#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AMI Builder (stack-aware)
=========================

Creates AMIs for a set of EC2 instances discovered by tag filters or explicit IDs.
Optionally copies AMIs cross-region with encryption, verifies image & snapshot health,
and tags both image and snapshots for traceability.

Safety modes
------------
--preview  : Discovery + plan only; prints what would run; no mutations.
--simulate : Run read-only phases; log all mutating actions as "Would ...".
             Return synthetic IDs so summaries and JSON look realistic.

Exit codes:
  0  success (some per-instance failures may be logged if --fail-fast not used)
  2  fatal configuration/AWS errors or --fail-fast triggered
"""

from __future__ import annotations
import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError, WaiterError


SCRIPT_NAME = "AMI Builder (stack-aware)"
SCRIPT_VERSION = "1.1.0"
SCRIPT_OBJECTIVE = "Create AMIs from EC2 instances, optionally copy cross-region with KMS, and verify image/snapshot health."


# ------------- Utilities & logging -------------
def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": utc_iso(), "level": record.levelname, "msg": record.getMessage()}
        for k in ("step", "phase", "ctx"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        return json.dumps(payload, ensure_ascii=False)

def build_logger(log_file: Optional[str], json_mode: bool, level: int) -> logging.Logger:
    logger = logging.getLogger("ami-builder")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False
    fmt = JsonFormatter() if json_mode else logging.Formatter("[%(levelname)s] %(message)s")
    handler = logging.FileHandler(log_file, mode="w", encoding="utf-8") if log_file else logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    return logger

def log_step(logger: logging.Logger, phase: str, step: str, **ctx):
    logger.info(f"{phase}:{step}", extra={"phase": phase, "step": step, "ctx": ctx})

def fatal(logger: logging.Logger, phase: str, message: str, **ctx):
    logger.error(f"{phase}:FATAL", extra={"phase": phase, "step": "FATAL", "ctx": {"Error": message, **ctx}})
    print(f"[FATAL] {message}\nContext: {json.dumps(ctx, ensure_ascii=False)}", file=sys.stderr)
    raise SystemExit(2)

def secs_since(t0: float) -> float:
    return round(time.time() - t0, 3)

def sanitize_name(s: str) -> str:
    # AMI name constraints: up to 128 ASCII chars; no control chars; keep common safe set
    s = re.sub(r"[^A-Za-z0-9._/\-()+@ ]+", "-", s).strip()
    return s[:128]

def flatten_tags(tags: Optional[List[Dict[str,str]]]) -> Dict[str,str]:
    return {t["Key"]: t["Value"] for t in (tags or [])}

def synth_ami_id(seed: str) -> str:
    tail = re.sub(r"[^0-9a-f]", "", seed.lower())[-8:] or "deadbeef"
    return f"sim-ami-{tail}"

def synth_copy_id(seed: str) -> str:
    tail = re.sub(r"[^0-9a-f]", "", seed.lower())[-8:] or "deadbeef"
    return f"sim-copy-{tail}"


# ------------- AWS helpers -------------
def iter_instances(ec2, states: Iterable[str], tag_filter: Dict[str,str], explicit_ids: List[str]) -> List[dict]:
    filters = []
    if states:
        filters.append({"Name": "instance-state-name", "Values": list(states)})
    for k, v in (tag_filter or {}).items():
        filters.append({"Name": f"tag:{k}", "Values": [v]})
    reservations = []
    if explicit_ids:
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate(InstanceIds=explicit_ids):
            reservations.extend(page.get("Reservations", []))
    else:
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate(Filters=filters):
            reservations.extend(page.get("Reservations", []))
    instances = []
    for r in reservations:
        instances.extend(r.get("Instances", []))
    return instances

def get_instance_name(i: dict) -> str:
    return next((t["Value"] for t in i.get("Tags", []) if t.get("Key")=="Name"), "")

def wait_image_available(ec2, image_id: str, logger: logging.Logger, timeout: int = 7200, poll: int = 15):
    t0=time.time(); log_step(logger, "WAIT", "IMAGE_START", ImageId=image_id)
    deadline = time.time() + timeout
    last_state = None
    while time.time() < deadline:
        resp = ec2.describe_images(ImageIds=[image_id])
        img = resp["Images"][0]
        state = img.get("State")
        if state == "available":
            log_step(logger, "WAIT", "IMAGE_END", ImageId=image_id, ElapsedSec=secs_since(t0))
            return img
        if state in ("failed", "deregistered"):
            log_step(logger, "WAIT", "IMAGE_ERROR", ImageId=image_id, State=state)
            raise RuntimeError(f"AMI {image_id} entered terminal state: {state}")
        last_state = state
        time.sleep(poll)
    raise TimeoutError(f"Timeout waiting for AMI {image_id} to become available (last={last_state})")

def bdm_snapshot_ids(image_desc: dict) -> List[str]:
    snaps = []
    for bd in image_desc.get("BlockDeviceMappings", []) or []:
        ebs = bd.get("Ebs")
        if ebs and ebs.get("SnapshotId"):
            snaps.append(ebs["SnapshotId"])
    return snaps

def wait_snapshot_completed(ec2, snapshot_id: str, logger: logging.Logger, timeout: int = 7200, poll: int = 10):
    t0=time.time(); log_step(logger, "WAIT", "SNAPSHOT_START", SnapshotId=snapshot_id)
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        s = ec2.describe_snapshots(SnapshotIds=[snapshot_id])["Snapshots"][0]
        st = s.get("State")
        if st == "completed":
            size = s.get("VolumeSize") or 0
            if int(size) <= 0:
                log_step(logger, "WAIT", "SNAPSHOT_ERROR", SnapshotId=snapshot_id, State=st, VolumeSize=size)
                raise RuntimeError(f"Snapshot {snapshot_id} completed with invalid size {size} GiB")
            log_step(logger, "WAIT", "SNAPSHOT_END", SnapshotId=snapshot_id, ElapsedSec=secs_since(t0))
            return
        if st == "error":
            log_step(logger, "WAIT", "SNAPSHOT_ERROR", SnapshotId=snapshot_id, State=st)
            raise RuntimeError(f"Snapshot {snapshot_id} entered error state")
        last = st
        time.sleep(poll)
    raise TimeoutError(f"Timeout waiting for snapshot {snapshot_id} (last={last})")

def tag_resources(ec2, resource_ids: List[str], tags: Dict[str,str], simulate: bool=False, logger: Optional[logging.Logger]=None):
    if not resource_ids: return
    if simulate:
        if logger: log_step(logger, "TAG", "SIMULATE", Resources=resource_ids, Tags=tags)
        return
    ec2.create_tags(Resources=resource_ids, Tags=[{"Key":k,"Value":v} for k,v in tags.items()])


# ------------- Main workflow per-instance -------------
@dataclass
class AmiRecord:
    InstanceId: str
    InstanceName: str
    Region: str
    ImageId: Optional[str] = None
    ImageName: Optional[str] = None
    CopyImageId: Optional[str] = None
    DstRegion: Optional[str] = None
    StartTime: str = ""
    EndTime: str = ""
    Error: Optional[str] = None

def perform_copy(src_region: str, dst_region: str, image_id: str, name: str, description: str,
                 kms_key_id: Optional[str], logger: logging.Logger, simulate: bool=False) -> str:
    if simulate:
        new_id = synth_copy_id(image_id)
        log_step(logger, "COPY", "SIMULATE", SrcRegion=src_region, DstRegion=dst_region,
                 ImageId=image_id, NewImageId=new_id, Name=name, Encrypted=bool(kms_key_id))
        print(f"[SIMULATE] Would copy AMI {image_id} -> {dst_region} as {new_id}", file=sys.stderr)
        return new_id

    dst_sess = boto3.Session(region_name=dst_region)
    ec2_dst = dst_sess.client("ec2")
    params = {
        "SourceImageId": image_id,
        "SourceRegion": src_region,
        "Name": name,
        "Description": description,
    }
    if kms_key_id:
        params["Encrypted"] = True
        params["KmsKeyId"] = kms_key_id
    log_step(logger, "COPY", "IMAGE_START", SrcRegion=src_region, DstRegion=dst_region, ImageId=image_id, Name=name, Encrypted=bool(kms_key_id))
    resp = ec2_dst.copy_image(**params)
    new_id = resp["ImageId"]
    log_step(logger, "COPY", "IMAGE_END", SrcImageId=image_id, DstImageId=new_id)
    # Wait destination AMI available
    t0=time.time()
    while True:
        img = ec2_dst.describe_images(ImageIds=[new_id])["Images"][0]
        st = img.get("State")
        if st == "available":
            log_step(logger, "WAIT", "IMAGE_DST_END", ImageId=new_id, ElapsedSec=secs_since(t0))
            break
        if st in ("failed", "deregistered"):
            raise RuntimeError(f"Destination AMI {new_id} entered terminal state: {st}")
        time.sleep(15)
    return new_id


# ------------- CLI & runner -------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Create AMIs from EC2 instances and optionally copy cross-region.")
    ap.add_argument("--profile", default=None, help="AWS profile.")
    ap.add_argument("--region", required=True, help="Source region where instances live.")
    ap.add_argument("--dst-region", default=None, help="Optional destination region to copy AMIs.")
    ap.add_argument("--kms-key-id", default=None, help="KMS key (alias/ARN) for destination AMI snapshots (when copying).")

    ap.add_argument("--filter-tag", action="append", default=[], help="Filter instances by tag key=value (repeatable).")
    ap.add_argument("--instance-id", action="append", default=[], help="Explicit instance IDs to include (repeatable).")
    ap.add_argument("--states", default="running,stopped", help="Instance states to include (comma-separated).")

    ap.add_argument("--name-template", default="{Name}-{InstanceId}-{ts}", help="AMI name template. Vars: {Name},{InstanceId},{ts}")
    ap.add_argument("--desc-template", default="AMI for {Name} ({InstanceId}) created at {ts}", help="AMI description template.")
    ap.add_argument("--tag", action="append", default=[], help="Tags to apply to AMI & snapshots key=value (repeatable).")

    ap.add_argument("--no-reboot", action="store_true", default=True, help="Create image without instance reboot (default).")
    ap.add_argument("--reboot", dest="no_reboot", action="store_false", help="Allow reboot during AMI creation.")
    ap.add_argument("--fail-fast", action="store_true", help="Abort on first instance failure.")
    ap.add_argument("--yes", action="store_true", help="Non-interactive; don’t prompt.")

    ap.add_argument("--log-json", action="store_true", help="Structured JSON logs.")
    ap.add_argument("--log-file", default=None, help="If set, write logs to file instead of stdout.")

    # NEW safety modes
    ap.add_argument("--preview", action="store_true", help="Discovery + plan only; print what would run, no side effects.")
    ap.add_argument("--simulate", action="store_true", help="Run read-only phases; log all mutating actions as 'Would ...'.")

    return ap.parse_args()

def main() -> None:
    args = parse_args()
    mode = "PREVIEW" if args.preview else "SIMULATE" if args.simulate else "EXECUTE"

    # Startup banner (always)
    print(f"[START] {SCRIPT_NAME} — v{SCRIPT_VERSION}\n"
          f"        Objective: {SCRIPT_OBJECTIVE}\n"
          f"        Started (UTC): {utc_iso()}\n"
          f"        Mode: {mode}",
          file=sys.stderr)

    logger = build_logger(args.log_file, args.log_json, logging.INFO)

    # Sessions/clients (read-only calls are safe in all modes)
    sess_kwargs = {}
    if args.profile: sess_kwargs["profile_name"] = args.profile
    src_sess = boto3.Session(region_name=args.region, **sess_kwargs)
    ec2 = src_sess.client("ec2")

    # Parse filters/tags
    states = [s.strip() for s in args.states.split(",") if s.strip()]
    tag_filter: Dict[str,str] = {}
    for kv in args.filter_tag:
        if "=" not in kv: fatal(logger, "CONFIG", f"--filter-tag expects key=value, got: {kv}")
        k,v = kv.split("=",1); tag_filter[k]=v

    apply_tags: Dict[str,str] = {}
    for kv in args.tag:
        if "=" not in kv: fatal(logger, "CONFIG", f"--tag expects key=value, got: {kv}")
        k,v = kv.split("=",1); apply_tags[k]=v
    apply_tags.setdefault("BackupTool", f"ami_build.py v{SCRIPT_VERSION}")
    apply_tags.setdefault("BackupTime", utc_iso())

    # Discover instances
    t0 = time.time()
    instances = iter_instances(ec2, states, tag_filter, args.instance_id)
    log_step(logger, "DISCOVER", "END", Count=len(instances), States=states, Filters=tag_filter, ElapsedSec=secs_since(t0))
    if not instances:
        print("No instances matched filters.", file=sys.stderr)
        # Emit empty machine-readable payload for callers
        print(json.dumps({"Runs":[]}, ensure_ascii=False, indent=2))
        return

    # If PREVIEW: show plan only and exit
    if args.preview:
        print("[PREVIEW] Plan:", file=sys.stderr)
        for inst in instances:
            iid = inst["InstanceId"]
            name = get_instance_name(inst) or "noname"
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            ami_name = sanitize_name(args.name_template.format(Name=name, InstanceId=iid, ts=ts))
            desc = args.desc_template.format(Name=name, InstanceId=iid, ts=utc_iso())
            print(f"  - Would create AMI for {iid} ({name}) → Name='{ami_name}'  NoReboot={bool(args.no_reboot)}", file=sys.stderr)
            if args.dst_region and args.dst_region != args.region:
                print(f"    Would copy AMI to {args.dst_region}  KMS={'(default or none)' if not args.kms_key_id else args.kms_key_id}", file=sys.stderr)
        # Machine-readable lightweight plan
        print(json.dumps({"Plan":[{"InstanceId": i["InstanceId"], "Name": get_instance_name(i) or ""} for i in instances]}, ensure_ascii=False, indent=2))
        return

    # EXECUTE or SIMULATE
    records: List[AmiRecord] = []
    failures = 0

    for inst in instances:
        iid = inst["InstanceId"]
        name = get_instance_name(inst) or ""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        ami_name = sanitize_name(args.name_template.format(Name=(name or "noname"), InstanceId=iid, ts=ts))
        ami_desc = args.desc_template.format(Name=(name or "noname"), InstanceId=iid, ts=utc_iso())

        rec = AmiRecord(InstanceId=iid, InstanceName=name, Region=args.region, StartTime=utc_iso())
        log_step(logger, "AMI", "CREATE_START", InstanceId=iid, InstanceName=name, Name=ami_name, NoReboot=bool(args.no_reboot))

        try:
            if args.simulate:
                image_id = synth_ami_id(iid)
                rec.ImageId = image_id; rec.ImageName = ami_name
                log_step(logger, "AMI", "SIMULATE_CREATE", InstanceId=iid, ImageId=image_id, Name=ami_name, NoReboot=bool(args.no_reboot), Description=ami_desc, Tags=apply_tags)
                print(f"[SIMULATE] Would create AMI for {iid} as {image_id} (Name='{ami_name}')", file=sys.stderr)
                # No waits, no real snapshots; pretend snapshot validation is fine
            else:
                tag_specs = [{"ResourceType":"image","Tags":[{"Key":k,"Value":v} for k,v in {**apply_tags, "SourceInstanceId":iid, "SourceInstanceName": name or ""}.items()]}]
                resp = ec2.create_image(InstanceId=iid, Name=ami_name, Description=ami_desc, NoReboot=bool(args.no_reboot), TagSpecifications=tag_specs)
                image_id = resp["ImageId"]
                rec.ImageId = image_id; rec.ImageName = ami_name
                log_step(logger, "AMI", "CREATE_END", InstanceId=iid, ImageId=image_id)

                # Wait AMI available (and verify underlying snapshots)
                img_desc = wait_image_available(ec2, image_id, logger, timeout=3*3600, poll=15)

                # snapshots created by AMI: wait & validate
                snap_ids = bdm_snapshot_ids(img_desc)
                for sid in snap_ids:
                    wait_snapshot_completed(ec2, sid, logger)
                # Tag snapshots too (after they exist)
                if snap_ids:
                    tag_resources(ec2, snap_ids, {**apply_tags, "SourceInstanceId": iid, "SourceInstanceName": name or ""}, simulate=False, logger=logger)
                    log_step(logger, "TAG", "SNAPSHOTS", ImageId=image_id, SnapshotCount=len(snap_ids))

            # Optional copy to destination region
            if args.dst_region and args.dst_region != args.region:
                dst_name = ami_name  # keep same
                desc = f"Copy of {rec.ImageId} from {args.region} at {utc_iso()}"
                try:
                    new_id = perform_copy(args.region, args.dst_region, rec.ImageId, dst_name, desc, args.kms_key_id, logger, simulate=args.simulate)
                    rec.CopyImageId = new_id; rec.DstRegion = args.dst_region
                except Exception as ce:
                    rec.Error = str(ce); failures += 1
                    log_step(logger, "COPY", "ERROR", InstanceId=iid, ImageId=rec.ImageId, Error=str(ce))
                    if args.fail_fast:
                        fatal(logger, "COPY", f"Copy failed for AMI {rec.ImageId}: {ce}", InstanceId=iid, ImageId=rec.ImageId)

            log_step(logger, "AMI", "DONE", InstanceId=iid, ImageId=rec.ImageId)
        except (ClientError, WaiterError, TimeoutError, RuntimeError) as e:
            rec.Error = str(e); failures += 1
            log_step(logger, "AMI", "ERROR", InstanceId=iid, InstanceName=name, Error=str(e))
            if args.fail_fast:
                fatal(logger, "AMI", f"Aborting due to failure on {iid}: {e}", InstanceId=iid)

        # In simulate mode, we skip snapshot waits/tagging entirely by design.
        rec.EndTime = utc_iso()
        records.append(rec)

    # Summary
    ok = sum(1 for r in records if not r.Error)
    log_step(logger, "SUMMARY", "END", Total=len(records), Succeeded=ok, Failed=failures)
    print(f"Done. {ok} succeeded, {failures} failed.", file=sys.stderr)
    print(json.dumps({"Runs":[asdict(r) for r in records]}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
