# iaactools/ebs_backup_pkg/fullvol.py
from __future__ import annotations

import time
from typing import Optional, Tuple, List, Dict

from botocore.exceptions import ClientError, WaiterError

from .utils import log_step

def preclear_helper_instance(ec2_dst, helper_instance_id: str, logger, simulate: bool = False) -> None:
    """
    Ensure the helper instance has **no non-root EBS** volumes attached.
    Detaches any non-root EBS attachments (force), waiting until they're available.
    Logs what it does; does nothing in simulate mode.
    """
    try:
        resp = ec2_dst.describe_instances(InstanceIds=[helper_instance_id])
    except ClientError as e:
        raise RuntimeError(f"Failed to describe helper instance {helper_instance_id}: {e}") from e

    resv = resp.get("Reservations", [])
    if not resv or not resv[0].get("Instances"):
        raise RuntimeError(f"Helper instance not found: {helper_instance_id}")

    inst = resv[0]["Instances"][0]
    root_device = inst.get("RootDeviceName")
    bdm: List[Dict] = inst.get("BlockDeviceMappings", []) or []

    # If AWS didn't return RootDeviceName, guess it from mappings by most common pattern
    if not root_device:
        for m in bdm:
            if m.get("Ebs", {}).get("DeleteOnTermination") and m.get("DeviceName", "").startswith(("/dev/sd", "/dev/xvd", "/dev/nvme")):
                root_device = m.get("DeviceName")
                break

    non_root: List[Dict[str, str]] = []
    for m in bdm:
        ebs = m.get("Ebs")
        if not ebs:
            continue
        dev = m.get("DeviceName")
        if dev and dev == root_device:
            continue
        non_root.append({"VolumeId": ebs.get("VolumeId"), "DeviceName": dev or "(unknown)"})

    if not non_root:
        log_step(logger, "HELPER", "CLEAN", Message="No non-root attachments on helper.")
        return

    for att in non_root:
        vol_id = att["VolumeId"]
        dev = att["DeviceName"]
        log_step(logger, "HELPER", "DETACH", VolumeId=vol_id, Device=dev)
        if simulate:
            continue
        try:
            ec2_dst.detach_volume(InstanceId=helper_instance_id, VolumeId=vol_id, Device=dev, Force=True)
        except ClientError as e:
            log_step(logger, "HELPER", "DETACH_WARN", VolumeId=vol_id, Device=dev, Error=str(e))
            continue
        try:
            ec2_dst.get_waiter("volume_available").wait(
                VolumeIds=[vol_id],
                WaiterConfig={"Delay": 3, "MaxAttempts": 120},
            )
        except (WaiterError, ClientError) as e:
            log_step(logger, "HELPER", "WAIT_WARN", VolumeId=vol_id, Error=str(e))


def _helper_az(ec2_dst, helper_instance_id: str) -> str:
    """Return the Availability Zone of the helper instance."""
    resp = ec2_dst.describe_instances(InstanceIds=[helper_instance_id])
    rsv = resp.get("Reservations", [])
    if not rsv or not rsv[0].get("Instances"):
        raise RuntimeError(f"Helper instance not found: {helper_instance_id}")
    return rsv[0]["Instances"][0]["Placement"]["AvailabilityZone"]


def _wait(ec2_dst, waiter: str, **kwargs) -> None:
    w = ec2_dst.get_waiter(waiter)
    w.wait(**kwargs)


def perform_full_volume_backup(
    *,
    ec2_dst,
    ssm_dst,
    helper_instance_id: str,
    dst_snapshot_id: str,
    base_name: str,
    size_gib: int,
    s3_bucket: Optional[str],
    s3_run_prefix: Optional[str],  # e.g., tf-backup/runs/<runid>
    vol_id: str,
    fmt: str,                      # 'raw.gz' (default) or 'raw'
    delete_temp_volume: bool,
    logger,
    extra_tags: Optional[dict] = None,
    simulate: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Create a temp volume from the destination snapshot, attach to the helper,
    stream a raw image to S3 via SSM (gzip if requested), then detach/cleanup.

    Returns (s3_bucket, s3_key) or (None, None) if no S3 bucket provided.
    """
    if not s3_bucket:
        log_step(logger, "FULLVOL", "SKIP", Reason="No --s3-bucket configured")
        return None, None

    if not s3_run_prefix:
        s3_run_prefix = "tf-backup/runs/unknown"

    # Attachment name (Nitro remaps to /dev/nvme*)
    attach_device = "/dev/sdf"

    # Build safe key
    safe_name = "".join(ch if ch.isalnum() or ch in "-._" else "-" for ch in (base_name or vol_id))
    suffix = ".raw.gz" if fmt.strip().lower() == "raw.gz" else ".raw"
    s3_key = f"{s3_run_prefix.rstrip('/')}/fullvol/{safe_name}-{vol_id}{suffix}"

    if simulate:
        log_step(
            logger, "FULLVOL", "SIMULATE",
            Helper=helper_instance_id, Snapshot=dst_snapshot_id,
            DestKey=f"s3://{s3_bucket}/{s3_key}", Device=attach_device, SizeGiB=size_gib
        )
        return s3_bucket, s3_key

    # 1) Create temp volume from snapshot in helper AZ
    az = _helper_az(ec2_dst, helper_instance_id)
    tag_specs = []
    if extra_tags:
        tag_specs = [{
            "ResourceType": "volume",
            "Tags": [{"Key": k, "Value": str(v)} for k, v in (extra_tags or {}).items()]
        }]

    log_step(logger, "FULLVOL", "CREATE_VOLUME", SnapshotId=dst_snapshot_id, AZ=az, VolumeType="gp3")
    try:
        vol_resp = ec2_dst.create_volume(
            AvailabilityZone=az,
            SnapshotId=dst_snapshot_id,
            VolumeType="gp3",
            TagSpecifications=tag_specs or []
        )
    except ClientError as e:
        raise RuntimeError(f"Failed to create temp volume from snapshot {dst_snapshot_id}: {e}") from e

    temp_vol_id = vol_resp["VolumeId"]
    try:
        _wait(ec2_dst, "volume_available", VolumeIds=[temp_vol_id], WaiterConfig={"Delay": 5, "MaxAttempts": 120})
    except (WaiterError, ClientError) as e:
        raise RuntimeError(f"Temp volume did not become available: {temp_vol_id}: {e}") from e

    # 2) Attach to helper
    log_step(logger, "FULLVOL", "ATTACH", VolumeId=temp_vol_id, InstanceId=helper_instance_id, Device=attach_device)
    try:
        ec2_dst.attach_volume(InstanceId=helper_instance_id, VolumeId=temp_vol_id, Device=attach_device)
        _wait(ec2_dst, "volume_in_use", VolumeIds=[temp_vol_id], WaiterConfig={"Delay": 3, "MaxAttempts": 120})
    except (ClientError, WaiterError) as e:
        try:
            ec2_dst.detach_volume(VolumeId=temp_vol_id, InstanceId=helper_instance_id, Device=attach_device, Force=True)
        except Exception:
            pass
        raise RuntimeError(f"Failed to attach temp volume {temp_vol_id} to {helper_instance_id}: {e}") from e

    # 3) SSM command to stream bytes to S3 (gzip if requested)
    compress_pipeline = "gzip -1 | " if suffix.endswith(".gz") else ""
    s3_uri = f"s3://{s3_bucket}/{s3_key}"
    shell = f"""set -euo pipefail
DEV=""
for CAND in /dev/xvdf /dev/sdf; do
  if [ -e "$CAND" ]; then DEV=$(readlink -f "$CAND" || echo "$CAND"); break; fi
done
if [ -z "$DEV" ]; then
  DEV=$(lsblk -ndo NAME,TYPE | awk '$2=="disk"{{print "/dev/"$1}}' | head -n1)
fi
if [ -z "$DEV" ] || [ ! -b "$DEV" ]; then
  echo "Could not resolve attached device"; exit 2
fi
dd if="$DEV" bs=16M iflag=direct status=progress | {compress_pipeline}aws s3 cp - "{s3_uri}"
"""

    log_step(logger, "FULLVOL", "SSM_SEND", InstanceId=helper_instance_id, S3=s3_uri)
    try:
        send = ssm_dst.send_command(
            InstanceIds=[helper_instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [shell], "executionTimeout": ["86400"]},
            CloudWatchOutputConfig={"CloudWatchLogGroupName": "", "CloudWatchOutputEnabled": False}
        )
        cmd_id = send["Command"]["CommandId"]
    except ClientError as e:
        raise RuntimeError(f"Failed to dispatch SSM command to helper {helper_instance_id}: {e}") from e

    # Poll for completion
    status = "InProgress"
    t0 = time.time()
    while status in ("Pending", "InProgress", "Delayed"):
        time.sleep(10)
        inv = ssm_dst.list_command_invocations(CommandId=cmd_id, InstanceId=helper_instance_id, Details=True)
        if inv.get("CommandInvocations"):
            status = inv["CommandInvocations"][0].get("Status", "InProgress")
            if status in ("Cancelled", "TimedOut", "Failed", "Cancelling"):
                break
        if time.time() - t0 > 3 * 3600:
            status = "TimedOut"
            break

    if status != "Success":
        raise RuntimeError(f"SSM command {cmd_id} ended with status={status}")

    log_step(logger, "FULLVOL", "SSM_DONE", Status=status, S3=s3_uri)

    # 4) Detach & cleanup
    try:
        ec2_dst.detach_volume(VolumeId=temp_vol_id, InstanceId=helper_instance_id, Device=attach_device, Force=True)
        _wait(ec2_dst, "volume_available", VolumeIds=[temp_vol_id], WaiterConfig={"Delay": 3, "MaxAttempts": 120})
    except Exception as e:
        log_step(logger, "FULLVOL", "DETACH_WARN", VolumeId=temp_vol_id, Error=str(e))

    if delete_temp_volume:
        try:
            ec2_dst.delete_volume(VolumeId=temp_vol_id)
            log_step(logger, "FULLVOL", "DELETE_VOLUME", VolumeId=temp_vol_id)
        except ClientError as e:
            log_step(logger, "FULLVOL", "DELETE_WARN", VolumeId=temp_vol_id, Error=str(e))

    return s3_bucket, s3_key
