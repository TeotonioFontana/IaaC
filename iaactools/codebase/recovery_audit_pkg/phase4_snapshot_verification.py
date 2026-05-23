# -*- coding: utf-8 -*-
"""
===============================================================================
 phase4_snapshot_verification.py — v4.0.0-alpha1
===============================================================================
 Purpose............: Check EC2 snapshots exist and are available.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Uses EC2 describe_snapshots to confirm every snapshot ID in the manifest
 actually exists and is in 'completed' state.
===============================================================================
"""
import boto3, logging
from botocore.exceptions import ClientError

def run(cfg, manifest_data: dict, logger: logging.Logger) -> dict:
    """Phase 4 — Verify EC2 snapshots referenced by manifest."""
    ec2 = boto3.client("ec2", region_name=cfg["audit"]["region"])
    snaps = {}
    for rec in manifest_data.get("Backups", []):
        sid = rec.get("DstSnapshotId") or rec.get("SrcSnapshotId")
        if not sid:
            continue
        try:
            resp = ec2.describe_snapshots(SnapshotIds=[sid])
            state = resp["Snapshots"][0]["State"] if resp["Snapshots"] else "unknown"
            snaps[sid] = state.upper()
            logger.debug(f"Snapshot {sid} state: {state}")
        except ClientError:
            snaps[sid] = "MISSING"
            logger.warning(f"Snapshot {sid} not found.")
    return snaps

if __name__ == "__main__":
    print("Synthetic test: Phase4 snapshot verification stub.")
