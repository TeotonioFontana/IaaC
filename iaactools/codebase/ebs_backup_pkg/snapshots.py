from __future__ import annotations
from typing import Dict, Optional
from botocore.exceptions import ClientError, WaiterError
import logging
from .utils import log_step, utc_iso, secs_since


def create_snapshot_for_volume(src_client, vol: dict, tags: Dict[str, str], logger, snapshot_name: str, simulate: bool=False) -> str:
    import time, sys
    t0 = time.time()
    vid = vol["VolumeId"]
    size = vol["Size"]
    az = vol["AvailabilityZone"]
    desc = f"IaaC full-backup {vid} at {utc_iso()}"
    tags_with_name = dict(tags)
    tags_with_name["Name"] = snapshot_name
    tag_spec = [{"ResourceType": "snapshot", "Tags": [{"Key": k, "Value": v} for k, v in tags_with_name.items()]}]

    if simulate:
        # DEBUG-only simulate message
        if logger.isEnabledFor(logging.DEBUG):
            log_step(logger, "SNAPSHOT", "SIMULATE_CREATE",
                     Action="CreateSnapshot", VolumeId=vid, SizeGiB=size, AZ=az,
                     Description=desc, Tags=tags_with_name, SnapshotName=snapshot_name)
        return f"sim-snap-{vid[-8:].replace('-', '')}"

    log_step(logger, "SNAPSHOT", "START", Action="CreateSnapshot",
             VolumeId=vid, SizeGiB=size, AZ=az,
             Description=desc, Tags=tags_with_name, SnapshotName=snapshot_name)
    resp = src_client.create_snapshot(VolumeId=vid, Description=desc, TagSpecifications=tag_spec)
    snap_id = resp["SnapshotId"]
    log_step(logger, "SNAPSHOT", "END", SnapshotId=snap_id, VolumeId=vid,
             ElapsedSec=secs_since(t0), SnapshotName=snapshot_name)
    print(f"[SNAPSHOT] Source snapshot created: {snap_id}  Name='{snapshot_name}'  Volume='{vid}'", file=sys.stderr)
    return snap_id


def wait_snapshot_complete(ec2_client, snapshot_id: str, logger, delay: int = 15, max_attempts: int = 400, simulate: bool=False):
    if simulate:
        # Only visible in DEBUG mode
        if logger.isEnabledFor(logging.DEBUG):
            log_step(logger, "WAIT", "SIMULATE_SKIP", ResourceType="Snapshot", SnapshotId=snapshot_id)
        return
    import time
    t0 = time.time()
    log_step(logger, "WAIT", "START", ResourceType="Snapshot", SnapshotId=snapshot_id)
    waiter = ec2_client.get_waiter("snapshot_completed")
    waiter.wait(SnapshotIds=[snapshot_id], WaiterConfig={"Delay": delay, "MaxAttempts": max_attempts})
    log_step(logger, "WAIT", "END", ResourceType="Snapshot", SnapshotId=snapshot_id, ElapsedSec=secs_since(t0))


def copy_snapshot(dst_client, src_region: str, snapshot_id: str, tags: Dict[str, str], logger,
                  snapshot_name: str, encrypt: bool, kms_key_id: Optional[str], simulate: bool=False) -> str:
    import time, sys
    t0 = time.time()
    tags_with_name = dict(tags)
    tags_with_name["Name"] = snapshot_name

    if simulate:
        # DEBUG-only simulate message
        if logger.isEnabledFor(logging.DEBUG):
            log_step(logger, "COPY", "SIMULATE",
                     SourceRegion=src_region, SourceSnapshotId=snapshot_id,
                     SnapshotName=snapshot_name, Encrypted=bool(encrypt),
                     KmsKeyId=kms_key_id or "(default-key)")
        return f"sim-copy-{snapshot_id[-8:].replace('-', '')}"

    tag_spec = [{"ResourceType": "snapshot", "Tags": [{"Key": k, "Value": v} for k, v in tags_with_name.items()]}]
    kwargs = dict(SourceRegion=src_region, SourceSnapshotId=snapshot_id,
                  Description=f"Copy of {snapshot_id} from {src_region}", TagSpecifications=tag_spec)
    if encrypt:
        kwargs["Encrypted"] = True
        if kms_key_id:
            kwargs["KmsKeyId"] = kms_key_id

    log_step(logger, "COPY", "START", SourceRegion=src_region, SourceSnapshotId=snapshot_id,
             SnapshotName=snapshot_name, Encrypted=bool(encrypt), KmsKeyId=kms_key_id or "(default-key)")
    resp = dst_client.copy_snapshot(**kwargs)
    dst_snap = resp["SnapshotId"]
    log_step(logger, "COPY", "END", DstSnapshotId=dst_snap, SourceSnapshotId=snapshot_id,
             ElapsedSec=secs_since(t0), SnapshotName=snapshot_name, Encrypted=bool(encrypt))
    print(f"[COPY] Destination snapshot created: {dst_snap}  Name='{snapshot_name}'  From='{snapshot_id}'  Encrypted={bool(encrypt)}", file=sys.stderr)
    return dst_snap
