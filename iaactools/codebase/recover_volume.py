#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
recover_volume.py
=================

Recover an EBS volume for an EC2 instance from the IaaC backup layout.

New
---
--preview     : show a step-by-step plan without making any API changes
--simulate    : validate steps using EC2 DryRun (no state changes); prints results
--dst-region  : destination AWS region for recovery (default: us-east-1)
                (back-compat: --region still accepted; --dst-region wins if both provided)

Usage
-----
  python recover_volume.py \
    --dst-region us-east-1 \
    --instance i-0123456789abcdef0 \
    --source snapshots \
    --vol-id vol-0abc...

  python recover_volume.py \
    --dst-region us-east-1 \
    --instance i-0123456789abcdef0 \
    --source fullvolumes \
    --vol-id vol-0abc...

  # Planning only:
  python recover_volume.py --dst-region us-east-1 --preview ...

  # Permission/param validation without changes:
  python recover_volume.py --dst-region us-east-1 --simulate ...

What it does
------------
- Looks up s3://<bucket>/<prefix>/index/by-volume/<vol-id>.json
- Picks latest entry with Status=="ok" and requested source:
  * snapshots  : uses entry["DstSnapshotId"]
  * fullvolumes: uses entry["FullVolume"] (s3 URI) and run manifest for SizeGiB
- Creates/attaches volume (normal run only)
  * snapshots  : create from snapshot
  * fullvolumes: create blank gp3 then write image via SSM (dd/gunzip)
- Chooses a free device (/dev/sdf, /dev/sdg, ...)

Constraint (recommended)
------------------------
- By default we recover in us-east-1 (the backup region in your tests).
  If you want to restrict to that region, simply always pass: --dst-region us-east-1

Requirements
------------
- boto3 installed and AWS creds/profile configured
- For fullvolumes: target instance must be SSM-managed and able to read the S3 object.
"""

from __future__ import annotations
import argparse
import json
import sys
import time
from typing import Optional, Tuple, List, Dict
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

# ---- defaults you may edit ----
DEFAULT_BUCKET = "212533511020-tf-iaac"
DEFAULT_PREFIX = "tf-backup/"
DEFAULT_DST_REGION = "us-east-1"  # default destination region (where recoveries happen)


# ---------------- helpers ----------------
def die(msg: str) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(2)

def note(msg: str) -> None:
    print(msg, file=sys.stderr)

def get_boto_session(profile: Optional[str], region: str) -> boto3.Session:
    kw = {"region_name": region}
    if profile:
        kw["profile_name"] = profile
    return boto3.Session(**kw)

def read_s3_json(s3, bucket: str, key: str) -> Optional[dict]:
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = obj["Body"].read().decode("utf-8")
        return json.loads(data)
    except s3.exceptions.NoSuchKey:
        return None
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "NotFound", "404"):
            return None
        raise

def parse_s3_uri(uri: str) -> Tuple[str, str]:
    u = urlparse(uri)
    if u.scheme != "s3" or not u.netloc or not u.path:
        raise ValueError(f"Invalid S3 URI: {uri}")
    return u.netloc, u.path.lstrip("/")

def instance_az(ec2, instance_id: str) -> str:
    r = ec2.describe_instances(InstanceIds=[instance_id])
    for res in r.get("Reservations", []):
        for inst in res.get("Instances", []):
            return inst["Placement"]["AvailabilityZone"]
    die(f"Instance not found: {instance_id}")
    return ""  # not reached

def list_used_devices(ec2, instance_id: str) -> List[str]:
    used = []
    r = ec2.describe_instances(InstanceIds=[instance_id])
    for res in r.get("Reservations", []):
        for inst in res.get("Instances", []):
            for bdm in inst.get("BlockDeviceMappings", []):
                if "DeviceName" in bdm:
                    used.append(bdm["DeviceName"])
    return used

def next_free_device(ec2, instance_id: str, candidates: Optional[List[str]] = None) -> str:
    if not candidates:
        letters = [chr(c) for c in range(ord('f'), ord('p') + 1)]
        candidates = [f"/dev/sd{ch}" for ch in letters]
    used = set(list_used_devices(ec2, instance_id))
    for dev in candidates:
        if dev not in used:
            return dev
    die("No free /dev/sd[f-p] attachment point found on the instance.")

def wait_volume_state(ec2, volume_id: str, target: str, timeout: int = 1200):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = ec2.describe_volumes(VolumeIds=[volume_id])["Volumes"][0]["State"]
        print(f"\r[VOL state] {volume_id} -> {st}", end="", file=sys.stderr)
        if st == target:
            print("", file=sys.stderr)
            return
        time.sleep(5)
    die(f"Timeout waiting volume {volume_id} -> {target}")

def wait_attach_state(ec2, volume_id: str, expected: str, timeout: int = 900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        vol = ec2.describe_volumes(VolumeIds=[volume_id])["Volumes"][0]
        atts = vol.get("Attachments", [])
        cur = "attached" if (atts and atts[0]["State"] == "attached") else "detached"
        print(f"\r[ATTACH] {volume_id} -> {cur}", end="", file=sys.stderr)
        if expected == cur:
            print("", file=sys.stderr)
            return
        time.sleep(5)
    die(f"Timeout waiting attachment {volume_id} -> {expected}")

def pick_latest_ok_entry(index_doc: dict, want_source: str) -> dict:
    entries = index_doc.get("Entries") or []
    for e in entries:  # newest first (our writer prepends)
        if e.get("Status") != "ok":
            continue
        if want_source == "snapshots" and e.get("DstSnapshotId"):
            return e
        if want_source == "fullvolumes" and e.get("FullVolume"):
            return e
    return {}

def load_run_manifest(s3, bucket: str, run_id: str, prefix: str) -> dict:
    man_key = f"{prefix.rstrip('/')}/runs/{run_id}/manifest.json"
    doc = read_s3_json(s3, bucket, man_key)
    if not doc:
        die(f"Run manifest not found: s3://{bucket}/{man_key}")
    return doc

def lookup_size_gib_from_manifest(manifest: dict, vol_id: str) -> int:
    for rec in manifest.get("Backups", []):
        if rec.get("VolumeId") == vol_id:
            try:
                return int(rec.get("SizeGiB", 0))
            except Exception:
                return 0
    return 0

def create_blank_volume(ec2, az: str, size_gib: int, vol_type: str = "gp3", tags: Optional[Dict[str, str]] = None) -> str:
    if size_gib <= 0:
        die("Cannot create blank volume: unknown SizeGiB (0).")
    params = {"AvailabilityZone": az, "Size": size_gib, "VolumeType": vol_type}
    if tags:
        params["TagSpecifications"] = [{
            "ResourceType": "volume",
            "Tags": [{"Key": k, "Value": v} for k, v in tags.items()]
        }]
    r = ec2.create_volume(**params)
    vid = r["VolumeId"]
    wait_volume_state(ec2, vid, "available")
    return vid

def attach_volume(ec2, instance_id: str, volume_id: str, device: str):
    ec2.attach_volume(InstanceId=instance_id, VolumeId=volume_id, Device=device)
    wait_attach_state(ec2, volume_id, "attached")

def ssm_stream_s3_to_device(ssm, instance_id: str, s3_uri: str, device_link: str):
    script = f"""#!/bin/bash
set -euo pipefail
URI="{s3_uri}"
LINK="{device_link}"

echo "[restore] Waiting for $LINK ..."
DEV=""
for i in {{1..120}}; do
  if [ -e "$LINK" ]; then DEV=$(readlink -f "$LINK"); break; fi
  sleep 2
done
[ -n "$DEV" ] || {{ echo "[restore][error] device link not found: $LINK" >&2; exit 2; }}

echo "[restore] Target device: $DEV"
command -v aws >/dev/null 2>&1 || {{ echo "aws CLI missing" >&2; exit 3; }}

if [[ "$URI" == *.gz ]]; then
  echo "[restore] Downloading + gunzip -> $DEV ..."
  aws s3 cp "$URI" - | gunzip -c | dd of="$DEV" bs=4M oflag=direct status=progress
else
  echo "[restore] Downloading raw -> $DEV ..."
  aws s3 cp "$URI" - | dd of="$DEV" bs=4M oflag=direct status=progress
fi

sync
blockdev --rereadpt "$DEV" || true
echo "[restore] Completed."
"""
    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [script]},
        TimeoutSeconds=60*60*6
    )
    cmd_id = resp["Command"]["CommandId"]
    status_prev = ""
    while True:
        inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
        st = inv.get("Status")
        if st != status_prev:
            note(f"[SSM] status={st}")
            status_prev = st
        if st in ("Success", "Failed", "Cancelled", "TimedOut"):
            if st != "Success":
                stderr_tail = (inv.get("StandardErrorContent") or "")[-1200:]
                die(f"SSM restore failed: {st}\n--- STDERR (tail) ---\n{stderr_tail}")
            break
        time.sleep(6)

# --------- preview / simulate helpers ---------
def print_plan_header():
    note("[PREVIEW] Recovery plan:")
    note("----------")

def plan_for_snapshots(ec2, s3, bucket, prefix, instance_id, vol_id):
    az = instance_az(ec2, instance_id)
    used = list_used_devices(ec2, instance_id)
    idx_key = f"{prefix.rstrip('/')}/index/by-volume/{vol_id}.json"
    idx = read_s3_json(s3, bucket, idx_key)
    if not idx:
        die(f"No by-volume index for {vol_id}: s3://{bucket}/{idx_key}")
    entry = pick_latest_ok_entry(idx, "snapshots")
    if not entry:
        die(f"No successful snapshot entry found for {vol_id} in index.")
    dst_snap = entry["DstSnapshotId"]
    device = next_free_device(ec2, instance_id)
    plan = {
        "Source": "snapshots",
        "InstanceId": instance_id,
        "InstanceAZ": az,
        "UsedDevices": used,
        "VolumeId": vol_id,
        "ChosenSnapshot": dst_snap,
        "CreateVolumeParams": {"AvailabilityZone": az, "SnapshotId": dst_snap, "VolumeType": "gp3"},
        "AttachDevice": device
    }
    return plan, entry

def plan_for_fullvolumes(ec2, s3, bucket, prefix, instance_id, vol_id):
    az = instance_az(ec2, instance_id)
    used = list_used_devices(ec2, instance_id)
    idx_key = f"{prefix.rstrip('/')}/index/by-volume/{vol_id}.json"
    idx = read_s3_json(s3, bucket, idx_key)
    if not idx:
        die(f"No by-volume index for {vol_id}: s3://{bucket}/{idx_key}")
    entry = pick_latest_ok_entry(idx, "fullvolumes")
    if not entry:
        die(f"No successful full-volume entry found for {vol_id} in index.")
    s3_uri = entry["FullVolume"]
    run_id = entry["RunId"]
    manifest = load_run_manifest(s3, bucket, run_id, prefix)
    size_gib = lookup_size_gib_from_manifest(manifest, vol_id)
    if size_gib <= 0:
        die(f"Could not determine SizeGiB for {vol_id} from run manifest {run_id}.")
    device = next_free_device(ec2, instance_id)
    vol_link_pattern = "/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_<NEW_VOLUME_ID_NO_DASH>"
    plan = {
        "Source": "fullvolumes",
        "InstanceId": instance_id,
        "InstanceAZ": az,
        "UsedDevices": used,
        "VolumeId": vol_id,
        "RunId": run_id,
        "S3Image": s3_uri,
        "CreateVolumeParams": {"AvailabilityZone": az, "Size": size_gib, "VolumeType": "gp3"},
        "AttachDevice": device,
        "DeviceLinkPattern": vol_link_pattern
    }
    return plan, entry

def ec2_dryrun_create_volume(ec2, params: dict) -> Tuple[bool, str]:
    try:
        ec2.create_volume(DryRun=True, **params)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))
        if code == "DryRunOperation":
            return True, "DryRunOperation (OK)"
        return False, f"{code}: {msg}"
    return True, "OK"

def ensure_ssm_managed(ssm, instance_id: str) -> bool:
    try:
        inv = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
        )
        return bool(inv.get("InstanceInformationList"))
    except ClientError:
        return False

# ---------------- core flows ----------------
def restore_from_snapshot(ec2, s3, bucket: str, prefix: str, instance_id: str, vol_id: str,
                          preview: bool, simulate: bool):
    plan, entry = plan_for_snapshots(ec2, s3, bucket, prefix, instance_id, vol_id)
    if preview:
        print_plan_header()
        note(json.dumps(plan, indent=2))
        note("[PREVIEW] (end)")
        if not simulate:
            return

    if simulate:
        ok, msg = ec2_dryrun_create_volume(ec2, plan["CreateVolumeParams"])
        note(f"[SIMULATE] CreateVolume DryRun -> {msg}")
        note(f"[SIMULATE] Would attach at {plan['AttachDevice']}")
        note("[SIMULATE] (end)")
        return

    # real execution
    params = plan["CreateVolumeParams"].copy()
    r = ec2.create_volume(**params)
    new_vol = r["VolumeId"]
    wait_volume_state(ec2, new_vol, "available")
    device = plan["AttachDevice"]
    note(f"[ATTACH] Attaching {new_vol} to {instance_id} at {device}")
    attach_volume(ec2, instance_id, new_vol, device)
    note(f"[DONE] New volume {new_vol} attached at {device} from snapshot {params['SnapshotId']}")

def restore_from_fullvolume(ec2, s3, ssm, bucket: str, prefix: str, instance_id: str, vol_id: str,
                            preview: bool, simulate: bool):
    plan, entry = plan_for_fullvolumes(ec2, s3, bucket, prefix, instance_id, vol_id)
    if preview:
        print_plan_header()
        note(json.dumps(plan, indent=2))
        managed = ensure_ssm_managed(ssm, instance_id)
        note(f"[PREVIEW] SSM managed: {'yes' if managed else 'no/unknown'}")
        note("[PREVIEW] (end)")
        if not simulate:
            return

    if simulate:
        ok, msg = ec2_dryrun_create_volume(ec2, plan["CreateVolumeParams"])
        note(f"[SIMULATE] CreateVolume DryRun -> {msg}")
        note(f"[SIMULATE] Would attach at {plan['AttachDevice']}")
        note(f"[SIMULATE] Would stream {plan['S3Image']} to device link like {plan['DeviceLinkPattern']}")
        managed = ensure_ssm_managed(ssm, instance_id)
        note(f"[SIMULATE] SSM managed: {'yes' if managed else 'no/unknown'}")
        note("[SIMULATE] (end)")
        return

    # real execution
    params = plan["CreateVolumeParams"].copy()
    new_vol = create_blank_volume(ec2, params["AvailabilityZone"], params["Size"], vol_type=params["VolumeType"],
                                  tags={"RestoreFrom": vol_id, "Source": "fullvol"})
    device = plan["AttachDevice"]
    note(f"[ATTACH] Attaching {new_vol} to {instance_id} at {device}")
    attach_volume(ec2, instance_id, new_vol, device)

    vol_nodash = new_vol.replace("-", "")
    device_link = f"/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_{vol_nodash}"

    s3_uri = plan["S3Image"]
    note(f"[RESTORE] Streaming image -> {device_link} from {s3_uri}")
    if not ensure_ssm_managed(ssm, instance_id):
        note("[WARN] Instance not listed as SSM managed; the SSM step may fail.")
    ssm_stream_s3_to_device(ssm, instance_id, s3_uri, device_link)
    note(f"[DONE] Full-volume image restored to {new_vol} (attached at {device})")

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description="Recover an EBS volume for an EC2 instance from IaaC backups.")
    ap.add_argument("--profile", default=None, help="AWS profile")
    # New preferred flag:
    ap.add_argument("--dst-region", default=DEFAULT_DST_REGION, help="Destination AWS region for recovery (default: us-east-1)")
    # Back-compat flag:
    ap.add_argument("--region", default=None, help="(Deprecated) Region alias; --dst-region wins if both are provided")
    ap.add_argument("--bucket", default=DEFAULT_BUCKET, help="S3 bucket for backups")
    ap.add_argument("--prefix", default=DEFAULT_PREFIX, help="S3 prefix (e.g., tf-backup/)")
    ap.add_argument("--instance", required=True, help="EC2 instance ID to attach the recovered volume")
    ap.add_argument("--source", required=True, choices=["snapshots", "fullvolumes"], help="Recovery source type")
    ap.add_argument("--vol-id", required=True, help="The original EBS VolumeId you want to recover")
    ap.add_argument("--preview", action="store_true", help="Show step-by-step plan without changing anything")
    ap.add_argument("--simulate", action="store_true", help="Perform DryRun checks (no state changes)")
    args = ap.parse_args()

    # Resolve the region to use
    region = args.dst_region or args.region or DEFAULT_DST_REGION

    sess = get_boto_session(args.profile, region)
    ec2 = sess.client("ec2")
    s3 = sess.client("s3")
    ssm = sess.client("ssm")

    # Sanity: instance exists (in region)
    try:
        ec2.describe_instances(InstanceIds=[args.instance])
    except ClientError as e:
        die(f"Could not describe instance {args.instance} in {region}: {e}")

    note(f"[START] recover_volume: region={region} instance={args.instance} source={args.source} vol={args.vol_id}")
    note(f"[INFO] Using bucket={args.bucket} prefix={args.prefix}")

    if args.source == "snapshots":
        restore_from_snapshot(ec2, s3, args.bucket, args.prefix, args.instance, args.vol_id,
                              preview=args.preview, simulate=args.simulate)
    else:
        restore_from_fullvolume(ec2, s3, ssm, args.bucket, args.prefix, args.instance, args.vol_id,
                                preview=args.preview, simulate=args.simulate)

    if args.preview and not args.simulate:
        note("[OK] Preview complete.")
    elif args.simulate:
        note("[OK] Simulation complete.")
    else:
        note("[OK] Recovery completed.")

if __name__ == "__main__":
    main()
