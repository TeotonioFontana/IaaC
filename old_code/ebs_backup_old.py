#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EBS Volume Full Backup (Cross-Region) — Run-scoped S3 layout + Helper lock & pre-clear
=====================================================================================

Version: 1.22.0

What’s new in 1.22.0
--------------------
- **--preview**: discovery + plan only, prints what would run, then exits with no side effects.
- **--simulate**: runs read-only phases (discovery, SSM inspect, planning, manifest write),
  and logs “Would …” for all mutating actions (snapshots, copies, S3 uploads, helper lock,
  pre-clear, temp volume attach/delete, SSM streaming). No resource changes occur.

What’s new in 1.21.2
--------------------
- Bugfix in snapshot loop: pass `vol` dict correctly.

Recent features
---------------
- Helper exclusivity lock (S3), helper pre-clear, fatal-on-full-volume errors,
  richer SSM diagnostics, fail-fast, always-cleanup.
"""

from __future__ import annotations
import argparse
import atexit
import json
import logging
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Any, Tuple

import boto3
from botocore.exceptions import ClientError, WaiterError

# ----- Script identity -----
SCRIPT_NAME = "EBS Volume Full Backup (Cross-Region)"
SCRIPT_VERSION = "1.22.0"
SCRIPT_OBJECTIVE = (
    "Create EBS snapshots, optional encrypted cross-region copies, and/or full-volume images to S3; "
    "record a manifest and optionally upload it to S3 (run-scoped layout with indexes)."
)

# ---------- Utilities ----------
def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def run_id_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

def secs_since(t0: float) -> float:
    return round(time.time() - t0, 3)

def safe_name(s: str) -> str:
    s = (s or "").strip()
    return s.replace("/", "_").replace("\\", "_").replace("  ", " ")

def load_config_file(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        raise SystemExit(f"--config file not found: {p}")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    if suffix in (".yml", ".yaml"):
        try:
            import yaml  # type: ignore
        except Exception:
            raise SystemExit("PyYAML is required for YAML configs. Install with: pip install pyyaml")
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text or "{}")
    if not isinstance(data, dict):
        raise SystemExit("Config must be a mapping/object at the top level.")
    return data

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": utc_iso(), "level": record.levelname, "msg": record.getMessage()}
        for k in ("step", "phase", "ctx"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        return json.dumps(payload, ensure_ascii=False)

class TextFormatter(logging.Formatter):
    def __init__(self, fmt: str): super().__init__(fmt)
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        parts = [base]
        if hasattr(record, "phase"): parts.append(f"phase={record.phase}")
        if hasattr(record, "step"): parts.append(f"step={record.step}")
        if hasattr(record, "ctx") and isinstance(record.ctx, dict) and record.ctx:
            try: parts.append(json.dumps(record.ctx, ensure_ascii=False))
            except Exception: parts.append(repr(record.ctx))
        return " ".join(parts)

class JsonArrayFileHandler(logging.FileHandler):
    def __init__(self, filename: str, mode: str = "w", encoding: Optional[str] = "utf-8"):
        super().__init__(filename, mode=mode, encoding=encoding, delay=False)
        self._first = True
        self.stream.write("["); self.stream.flush()
        atexit.register(self._close_array)
    def emit(self, record: logging.LogRecord) -> None:
        try:
            js = self.format(record)
            if not self._first: self.stream.write(",\n")
            else: self._first = False
            self.stream.write(js); self.stream.flush()
        except Exception:
            self.handleError(record)
    def _close_array(self):
        try: self.stream.write("]\n"); self.stream.flush()
        except Exception: pass

class JsonArrayStreamHandler(logging.StreamHandler):
    def __init__(self, stream=None):
        super().__init__(stream if stream is not None else sys.stdout)
        self._first = True
        self.stream.write("["); self.stream.flush()
        atexit.register(self._close_array)
    def emit(self, record: logging.LogRecord) -> None:
        try:
            js = self.format(record)
            if not self._first: self.stream.write(",\n")
            else: self._first = False
            self.stream.write(js); self.stream.flush()
        except Exception:
            self.handleError(record)
    def _close_array(self):
        try: self.stream.write("]\n"); self.stream.flush()
        except Exception: pass

def build_logger(name: str, log_file: Optional[str], json_mode: bool, json_array: bool, level: int) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False
    fmt = JsonFormatter() if json_mode else TextFormatter("[%(levelname)s] %(message)s")
    if log_file:
        p = Path(log_file); p.parent.mkdir(parents=True, exist_ok=True)
        handler = JsonArrayFileHandler(log_file, mode="w", encoding="utf-8") if (json_mode and json_array) \
                  else logging.FileHandler(log_file, mode="w", encoding="utf-8")
    else:
        handler = JsonArrayStreamHandler(sys.stdout) if (json_mode and json_array) \
                  else logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt); logger.addHandler(handler)
    return logger

def log_step(logger: logging.Logger, phase: str, step: str, **ctx):
    logger.info(f"{phase}:{step}", extra={"phase": phase, "step": step, "ctx": ctx})

def flatten_tags(tags_list: Optional[List[Dict[str, str]]]) -> Dict[str, str]:
    return {t["Key"]: t["Value"] for t in (tags_list or [])}

def prompt_yes_no(logger: logging.Logger, question: str, assume_yes: bool, non_interactive_abort_msg: str) -> bool:
    if assume_yes:
        log_step(logger, "PROMPT", "AUTO-CONTINUE", Reason="--yes supplied", Question=question)
        return True
    if not sys.stdin.isatty():
        log_step(logger, "PROMPT", "ABORT", Reason="Non-interactive stdin; supply --yes", Question=question)
        if non_interactive_abort_msg: print(non_interactive_abort_msg)
        return False
    try: ans = input(f"{question} [y/N]: ").strip().lower()
    except EOFError: ans = ""
    if ans in ("y","yes"):
        log_step(logger, "PROMPT", "CONFIRMED", Answer=ans, Question=question); return True
    log_step(logger, "PROMPT", "CANCELLED", Answer=ans or "(empty)", Question=question); return False

def confirm_phase(args, logger: logging.Logger, question: str, abort_reason: str):
    if not args.verbose or args.preview:  # never prompt in preview
        return
    ok = prompt_yes_no(logger, question, assume_yes=args.yes,
                       non_interactive_abort_msg="Refusing to continue without --yes in non-interactive mode.")
    if not ok: raise SystemExit(abort_reason)

# ---------- Data structures ----------
@dataclass
class BackupRecord:
    VolumeId: str
    VolumeType: str
    SizeGiB: int
    AvailabilityZone: str
    SrcRegion: str
    DstRegion: str
    SrcSnapshotId: Optional[str] = None
    DstSnapshotId: Optional[str] = None
    FullVolumeS3Bucket: Optional[str] = None
    FullVolumeS3Key: Optional[str] = None
    StartTime: str = ""
    EndTime: str = ""
    Tags: Optional[Dict[str, str]] = None
    Error: Optional[str] = None

# ---------- Discovery helpers ----------
def load_instance_name_map(ec2_client) -> Dict[str, str]:
    name_map: Dict[str, str] = {}
    paginator = ec2_client.get_paginator("describe_instances")
    for page in paginator.paginate():
        for r in page.get("Reservations", []):
            for inst in r.get("Instances", []):
                inst_id = inst["InstanceId"]; name = ""
                for t in inst.get("Tags", []):
                    if t.get("Key") == "Name": name = t.get("Value",""); break
                name_map[inst_id] = name
    return name_map

def describe_volumes(ec2_client, states: Iterable[str]) -> List[dict]:
    paginator = ec2_client.get_paginator("describe_volumes")
    filters = [{"Name":"status","Values":list(states)}] if states else []
    volumes: List[dict] = []
    for page in paginator.paginate(Filters=filters):
        volumes.extend(page.get("Volumes", []))
    return volumes

# ---- SSM mount discovery ----
def ssm_collect_lsblk(ssm_client, instance_ids: List[str], logger: logging.Logger,
                      timeout_sec: int = 90) -> Tuple[Dict[str, dict], Dict[str, str]]:
    data_map: Dict[str, dict] = {}; status_map: Dict[str,str] = {}
    if not instance_ids: return data_map, status_map
    log_step(logger, "DISCOVER", "SSM_START", InstanceCount=len(instance_ids))
    try:
        resp = ssm_client.send_command(
            InstanceIds=instance_ids,
            DocumentName="AWS-RunShellScript",
            Parameters={"commands":[
                "which lsblk >/dev/null 2>&1 || exit 4",
                "lsblk -Jo NAME,KNAME,PATH,SERIAL,MODEL,MOUNTPOINT,FSTYPE,SIZE"
            ]},
            TimeoutSeconds=timeout_sec
        )
    except ClientError as e:
        err = str(e); log_step(logger, "DISCOVER", "SSM_ERROR", Error=err)
        for iid in instance_ids:
            data_map[iid]={"error":err}; status_map[iid]=f"error:{err}"
        return data_map, status_map
    cmd_id = resp["Command"]["CommandId"]; deadline = time.time()+timeout_sec
    for iid in instance_ids:
        while True:
            if time.time()>deadline:
                data_map[iid]={"error":"timeout"}; status_map[iid]="error:timeout"; break
            try:
                inv = ssm_client.get_command_invocation(CommandId=cmd_id, InstanceId=iid)
                status = inv.get("Status")
                if status in ("Success","Failed","Cancelled","TimedOut"):
                    if status=="Success":
                        text = inv.get("StandardOutputContent","").strip()
                        try:
                            parsed = json.loads(text) if text else {}
                            data_map[iid] = parsed or {"note":"no output"}
                            status_map[iid] = "ok" if "blockdevices" in json.dumps(parsed).lower() else "error:no-blockdevices"
                        except Exception as je:
                            msg=f"json-parse:{je}"; data_map[iid]={"error":msg,"raw":text[:4000]}; status_map[iid]=f"error:{msg}"
                    else:
                        stderr=(inv.get("StandardErrorContent","") or "")[:4000]
                        data_map[iid]={"error":status,"stderr":stderr}; status_map[iid]=f"error:{status}"
                    break
            except ClientError: time.sleep(2.0); continue
            time.sleep(2.0)
    ok_count=sum(1 for v in status_map.values() if v=="ok")
    log_step(logger, "DISCOVER", "SSM_END", Count=len(status_map), OK=ok_count, Errors=len(status_map)-ok_count)
    return data_map, status_map

def _iter_lsblk_nodes(node: Dict[str, Any]):
    yield node
    for ch in node.get("children",[]) or []: yield from _iter_lsblk_nodes(ch)

def find_mounts_for_volume(lsblk_data: dict, volume_id: str) -> List[str]:
    if not lsblk_data or "blockdevices" not in lsblk_data: return []
    vid_norm = volume_id.replace("-","").lower(); mounts: List[str]=[]
    for root in lsblk_data.get("blockdevices",[]):
        for n in _iter_lsblk_nodes(root):
            serial=(n.get("serial") or "").replace("-","").lower()
            if vid_norm and serial and vid_norm in serial:
                mp=n.get("mountpoint");  mps=[]
                if mp: mps.append(mp)
                for ch in _iter_lsblk_nodes(n):
                    cmp=ch.get("mountpoint")
                    if cmp: mps.append(cmp)
                mounts.extend(mps)
    seen=set(); uniq=[]
    for m in mounts:
        if m not in seen: uniq.append(m); seen.add(m)
    return uniq

# ---------- Clear discovery logging ----------
def log_discovery_items(logger: logging.Logger, volumes: List[dict], instance_name_map: Dict[str, str],
                        ssm_map: Optional[Dict[str, dict]] = None):
    for v in volumes:
        vid=v["VolumeId"]; size=v["Size"]; vtype=v.get("VolumeType","unknown"); az=v["AvailabilityZone"]
        iops=v.get("Iops"); throughput=v.get("Throughput"); encrypted=v.get("Encrypted")
        state=v.get("State") or v.get("Status"); vtags=flatten_tags(v.get("Tags")); vname=vtags.get("Name","")
        att_rows=[]
        for att in v.get("Attachments",[]) or []:
            iid=att.get("InstanceId"); dev=att.get("Device"); astate=att.get("State"); iname=instance_name_map.get(iid,"") if iid else ""
            mounts: List[str]=[]
            if ssm_map and iid and isinstance(ssm_map.get(iid),dict): mounts=find_mounts_for_volume(ssm_map.get(iid) or {}, vid)
            att_rows.append({"InstanceId":iid,"InstanceName":iname or None,"DeviceName":dev,"AttachState":astate,"MountPoints":mounts or None})
        log_step(logger,"DISCOVER","ITEM",VolumeId=vid,VolumeName=(vname or None),SizeGiB=size,VolumeType=vtype,AZ=az,
                 State=state,Encrypted=encrypted,Iops=iops,Throughput=throughput,
                 Tags=(vtags if vname=="" else {k:v for k,v in vtags.items() if k!="Name"}),
                 Attachments=att_rows or None)
    by_state=Counter([v.get("State") or v.get("Status") or "unknown" for v in volumes])
    by_az=Counter([v["AvailabilityZone"] for v in volumes])
    by_type=Counter([v.get("VolumeType","unknown") for v in volumes])
    log_step(logger,"DISCOVER","SUMMARY",Count=len(volumes),ByState=dict(by_state),ByAZ=dict(by_az),ByType=dict(by_type))

# ---------- Snapshot operations ----------
def create_snapshot_for_volume(src_client, vol: dict, tags: Dict[str, str], logger: logging.Logger, snapshot_name: str, simulate: bool=False) -> str:
    t0=time.time(); vid=vol["VolumeId"]; size=vol["Size"]; az=vol["AvailabilityZone"]
    desc=f"IaaC full-backup {vid} at {utc_iso()}"
    tags_with_name=dict(tags); tags_with_name["Name"]=snapshot_name
    tag_spec=[{"ResourceType":"snapshot","Tags":[{"Key":k,"Value":v} for k,v in tags_with_name.items()]}]
    if simulate:
        log_step(logger,"SNAPSHOT","SIMULATE_CREATE",Action="CreateSnapshot",VolumeId=vid,SizeGiB=size,AZ=az,
                 Description=desc,Tags=tags_with_name,SnapshotName=snapshot_name)
        return f"sim-snap-{vid[-8:].replace('-','')}"
    log_step(logger,"SNAPSHOT","START",Action="CreateSnapshot",VolumeId=vid,SizeGiB=size,AZ=az,
             Description=desc,Tags=tags_with_name,SnapshotName=snapshot_name)
    resp=src_client.create_snapshot(VolumeId=vid, Description=desc, TagSpecifications=tag_spec)
    snap_id=resp["SnapshotId"]
    log_step(logger,"SNAPSHOT","END",SnapshotId=snap_id,VolumeId=vid,ElapsedSec=secs_since(t0),SnapshotName=snapshot_name)
    print(f"[SNAPSHOT] Source snapshot created: {snap_id}  Name='{snapshot_name}'  Volume='{vid}'", file=sys.stderr)
    return snap_id

def wait_snapshot_complete(ec2_client, snapshot_id: str, logger: logging.Logger, delay: int = 15, max_attempts: int = 400, simulate: bool=False):
    if simulate:
        log_step(logger,"WAIT","SIMULATE_SKIP",ResourceType="Snapshot",SnapshotId=snapshot_id)
        return
    t0=time.time(); log_step(logger,"WAIT","START",ResourceType="Snapshot",SnapshotId=snapshot_id)
    waiter=ec2_client.get_waiter("snapshot_completed")
    waiter.wait(SnapshotIds=[snapshot_id], WaiterConfig={"Delay":delay,"MaxAttempts":max_attempts})
    log_step(logger,"WAIT","END",ResourceType="Snapshot",SnapshotId=snapshot_id,ElapsedSec=secs_since(t0))

def copy_snapshot(dst_client, src_region: str, snapshot_id: str, tags: Dict[str, str], logger: logging.Logger,
                  snapshot_name: str, encrypt: bool, kms_key_id: Optional[str], simulate: bool=False) -> str:
    t0=time.time()
    tags_with_name=dict(tags); tags_with_name["Name"]=snapshot_name
    if simulate:
        log_step(logger,"COPY","SIMULATE",SourceRegion=src_region,SourceSnapshotId=snapshot_id,
                 SnapshotName=snapshot_name,Encrypted=bool(encrypt),KmsKeyId=kms_key_id or "(default-key)")
        return f"sim-copy-{snapshot_id[-8:].replace('-','')}"
    tag_spec=[{"ResourceType":"snapshot","Tags":[{"Key":k,"Value":v} for k,v in tags_with_name.items()]}]
    kwargs=dict(SourceRegion=src_region, SourceSnapshotId=snapshot_id,
                Description=f"Copy of {snapshot_id} from {src_region}", TagSpecifications=tag_spec)
    if encrypt:
        kwargs["Encrypted"]=True
        if kms_key_id: kwargs["KmsKeyId"]=kms_key_id
    log_step(logger,"COPY","START",SourceRegion=src_region,SourceSnapshotId=snapshot_id,
             SnapshotName=snapshot_name,Encrypted=bool(encrypt),KmsKeyId=kms_key_id or "(default-key)")
    resp=dst_client.copy_snapshot(**kwargs)
    dst_snap=resp["SnapshotId"]
    log_step(logger,"COPY","END",DstSnapshotId=dst_snap,SourceSnapshotId=snapshot_id,
             ElapsedSec=secs_since(t0),SnapshotName=snapshot_name,Encrypted=bool(encrypt))
    print(f"[COPY] Destination snapshot created: {dst_snap}  Name='{snapshot_name}'  From='{snapshot_id}'  Encrypted={bool(encrypt)}", file=sys.stderr)
    return dst_snap

# ---------- Full-volume backup operations ----------
def _get_instance_az(ec2_client, instance_id: str) -> str:
    resp = ec2_client.describe_instances(InstanceIds=[instance_id])
    for r in resp.get("Reservations", []):
        for inst in r.get("Instances", []):
            return inst["Placement"]["AvailabilityZone"]
    raise SystemExit(f"Could not find helper instance {instance_id}")

def _get_root_device_name(ec2_client, instance_id: str) -> str:
    resp = ec2_client.describe_instances(InstanceIds=[instance_id])
    for r in resp.get("Reservations", []):
        for inst in r.get("Instances", []):
            return inst.get("RootDeviceName", "/dev/xvda")
    return "/dev/xvda"

def _wait_volume_state(ec2_client, volume_id: str, target: str, timeout: int = 900):
    deadline=time.time()+timeout
    while time.time()<deadline:
        resp=ec2_client.describe_volumes(VolumeIds=[volume_id])
        state=resp["Volumes"][0]["State"]
        print(f"\r[VOL state] {volume_id} -> {state}", file=sys.stderr, end="")
        if state==target:
            print("", file=sys.stderr)
            return
        time.sleep(5)
    raise TimeoutError(f"Timeout waiting for volume {volume_id} to reach state {target}")

def _wait_attachment_state(ec2_client, volume_id: str, expected: str, timeout: int = 900):
    deadline=time.time()+timeout
    while time.time()<deadline:
        resp=ec2_client.describe_volumes(VolumeIds=[volume_id])
        att=resp["Volumes"][0].get("Attachments",[])
        cur = "attached" if (att and att[0]["State"]=="attached") else "detached"
        print(f"\r[ATTACH] {volume_id} -> {cur}", file=sys.stderr, end="")
        if (expected=="attached" and cur=="attached") or (expected=="detached" and cur=="detached"):
            print("", file=sys.stderr)
            return
        time.sleep(5)
    raise TimeoutError(f"Timeout waiting for volume {volume_id} attachment state {expected}")

def preclear_helper_instance(ec2_client, helper_instance_id: str, logger: logging.Logger, simulate: bool):
    root_dev = _get_root_device_name(ec2_client, helper_instance_id)
    if simulate:
        log_step(logger, "HELPER", "SIMULATE_PRECLEAR", InstanceId=helper_instance_id, RootDevice=root_dev)
        print(f"[SIMULATE] Would pre-clear non-root volumes on helper {helper_instance_id}", file=sys.stderr)
        return
    log_step(logger, "HELPER", "PRECLEAR_START", InstanceId=helper_instance_id, RootDevice=root_dev)

    vols = ec2_client.describe_volumes(
        Filters=[{"Name":"attachment.instance-id","Values":[helper_instance_id]}]
    )["Volumes"]

    to_detach = []
    for v in vols:
        att = v.get("Attachments", [])
        if not att: continue
        dev = att[0].get("Device")
        if dev and dev != root_dev:
            to_detach.append((v["VolumeId"], dev, att[0].get("State")))

    if not to_detach:
        log_step(logger, "HELPER", "PRECLEAR_NONE", InstanceId=helper_instance_id)
        print(f"[HELPER] No non-root attachments on {helper_instance_id}.", file=sys.stderr)
        return

    for vol_id, dev, state in to_detach:
        print(f"[HELPER] Detaching {vol_id} mapped at {dev} (state={state})", file=sys.stderr)
        try:
            ec2_client.detach_volume(VolumeId=vol_id, InstanceId=helper_instance_id)
        except ClientError as e:
            if e.response.get("Error",{}).get("Code") in ("IncorrectState","VolumeInUse"):
                ec2_client.detach_volume(VolumeId=vol_id, InstanceId=helper_instance_id, Force=True)
            else:
                raise
        _wait_attachment_state(ec2_client, vol_id, "detached", timeout=600)
        _wait_volume_state(ec2_client, vol_id, "available", timeout=600)

    log_step(logger, "HELPER", "PRECLEAR_END", InstanceId=helper_instance_id, Detached=len(to_detach))
    print(f"[HELPER] Pre-clear complete. Detached {len(to_detach)} volume(s).", file=sys.stderr)

def perform_full_volume_backup(
    ec2_dst, ssm_dst, helper_instance_id: str, dst_snapshot_id: str, base_name: str, size_gib: int,
    s3_bucket: str, s3_run_prefix: str, vol_id: str, fmt: str, delete_temp_volume: bool, logger: logging.Logger,
    extra_tags: Dict[str, str], simulate: bool=False
) -> Tuple[str, str]:
    """
    Create a temp volume from the destination snapshot, attach to helper instance, stream raw image to S3 via SSM.
    Returns (bucket, key). In simulate mode, logs actions and returns simulated key.
    """
    if not s3_bucket:
        raise RuntimeError("Full-volume backup requires an S3 bucket (set --fullvol-s3-bucket or --s3-bucket).")
    helper_az = _get_instance_az(ec2_dst, helper_instance_id)
    safe_base = safe_name(base_name) if base_name else vol_id
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    sim_key = f"{(s3_run_prefix or '').rstrip('/')}/fullvol/{vol_id}/{safe_base}-snap-{dst_snapshot_id}-{ts}.img"
    if fmt == "raw.gz": sim_key += ".gz"
    if simulate:
        log_step(logger, "FULLVOL", "SIMULATE",
                 InstanceId=helper_instance_id, SnapshotId=dst_snapshot_id, AZ=helper_az,
                 S3Key=sim_key, Format=fmt, DeleteTemp=bool(delete_temp_volume), ExtraTags=extra_tags)
        print(f"[SIMULATE] Would create temp volume from {dst_snapshot_id} in {helper_az}, attach to {helper_instance_id}, stream to s3://{s3_bucket}/{sim_key}", file=sys.stderr)
        return s3_bucket, sim_key

    # Real path:
    # 1) Create temp volume
    log_step(logger, "FULLVOL", "CREATE_VOL_START", SnapshotId=dst_snapshot_id, AZ=helper_az, SizeGiB=size_gib)
    tag_spec=[{"ResourceType":"volume","Tags":[{"Key":"Name","Value":f"tmp-fullvol-{safe_base}"},
                                             *({"Key":k,"Value":v} for k,v in extra_tags.items())]}]
    resp = ec2_dst.create_volume(SnapshotId=dst_snapshot_id, AvailabilityZone=helper_az, TagSpecifications=tag_spec)
    tmp_vol_id = resp["VolumeId"]
    log_step(logger, "FULLVOL", "CREATE_VOL_END", VolumeId=tmp_vol_id)
    _wait_volume_state(ec2_dst, tmp_vol_id, "available", timeout=1800)

    # 2) Attach to helper, then ALWAYS detach/delete in finally
    log_step(logger, "FULLVOL", "ATTACH_START", VolumeId=tmp_vol_id, InstanceId=helper_instance_id)
    ec2_dst.attach_volume(InstanceId=helper_instance_id, VolumeId=tmp_vol_id, Device="/dev/sdf")
    _wait_attachment_state(ec2_dst, tmp_vol_id, "attached", timeout=900)
    log_step(logger, "FULLVOL", "ATTACH_END", VolumeId=tmp_vol_id)

    try:
        # 3) SSM stream to S3
        key = sim_key  # reuse computed name
        s3_uri = f"s3://{s3_bucket}/{key.lstrip('/')}"
        script = f"""#!/bin/bash
set -euo pipefail
VOLID="{tmp_vol_id}"
VID_NODASH="${{VOLID//-/}}"
LINKS=(
  "/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_$VID_NODASH"
  "/dev/disk/by-id/virtio-$VID_NODASH"
  "/dev/disk/by-id/scsi-0AWS_EC2_$VID_NODASH"
)
DEV=""
for L in "${{LINKS[@]}}"; do
  for i in $(seq 1 120); do
    if [ -e "$L" ]; then DEV=$(readlink -f "$L"); break; fi
    sleep 2
  done
  [ -n "$DEV" ] && break
done
if [ -z "$DEV" ]; then echo "[fullvol][error] Device link not found for $VOLID" >&2; exit 2; fi
BYTES=$(blockdev --getsize64 "$DEV" || echo 0)
command -v aws >/dev/null 2>&1 || {{ echo "[fullvol][error] aws CLI missing" >&2; exit 3; }}
if [ "{fmt}" = "raw.gz" ]; then
  dd if="$DEV" bs=4M iflag=direct status=progress 2>/dev/stderr | gzip -1 | aws s3 cp - "{s3_uri}" --expected-size "$BYTES" --only-show-errors
else
  dd if="$DEV" bs=4M iflag=direct status=progress 2>/dev/stderr | aws s3 cp - "{s3_uri}" --expected-size "$BYTES" --only-show-errors
fi
echo "[fullvol][ok] Upload complete: {s3_uri}"
"""
        log_step(logger, "FULLVOL", "SSM_BACKUP_START", InstanceId=helper_instance_id, VolumeId=tmp_vol_id, S3Uri=s3_uri, Format=fmt)
        resp = ssm_dst.send_command(
            InstanceIds=[helper_instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands":[script]},
            TimeoutSeconds=60*60*8
        )
        cmd_id = resp["Command"]["CommandId"]

        last_status = ""
        inv = None
        started = time.time()
        while True:
            inv = ssm_dst.get_command_invocation(CommandId=cmd_id, InstanceId=helper_instance_id)
            status = inv.get("Status")
            if status != last_status:
                print(f"[SSM] status={status}", file=sys.stderr)
                last_status = status
            if status in ("Success","Failed","Cancelled","TimedOut"):
                break
            time.sleep(10)

        if status != "Success":
            # Tail stdout/stderr to keep the log readable but useful
            tail = 4000
            rc = inv.get("ResponseCode")
            sout = (inv.get("StandardOutputContent","") or "")
            serr = (inv.get("StandardErrorContent","") or "")
            sout_tail = sout[-tail:] if len(sout) > tail else sout
            serr_tail = serr[-tail:] if len(serr) > tail else serr

            hint = None
            if "AccessDenied" in serr or "AccessDenied" in sout:
                hint = ("S3 AccessDenied during upload. Ensure the helper instance role "
                        "has s3:PutObject (and ideally AbortMultipartUpload) on the target key/prefix, "
                        "and bucket policy/KMS conditions allow it.")
            elif "Device link not found" in serr or "Device link not found" in sout:
                hint = ("The temp volume symlink under /dev/disk/by-id was not found in time. "
                        "Check NVMe/virtio device mappings and consider increasing the probe wait.")
            elif "No space left" in serr or "No space left" in sout:
                hint = ("ENOSPC encountered. Verify the source block device and streaming pipeline; "
                        "also check any intermediary filesystem constraints.")
            elif "ssl" in serr.lower() and "aws s3" in serr.lower():
                hint = ("Network/SSL error during aws s3 cp. Check VPC egress, proxy, or S3 VPC endpoint config.")

            log_step(
                logger, "FULLVOL", "SSM_BACKUP_FAIL",
                InstanceId=helper_instance_id, VolumeId=tmp_vol_id, S3Uri=s3_uri,
                ResponseCode=rc, DurationSec=round(time.time()-started, 1),
                StdoutTail=sout_tail, StderrTail=serr_tail, Hint=hint or "(none)"
            )

            print("\n[FULLVOL][SSM-FAIL]")
            print(f"  instance={helper_instance_id}")
            print(f"  tmp_volume={tmp_vol_id}")
            print(f"  s3_uri={s3_uri}")
            print(f"  status={status} rc={rc} duration={round(time.time()-started,1)}s")
            if hint:
                print(f"  hint={hint}")
            print("  --- STDERR (tail) ---")
            sys.stdout.write((serr_tail or "").rstrip() + "\n")
            print("  --- STDOUT (tail) ---")
            sys.stdout.write((sout_tail or "").rstrip() + "\n")

            raise RuntimeError(f"{status}: rc={rc} (see SSM stderr/stdout tails above)")

        return s3_bucket, key

    finally:
        # 4) Detach & delete temp volume — ALWAYS
        try:
            log_step(logger, "FULLVOL", "DETACH_START", VolumeId=tmp_vol_id, InstanceId=helper_instance_id)
            ec2_dst.detach_volume(VolumeId=tmp_vol_id, InstanceId=helper_instance_id, Force=False)
            _wait_attachment_state(ec2_dst, tmp_vol_id, "detached", timeout=900)
            _wait_volume_state(ec2_dst, tmp_vol_id, "available", timeout=900)
            log_step(logger, "FULLVOL", "DETACH_END", VolumeId=tmp_vol_id)
        except Exception as de:
            log_step(logger, "FULLVOL", "DETACH_ERROR", VolumeId=tmp_vol_id, Error=str(de))
            print(f"[FULLVOL][WARN] Detach error for {tmp_vol_id}: {de}", file=sys.stderr)
        try:
            if delete_temp_volume:
                log_step(logger, "FULLVOL", "DELETE_START", VolumeId=tmp_vol_id)
                ec2_dst.delete_volume(VolumeId=tmp_vol_id)
                log_step(logger, "FULLVOL", "DELETE_END", VolumeId=tmp_vol_id)
        except Exception as de:
            log_step(logger, "FULLVOL", "DELETE_ERROR", VolumeId=tmp_vol_id, Error=str(de))
            print(f"[FULLVOL][WARN] Delete error for {tmp_vol_id}: {de}", file=sys.stderr)

# ---------- S3 helpers ----------

# ---------------------------------------------------------------------
# Compatibility shim: write_snapshot_artifacts
#   Many older branches call this but never defined it. This helper
#   writes a simple JSON manifest to disk and optionally uploads it
#   to S3. It is intentionally permissive about parameters so we
#   don’t have to touch call sites elsewhere in the script.
# ---------------------------------------------------------------------
def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p

def write_snapshot_artifacts(*args, **kwargs) -> str:
    """
    Backwards-compatible artifact writer.

    Accepts any of the following shapes (best-effort parsing):
      - write_snapshot_artifacts(manifest_path, records, s3_bucket=None, s3_prefix=None, s3_client=None, **extra)
      - write_snapshot_artifacts(out_dir, run_id, records, s3_bucket=None, s3_prefix=None, **extra)
      - write_snapshot_artifacts(records=<list>, manifest_path=<path>, s3_bucket=..., s3_prefix=..., s3_client=...)

    It will:
      1) Write a minimal manifest JSON with {"meta": ..., "items": ...}
      2) If s3_bucket is provided, upload to s3://{bucket}/{prefix}/manifests/<manifest-filename>
         (non-fatal on upload errors)

    Returns the manifest path as a string.
    """
    # ---- figure out where to write ----
    manifest_path = kwargs.get("manifest_path")
    out_dir = kwargs.get("out_dir")

    if not manifest_path and out_dir:
        manifest_path = Path(out_dir) / "ebs_backup_manifest.json"

    # If still missing, try first positional arg as a path
    if not manifest_path and args:
        a0 = args[0]
        if isinstance(a0, (str, Path)) and str(a0).lower().endswith(".json"):
            manifest_path = Path(a0)

    if not manifest_path:
        # ultimate fallback so we never crash
        manifest_path = Path("results") / "ebs_backup_manifest.json"

    manifest_path = Path(manifest_path)

    # ---- collect the items/records ----
    records = (
        kwargs.get("records")
        or kwargs.get("snapshots")
        or (args[1] if len(args) >= 2 and isinstance(args[1], list) else None)
        or []
    )

    # ---- write the file ----
    data = {
        "meta": {
            "generated_utc": _utc_iso(),
            "count": len(records),
        },
        "items": records,
    }
    _ensure_dir(manifest_path.parent)
    try:
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"[ARTIFACTS] Manifest written: {manifest_path}")
    except Exception as e:
        # Don’t break the backup because we couldn’t write the manifest
        print(f"[WARN] Could not write manifest to {manifest_path}: {e}", file=sys.stderr)
        # still return a string path for callers
        return str(manifest_path)

    # ---- optional S3 upload ----
    # FIX: bucket is args[1], prefix is args[2] in your call sites
    s3_bucket = kwargs.get("s3_bucket") or (args[1] if len(args) >= 2 and isinstance(args[1], str) else None)
    s3_prefix = (kwargs.get("s3_prefix") or (args[2] if len(args) >= 3 and isinstance(args[2], str) else "tf-backup/")).rstrip("/")
    if s3_bucket:
        key = f"{s3_prefix}/manifests/{manifest_path.name}".lstrip("/")
        try:
            s3 = kwargs.get("s3_client") or boto3.client("s3")
            s3.upload_file(str(manifest_path), s3_bucket, key)
            print(f"[ARTIFACTS] Manifest uploaded to s3://{s3_bucket}/{key}")
        except Exception as e:
            print(f"[WARN] Could not upload manifest to s3://{s3_bucket}/{key}: {e}", file=sys.stderr)

    return str(manifest_path)

def s3_put_json(s3_client, bucket: str, key: str, obj: dict, storage_class: Optional[str] = None, if_none_match: Optional[str] = None, simulate: bool=False):
    if simulate:
        print(f"[SIMULATE] Would PUT manifest/index to s3://{bucket}/{key}", file=sys.stderr)
        return
    body = json.dumps(obj, indent=2).encode("utf-8")
    extra = {}
    if storage_class:
        extra["StorageClass"] = storage_class
    if if_none_match is not None:
        extra["IfNoneMatch"] = if_none_match
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, **extra)

def s3_get_json(s3_client, bucket: str, key: str) -> Optional[dict]:
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        data = resp["Body"].read()
        return json.loads(data.decode("utf-8"))
    except s3_client.exceptions.NoSuchKey:
        return None
    except ClientError as e:
        if e.response.get("Error",{}).get("Code") in ("NoSuchKey","404","NotFound"):
            return None
        raise

def upload_manifest_to_s3(s3_client, bucket: str, key: str, local_path: Path, storage_class: str, logger: logging.Logger, simulate: bool=False):
    if simulate:
        log_step(logger, "MANIFEST", "SIMULATE_S3_UPLOAD", Bucket=bucket, Key=key, StorageClass=storage_class, Bytes=local_path.stat().st_size)
        print(f"[SIMULATE] Would upload manifest {local_path} to s3://{bucket}/{key}", file=sys.stderr)
        return
    log_step(logger, "MANIFEST", "S3_UPLOAD_START", Bucket=bucket, Key=key, StorageClass=storage_class, Bytes=local_path.stat().st_size)
    s3_client.upload_file(Filename=str(local_path), Bucket=bucket, Key=key, ExtraArgs={"StorageClass": storage_class})
    log_step(logger, "MANIFEST", "S3_UPLOAD_END", Bucket=bucket, Key=key, StorageClass=storage_class)

def upload_log_to_s3_if_present(s3_client, bucket: str, key: str, log_file: Optional[str], storage_class: str, logger: logging.Logger, simulate: bool=False):
    if not log_file: return
    p = Path(log_file)
    if not p.exists(): return
    if simulate:
        log_step(logger, "LOGS", "SIMULATE_S3_UPLOAD", Bucket=bucket, Key=key, StorageClass=storage_class, Bytes=p.stat().st_size)
        print(f"[SIMULATE] Would upload log {p} to s3://{bucket}/{key}", file=sys.stderr)
        return
    log_step(logger, "LOGS", "S3_UPLOAD_START", Bucket=bucket, Key=key, StorageClass=storage_class, Bytes=p.stat().st_size)
    s3_client.upload_file(Filename=str(p), Bucket=bucket, Key=key, ExtraArgs={"StorageClass": storage_class})
    log_step(logger, "LOGS", "S3_UPLOAD_END", Bucket=bucket, Key=key, StorageClass=storage_class)

def index_latest_key(prefix: str) -> str:
    return f"{prefix.rstrip('/')}/index/latest.json"

def index_by_volume_key(prefix: str, vol_id: str) -> str:
    return f"{prefix.rstrip('/')}/index/by-volume/{vol_id}.json"

def index_by_snapshot_key(prefix: str, snapshot_id: str) -> str:
    return f"{prefix.rstrip('/')}/index/by-snapshot/{snapshot_id}.json"

def append_volume_index_entry(s3_client, bucket: str, prefix: str, vol_id: str, entry: dict, storage_class: Optional[str] = None, simulate: bool=False):
    key = index_by_volume_key(prefix, vol_id)
    current = s3_get_json(s3_client, bucket, key) or {"VolumeId": vol_id, "Entries": []}
    current["Entries"] = [entry] + (current.get("Entries") or [])   # prepend newest
    s3_put_json(s3_client, bucket, key, current, storage_class=storage_class, simulate=simulate)

def write_latest_pointer(s3_client, bucket: str, prefix: str, run_id: str, storage_class: Optional[str] = None, simulate: bool=False):
    key = index_latest_key(prefix)
    s3_put_json(s3_client, bucket, key, {"run_id": run_id}, storage_class=storage_class, simulate=simulate)

# ---------- Intro & confirmations ----------
def intro_banner(mode: str):
    print(f"[START] {SCRIPT_NAME} — v{SCRIPT_VERSION}", file=sys.stderr)
    print(f"        Objective: {SCRIPT_OBJECTIVE}", file=sys.stderr)
    print(f"        Started (UTC): {utc_iso()}", file=sys.stderr)
    print(f"        Mode: {mode}", file=sys.stderr)

def intro_and_confirm(args, session_src, logger: logging.Logger, run_id: str):
    account=None
    try:
        sts=session_src.client("sts"); ident=sts.get_caller_identity(); account=ident.get("Account")
    except Exception: account=None
    cfg = {
        "ScriptName": SCRIPT_NAME, "Version": SCRIPT_VERSION, "Objective": SCRIPT_OBJECTIVE,
        "RunId": run_id,
        "SrcRegion": args.src_region, "DstRegion": args.dst_region, "Profile": args.profile or "(default)", "Account": account or "(unknown)",
        "States": args.states, "FilterTags": args.filter_tag or [], "SnapshotTags": args.tag or [],
        "BackupType": args.backup_type, "EncryptDst": bool(args.encrypt_dst), "KmsKeyId": args.kms_key_id or "(default-key)",
        "DeleteSrcAfterCopy": bool(args.delete_src_after_copy),
        "ManifestPath": args.manifest_file, "LogFile": args.log_file or "(stdout only)",
        "JSONLogs": bool(args.log_json), "JSONArray": bool(args.log_json_array),
        "Verbose": bool(args.verbose), "SSMInspect": bool(args.ssm_inspect),
        "S3Bucket": args.s3_bucket or "(none)", "S3Prefix": args.s3_prefix or "(n/a)", "S3StorageClass": args.s3_storage_class if args.s3_bucket else "(n/a)",
        "FullVolBucket": args.fullvol_s3_bucket or args.s3_bucket or "(none)", "FullVolPrefix": "(run-scoped)/fullvol/",
        "FullVolFormat": args.fullvol_format, "HelperInstance": args.helper_instance_id or "(none)",
        "KeepTempVolume": bool(args.fullvol_keep_temp_volume),
        "Preview": bool(args.preview), "Simulate": bool(args.simulate)
    }
    log_step(logger, "INTRO", "IDENTIFY", **cfg)
    if args.verbose and not args.preview:
        log_step(logger, "INTRO", "DETAILS",
                 Notes=("Operation creates EBS snapshots and/or full-volume images via a helper instance. "
                        "Requires EC2, S3, SSM, and (optional) KMS permissions."))

    if not args.ssm_inspect and not args.preview:
        log_step(logger, "ALERT", "SSM_NOT_USED", Message="--ssm-inspect not supplied; OS mount points will NOT be collected.")
        if args.verbose and not args.simulate:
            ok = prompt_yes_no(logger, "Proceed WITHOUT SSM mount inspection (mount points will not be logged)?",
                               assume_yes=args.yes, non_interactive_abort_msg="Refusing to continue without --yes in non-interactive mode (SSM not used).")
            if not ok: raise SystemExit("Cancelled by user (SSM not used).")

    if args.backup_type in ("full-volume","both") and not args.preview:
        if not (args.fullvol_s3_bucket or args.s3_bucket):
            raise SystemExit("Full-volume backup requires an S3 bucket (--fullvol-s3-bucket or --s3-bucket).")
        if not args.helper_instance_id:
            raise SystemExit("Full-volume backup requires --helper-instance-id (in destination region).")

    if args.preview:
        return  # never prompt in preview

    if args.yes or args.simulate:
        log_step(logger, "PROMPT", "AUTO-CONTINUE", Reason="--yes or --simulate supplied"); return
    if not sys.stdin.isatty():
        log_step(logger, "PROMPT", "ABORT", Reason="Non-interactive stdin; supply --yes to skip confirmation")
        raise SystemExit("Refusing to prompt without TTY. Re-run with --yes.")
    if not prompt_yes_no(logger, f"{SCRIPT_NAME} v{SCRIPT_VERSION} — proceed?", assume_yes=False, non_interactive_abort_msg=""):
        raise SystemExit("Cancelled by user.")

# ---------- Lock helpers ----------
def acquire_helper_lock(s3_client, bucket: str, s3_prefix: str, helper_instance_id: str, run_id: str, profile: Optional[str], logger: logging.Logger, simulate: bool) -> str:
    lock_key = f"{s3_prefix.rstrip('/')}/locks/helper-{helper_instance_id}.lock"
    payload = {
        "run_id": run_id,
        "helper_instance_id": helper_instance_id,
        "owner_profile": profile or "(default)",
        "acquired_utc": utc_iso()
    }
    if simulate:
        log_step(logger, "LOCK", "SIMULATE_ACQUIRE", Key=lock_key, Helper=helper_instance_id)
        print(f"[SIMULATE] Would acquire helper lock s3://{bucket}/{lock_key}", file=sys.stderr)
        return lock_key
    try:
        s3_put_json(s3_client, bucket, lock_key, payload, storage_class="STANDARD", if_none_match="*")
        log_step(logger, "LOCK", "ACQUIRED", Key=lock_key, Helper=helper_instance_id)
        print(f"[LOCK] Acquired {lock_key}", file=sys.stderr)
        return lock_key
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code == "PreconditionFailed" or status == 412:
            log_step(logger, "LOCK", "EXISTS", Key=lock_key, Helper=helper_instance_id)
            raise SystemExit(f"Helper lock already exists: s3://{bucket}/{lock_key} — another run may be in progress.")
        raise

def release_helper_lock(s3_client, bucket: str, lock_key: str, logger: logging.Logger, simulate: bool):
    if simulate:
        log_step(logger, "LOCK", "SIMULATE_RELEASE", Key=lock_key)
        print(f"[SIMULATE] Would release helper lock s3://{bucket}/{lock_key}", file=sys.stderr)
        return
    try:
        s3_client.delete_object(Bucket=bucket, Key=lock_key)
        log_step(logger, "LOCK", "RELEASED", Key=lock_key)
        print(f"[LOCK] Released {lock_key}", file=sys.stderr)
    except ClientError as e:
        log_step(logger, "LOCK", "RELEASE_ERROR", Key=lock_key, Error=str(e))
        print(f"[LOCK][WARN] Could not release {lock_key}: {e}", file=sys.stderr)

# ---------- Main routine ----------
def main():
    # Phase 0: capture --config first
    base=argparse.ArgumentParser(add_help=False)
    base.add_argument("--config", default=None, help="Path to YAML/JSON config file whose values become defaults.")
    pre,_=base.parse_known_args()
    config = load_config_file(pre.config) if pre.config else {}
    def cget(key, default): return config.get(key, default)

    # Phase 1: full parser with config-backed defaults
    ap=argparse.ArgumentParser(description="EBS snapshots, cross-region copies, and/or full-volume images to S3.", parents=[base])

    # Core selection
    ap.add_argument("--backup-type", default=cget("backup_type","snapshot"),
                    choices=["snapshot","full-volume","both"],
                    help="What to back up: snapshots, full-volume images, or both (default: snapshot).")

    ap.add_argument("--profile", default=cget("profile", None), help="AWS profile.")
    ap.add_argument("--src-region", default=cget("src_region","us-east-2"), help="Source region (volumes).")
    ap.add_argument("--dst-region", default=cget("dst_region","us-east-1"), help="Destination region (copied snapshots/temp volumes).")
    ap.add_argument("--states", default=cget("states","in-use,available"), help="Volume states to include (comma-separated).")
    ap.add_argument("--filter-tag", action="append", default=cget("filter_tag", []), help="Filter volumes by tag key=value (repeatable).")
    ap.add_argument("--tag", action="append", default=cget("tag", []), help="Tags to apply to snapshots key=value (repeatable).")

    # Logging
    ap.add_argument("--log-file", default=cget("log_file", None), help="Write logs to file; if set, no console logs.")
    ap.add_argument("--log-json", action="store_true", default=cget("log_json", False), help="Structured JSON logs.")
    ap.add_argument("--log-json-array", action="store_true", default=cget("log_json_array", False), help="JSON array instead of JSON Lines.")
    ap.add_argument("--log-level", default=cget("log_level","INFO"), choices=["DEBUG","INFO","WARNING","ERROR"], help="Log level.")
    ap.add_argument("--manifest-file", default=cget("manifest_file","results/ebs_backup_manifest.json"), help="Manifest path (JSON).")

    # Confirmations
    ap.add_argument("--ssm-inspect", action="store_true", default=cget("ssm_inspect", False), help="Collect mount points via SSM.")
    ap.add_argument("--verbose", action="store_true", default=cget("verbose", False), help="Ask confirmation before each phase.")
    ap.add_argument("--yes", action="store_true", default=cget("yes", False), help="Skip prompts.")

    # Snapshot encryption controls
    ap.add_argument("--encrypt-dst", dest="encrypt_dst", action="store_true", default=cget("encrypt_dst", True), help="Encrypt destination snapshots (default).")
    ap.add_argument("--no-encrypt-dst", dest="encrypt_dst", action="store_false", help="Do NOT encrypt destination snapshots.")
    ap.add_argument("--kms-key-id", default=cget("kms_key_id", None), help="KMS key (alias/ARN) in destination region.")
    ap.add_argument("--delete-src-after-copy", action="store_true", default=cget("delete_src_after_copy", False), help="Delete source snapshot after successful encrypted copy.")

    # S3 manifest/log upload controls
    ap.add_argument("--s3-bucket", default=cget("s3_bucket", None), help="Upload manifest (and logs & indexes) to this S3 bucket (optional).")
    ap.add_argument("--s3-prefix", default=cget("s3_prefix","tf-backup/"), help="S3 key prefix for run folder and indexes.")
    ap.add_argument("--s3-region", default=cget("s3_region", None), help="S3 client region (default: --dst-region).")
    ap.add_argument("--s3-storage-class", default=cget("s3_storage_class","DEEP_ARCHIVE"),
                    choices=["STANDARD","STANDARD_IA","ONEZONE_IA","INTELLIGENT_TIERING","GLACIER_IR","GLACIER",
                             "DEEP_ARCHIVE","EXPRESS_ONEZONE","OUTPOSTS","SNOW","FSX_OPENZFS","REDUCED_REDUNDANCY"],
                    help="Storage class for manifest/log/snapshot metadata uploads.")

    # Full-volume backup controls
    ap.add_argument("--helper-instance-id", default=cget("helper_instance_id", None), help="Helper EC2 instance ID (in destination region).")
    ap.add_argument("--fullvol-s3-bucket", default=cget("fullvol_s3_bucket", None), help="S3 bucket for full-volume images (default: --s3-bucket).")
    ap.add_argument("--fullvol-format", default=cget("fullvol_format","raw.gz"), choices=["raw","raw.gz"], help="Image format (default: raw.gz).")
    ap.add_argument("--fullvol-keep-temp-volume", action="store_true", default=cget("fullvol_keep_temp_volume", False),
                    help="Keep the temporary volume (debugging). Default is to delete it.")

    # Safety modes
    ap.add_argument("--preview", action="store_true", default=cget("preview", False), help="Discovery + plan only; print what would run, no side effects.")
    ap.add_argument("--simulate", action="store_true", default=cget("simulate", False), help="Run read-only phases; log all mutating actions as 'Would ...'.")

    args = ap.parse_args()

    mode = "PREVIEW" if args.preview else "SIMULATE" if args.simulate else "EXECUTE"
    intro_banner(mode)

    # Build logger AFTER final args are known
    logger = build_logger("ebs-backup", args.log_file, args.log_json, args.log_json_array,
                          getattr(logging, args.log_level.upper(), logging.INFO))
    config_path = Path(pre.config).resolve() if pre.config else None
    if config_path:
        log_step(logger, "CONFIG", "LOADED", Path=str(config_path), Keys=sorted(list(config.keys())))

    # Sessions / clients
    session_kwargs = {};
    if args.profile: session_kwargs["profile_name"]=args.profile
    src_sess=boto3.Session(region_name=args.src_region, **session_kwargs)
    dst_sess=boto3.Session(region_name=args.dst_region, **session_kwargs)
    ec2_src=src_sess.client("ec2"); ec2_dst=dst_sess.client("ec2")
    ssm_dst=dst_sess.client("ssm")

    s3_client = None
    if args.s3_bucket:
        s3_region=args.s3_region or args.dst_region
        s3_client=boto3.Session(region_name=s3_region, **({"profile_name":args.profile} if args.profile else {})).client("s3")

    run_id = run_id_iso()
    s3_run_prefix = None
    if args.s3_bucket:
        norm_prefix = args.s3_prefix.strip("/")
        if norm_prefix.endswith("/manifests"):
            print(f"[WARN] s3_prefix '{args.s3_prefix}' ends with '/manifests/'. Normalizing to '{norm_prefix.rsplit('/manifests',1)[0]}/'", file=sys.stderr)
            args.s3_prefix = norm_prefix.rsplit("/manifests", 1)[0] + "/"
        s3_run_prefix = f"{args.s3_prefix.rstrip('/')}/runs/{run_id}"

    intro_and_confirm(args, src_sess, logger, run_id)

    # ===== DISCOVER =====
    confirm_phase(args, logger, question=f"Proceed to DISCOVER volumes in {args.src_region} (states: {args.states})?",
                  abort_reason="Cancelled by user at DISCOVER phase.")

    include_states=[s.strip() for s in args.states.split(",") if s.strip()]
    vol_tag_filters: Dict[str,str]={}
    for kv in args.filter_tag:
        if "=" not in kv: raise SystemExit(f"--filter-tag expects key=value, got: {kv}")
        k,v=kv.split("=",1); vol_tag_filters[k]=v

    snap_tags: Dict[str,str]={}
    for kv in args.tag:
        if "=" not in kv: raise SystemExit(f"--tag expects key=value, got: {kv}")
        k,v=kv.split("=",1); snap_tags[k]=v
    snap_tags.setdefault("BackupOrigin", args.src_region)
    snap_tags.setdefault("BackupTime", utc_iso())
    snap_tags.setdefault("BackupTool", f"ebs_backup.py v{SCRIPT_VERSION}")

    inst_name_map=load_instance_name_map(ec2_src)

    t0=time.time(); log_step(logger,"DISCOVER","START",States=list(include_states))
    volumes=describe_volumes(ec2_src, include_states)
    log_step(logger,"DISCOVER","FOUND",Count=len(volumes),ElapsedSec=secs_since(t0))

    if vol_tag_filters:
        def _match(vol:dict)->bool:
            tags=flatten_tags(vol.get("Tags"))
            return all(tags.get(k)==v for k,v in vol_tag_filters.items())
        pre_len=len(volumes); volumes=[v for v in volumes if _match(v)]
        log_step(logger,"DISCOVER","FILTER",FilterTags=vol_tag_filters,Before=pre_len,After=len(volumes))

    if not volumes:
        log_step(logger,"DISCOVER","EMPTY",Message="No volumes matched filters/states"); print("No volumes to back up.", file=sys.stderr); return

    # Optional SSM inspect
    ssm_map: Dict[str,dict]={}; ssm_status: Dict[str,str]={}
    if args.ssm_inspect and not args.preview:
        attached_instance_ids=sorted({att.get("InstanceId") for v in volumes for att in v.get("Attachments",[]) or [] if att.get("InstanceId")})
        if attached_instance_ids:
            confirm_phase(args, logger, question=f"Run SSM mount inspection on {len(attached_instance_ids)} attached instances?",
                          abort_reason="Cancelled by user at SSM INSPECT phase.")
            ssm_map, ssm_status = ssm_collect_lsblk(src_sess.client("ssm"), attached_instance_ids, logger)
        else:
            log_step(logger,"ALERT","SSM_SKIPPED",Message="No attached instances found; --ssm-inspect has nothing to inspect.")

    log_discovery_items(logger, volumes, inst_name_map, ssm_map if (args.ssm_inspect and not args.preview) else None)
    log_step(logger,"DISCOVER","END",Count=len(volumes))

    # ===== PLAN =====
    total_gib=sum(int(v.get("Size",0)) for v in volumes)
    total_tib=round(total_gib/1024.0,3)
    log_step(logger,"PLAN","SIZE",TotalVolumes=len(volumes),TotalSizeGiB=total_gib,TotalSizeTiB=total_tib,
             Note="EBS snapshot storage is incremental; shown value is raw attached capacity.")

    if args.preview:
        print(f"[PREVIEW] Would back up {len(volumes)} volume(s) totaling ~{total_gib} GiB ({total_tib:.3f} TiB). No actions performed.", file=sys.stderr)
        return

    confirm_phase(args, logger,
                  question=f"Backup plan: {len(volumes)} volumes totaling ~{total_gib} GiB ({total_tib:.3f} TiB). Proceed?",
                  abort_reason="Cancelled by user at BACKUP (size confirmation) phase.")

    # ===== PREP (locks & pre-clear) =====
    lock_key = None
    try:
        if args.backup_type in ("full-volume","both"):
            if not s3_client or not args.s3_bucket:
                raise SystemExit("Full-volume runs require --s3-bucket to create the helper lock (safety).")
            lock_key = acquire_helper_lock(s3_client, args.s3_bucket, args.s3_prefix, args.helper_instance_id, run_id, args.profile, logger, simulate=args.simulate)
            preclear_helper_instance(ec2_dst, args.helper_instance_id, logger, simulate=args.simulate)

        # ===== BACKUP =====
        manifest_path=Path(args.manifest_file); manifest_path.parent.mkdir(parents=True, exist_ok=True)
        records: List[BackupRecord]=[]
        index_entries_by_volume: Dict[str, List[dict]] = defaultdict(list)
        overall_t0=time.time()
        log_step(logger,"BACKUP","START",SrcRegion=args.src_region,DstRegion=args.dst_region,Count=len(volumes),
                 BackupType=args.backup_type,EncryptDst=bool(args.encrypt_dst),KmsKeyId=args.kms_key_id or "(default-key)", RunId=run_id,
                 Simulate=bool(args.simulate))

        fullvol_bucket = args.fullvol_s3_bucket or args.s3_bucket

        for vol in volumes:
            vid=vol["VolumeId"]; size=vol["Size"]; vtype=vol.get("VolumeType","unknown"); az=vol["AvailabilityZone"]
            vtags=flatten_tags(vol.get("Tags")); vname=vtags.get("Name","").strip()
            snapshot_name = vname if vname else vid
            safe_base = safe_name(vname) if vname else vid

            rec=BackupRecord(VolumeId=vid,VolumeType=vtype,SizeGiB=size,AvailabilityZone=az,
                             SrcRegion=args.src_region,DstRegion=args.dst_region,StartTime=utc_iso(),Tags=vtags)

            try:
                # SNAPSHOT path (or minimal for full-volume)
                if args.backup_type in ("snapshot","both"):
                    snap_id=create_snapshot_for_volume(ec2_src, vol, snap_tags, logger, snapshot_name, simulate=args.simulate)
                    rec.SrcSnapshotId=snap_id
                    wait_snapshot_complete(ec2_src, snap_id, logger, simulate=args.simulate)

                    dst_snapshot_id=copy_snapshot(ec2_dst, args.src_region, snap_id, snap_tags, logger,
                                                  snapshot_name=snapshot_name, encrypt=args.encrypt_dst, kms_key_id=args.kms_key_id,
                                                  simulate=args.simulate)
                    rec.DstSnapshotId=dst_snapshot_id
                    wait_snapshot_complete(ec2_dst, dst_snapshot_id, logger, simulate=args.simulate)

                    if args.s3_bucket and s3_client and s3_run_prefix:
                        if not args.simulate:
                            write_snapshot_artifacts(
                                s3_client, args.s3_bucket, args.s3_prefix, s3_run_prefix, run_id,
                                dst_snapshot_id, rec.SrcSnapshotId, vid, args.dst_region, args.encrypt_dst, args.kms_key_id
                            )
                        else:
                            print(f"[SIMULATE] Would write snapshot artifact/index entries for {dst_snapshot_id}", file=sys.stderr)

                else:
                    # full-volume only: still need a base snapshot (simulate or real)
                    snap_id=create_snapshot_for_volume(ec2_src, vol, snap_tags, logger, snapshot_name, simulate=args.simulate)
                    rec.SrcSnapshotId=snap_id
                    wait_snapshot_complete(ec2_src, snap_id, logger, simulate=args.simulate)
                    dst_snapshot_id = snap_id
                    if args.dst_region != args.src_region:
                        dst_snapshot_id=copy_snapshot(ec2_dst, args.src_region, snap_id, snap_tags, logger,
                                                      snapshot_name=snapshot_name, encrypt=args.encrypt_dst, kms_key_id=args.kms_key_id,
                                                      simulate=args.simulate)
                        wait_snapshot_complete(ec2_dst, dst_snapshot_id, logger, simulate=args.simulate)

                    if args.s3_bucket and s3_client and s3_run_prefix:
                        if not args.simulate:
                            write_snapshot_artifacts(
                                s3_client, args.s3_bucket, args.s3_prefix, s3_run_prefix, run_id,
                                dst_snapshot_id, rec.SrcSnapshotId, vid, args.dst_region, args.encrypt_dst, args.kms_key_id
                            )
                        else:
                            print(f"[SIMULATE] Would write snapshot artifact/index entries for {dst_snapshot_id}", file=sys.stderr)
                    rec.DstSnapshotId = dst_snapshot_id if args.dst_region == args.src_region else (dst_snapshot_id or None)

                # FULL-VOLUME path
                if args.backup_type in ("full-volume","both"):
                    base_snap = rec.DstSnapshotId or dst_snapshot_id
                    if not base_snap:
                        raise RuntimeError("No snapshot available to produce a full-volume image.")
                    s3b, s3k = perform_full_volume_backup(
                        ec2_dst=ec2_dst, ssm_dst=ssm_dst, helper_instance_id=args.helper_instance_id,
                        dst_snapshot_id=base_snap, base_name=safe_base, size_gib=size,
                        s3_bucket=(fullvol_bucket), s3_run_prefix=(s3_run_prefix or args.s3_prefix), vol_id=vid, fmt=args.fullvol_format,
                        delete_temp_volume=(not args.fullvol_keep_temp_volume), logger=logger,
                        extra_tags={"BackupTool": f"ebs_backup.py v{SCRIPT_VERSION}", "BackupTime": utc_iso()},
                        simulate=args.simulate
                    )
                    rec.FullVolumeS3Bucket=s3b; rec.FullVolumeS3Key=s3k

            except (ClientError, WaiterError, TimeoutError, RuntimeError, SystemExit) as e:
                rec.Error=str(e)
                log_step(logger,"BACKUP","ERROR",VolumeId=vid,SrcSnapshotId=rec.SrcSnapshotId,DstSnapshotId=rec.DstSnapshotId,Error=str(e),SnapshotName=snapshot_name)
                if isinstance(e, SystemExit):
                    rec.EndTime=utc_iso(); records.append(rec)
                    raise

            rec.EndTime=utc_iso(); records.append(rec)
            log_step(logger,"BACKUP","SUMMARY",VolumeId=vid,SizeGiB=size,VolumeType=vtype,
                     SrcSnapshotId=rec.SrcSnapshotId,DstSnapshotId=rec.DstSnapshotId,
                     FullVolumeS3Bucket=rec.FullVolumeS3Bucket,FullVolumeS3Key=rec.FullVolumeS3Key,
                     Error=rec.Error,TotalSoFar=len(records),ElapsedSec=secs_since(overall_t0))

            status = "ok" if (not rec.Error) else "error"
            fullvol_uri = None
            if rec.FullVolumeS3Bucket and rec.FullVolumeS3Key:
                fullvol_uri = f"s3://{rec.FullVolumeS3Bucket}/{rec.FullVolumeS3Key.lstrip('/')}"
            index_entries_by_volume[vid].append({
                "RunId": run_id,
                "DstSnapshotId": rec.DstSnapshotId,
                "FullVolume": fullvol_uri,
                "EndTime": rec.EndTime,
                "Status": status
            })

        log_step(logger,"BACKUP","END",Total=len(records),
                 Succeeded=sum(1 for r in records if not r.Error), Failed=sum(1 for r in records if r.Error),
                 TotalElapsedSec=secs_since(overall_t0))

        # ===== MANIFEST =====
        confirm_phase(args, logger, question=f"Write MANIFEST to {Path(args.manifest_file).resolve()}?",
                      abort_reason="Cancelled by user at MANIFEST phase.")
        t1=time.time(); manifest_path=Path(args.manifest_file); log_step(logger,"MANIFEST","START",Path=str(manifest_path))
        existing={}
        if manifest_path.exists():
            try: existing=json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception: existing={}
        payload=existing or {"Backups":[]}
        payload.setdefault("RunId", run_id)
        payload["Simulated"] = bool(args.simulate)
        payload["Backups"].extend(asdict(r) for r in records)
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log_step(logger,"MANIFEST","END",Path=str(manifest_path),ElapsedSec=secs_since(t1))

        # ===== S3 uploads =====
        if args.s3_bucket and s3_client:
            man_key=f"{(s3_run_prefix or args.s3_prefix).rstrip('/')}/manifest.json".lstrip("/")
            upload_manifest_to_s3(s3_client, args.s3_bucket, man_key, manifest_path, args.s3_storage_class, logger, simulate=args.simulate)

            if args.log_file:
                log_key=f"{(s3_run_prefix or args.s3_prefix).rstrip('/')}/logs/backup-log.json".lstrip("/")
                upload_log_to_s3_if_present(s3_client, args.s3_bucket, log_key, args.log_file, args.s3_storage_class, logger, simulate=args.simulate)

            for vol_id, entries in index_entries_by_volume.items():
                append_volume_index_entry(s3_client, args.s3_bucket, args.s3_prefix, vol_id, entries[-1], storage_class="STANDARD", simulate=args.simulate)

            write_latest_pointer(s3_client, args.s3_bucket, args.s3_prefix, run_id, storage_class="STANDARD", simulate=args.simulate)

        ok=sum(1 for r in records if not r.Error); ko=len(records)-ok
        print(f"Done. {ok} succeeded, {ko} failed. Manifest: {manifest_path}", file=sys.stderr)

    finally:
        if lock_key and s3_client and args.s3_bucket:
            release_helper_lock(s3_client, args.s3_bucket, lock_key, logger, simulate=args.simulate)

if __name__ == "__main__":
    main()
