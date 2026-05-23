# -*- coding: utf-8 -*-
"""
===============================================================================
 snapshots.py — v1.2.0
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestration
 Purpose............: Snapshot management for AWS EBS backup operations.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Provides functions to:
   • Create snapshots for EBS volumes
   • Wait until all snapshots are completed
   • Copy snapshots across regions
   • Support simulation mode (no writes to AWS)
===============================================================================
"""

from __future__ import annotations
import time
import logging
from botocore.exceptions import ClientError, WaiterError
from iaactools.codebase.utils.logger_utils import ANSI

# -----------------------------------------------------------------------------
# Create snapshot for volume
# -----------------------------------------------------------------------------
def create_snapshot_for_volume(ec2_client, volume, logger: logging.Logger, simulate: bool = False):
    """
    Create (or simulate) a snapshot for the given EBS volume.

    Args:
        ec2_client: Boto3 EC2 client.
        volume (dict): Volume descriptor.
        logger (logging.Logger): Active logger.
        simulate (bool): If True, perform a dry-run without creating snapshots.

    Returns:
        dict: Snapshot metadata or simulated reference.
    """
    vol_id = volume.get("VolumeId")
    desc = f"Automated backup for volume {vol_id}"

    if simulate:
        logger.info(f"Simulating snapshot creation for volume {vol_id}")
        time.sleep(0.1)
        return {"SnapshotId": f"simulated-{vol_id}", "Description": desc}

    try:
        logger.info(f"Creating snapshot for volume {vol_id}")
        response = ec2_client.create_snapshot(VolumeId=vol_id, Description=desc)
        snapshot_id = response.get("SnapshotId")
        logger.debug(f"Snapshot initiated: {snapshot_id}")
        return response
    except ClientError as e:
        logger.error(f"Failed to create snapshot for {vol_id}: {e}")
        raise

# -----------------------------------------------------------------------------
# Wait for all snapshots to complete
# -----------------------------------------------------------------------------
def wait_snapshot_complete(ec2_client, logger: logging.Logger, simulate: bool = False):
    """
    Wait (or simulate wait) until all snapshots in the account are completed.

    Args:
        ec2_client: Boto3 EC2 client.
        logger (logging.Logger): Active logger.
        simulate (bool): If True, simulate waiting instead of polling AWS.
    """
    if simulate:
        logger.info("Waiting for snapshot completion (simulated)...")
        time.sleep(3)
        logger.info("[✔] Phase Snapshots: SUCCESS — All simulated snapshots completed.")
        return

    try:
        logger.info("Waiting for snapshot completion...")
        waiter = ec2_client.get_waiter("snapshot_completed")
        waiter.wait()
        logger.info("[✔] Phase Snapshots: SUCCESS — All snapshots completed.")
    except WaiterError as e:
        logger.error(f"Snapshot waiter failed: {e}")
        raise

# -----------------------------------------------------------------------------
# Copy snapshot to another region (optional)
# -----------------------------------------------------------------------------
def copy_snapshot(ec2_client, snapshot_id: str, target_region: str,
                  logger: logging.Logger, simulate: bool = False):
    """
    Copy a snapshot to another AWS region (optionally simulated).

    Args:
        ec2_client: Boto3 EC2 client.
        snapshot_id (str): Source snapshot ID.
        target_region (str): Destination region for copy.
        logger (logging.Logger): Active logger.
        simulate (bool): If True, only log the operation.

    Returns:
        dict: Copy result or simulated metadata.
    """
    if simulate:
        logger.info(f"Simulating snapshot copy {snapshot_id} → {target_region}")
        return {"SnapshotId": f"simulated-copy-{snapshot_id}", "Region": target_region}

    try:
        logger.info(f"Copying snapshot {snapshot_id} to region {target_region}")
        ec2_target = ec2_client.__class__(region_name=target_region)
        response = ec2_target.copy_snapshot(SourceRegion=ec2_client.meta.region_name,
                                            SourceSnapshotId=snapshot_id,
                                            Description=f"Cross-region copy of {snapshot_id}")
        logger.debug(f"Copy initiated: {response.get('SnapshotId')}")
        return response
    except ClientError as e:
        logger.error(f"Failed to copy snapshot {snapshot_id} to {target_region}: {e}")
        raise

# -----------------------------------------------------------------------------
# Summary log utility (optional)
# -----------------------------------------------------------------------------
def summarize_snapshots(logger: logging.Logger, snapshots: list[dict]):
    """
    Produce a summary report of created or simulated snapshots.

    Args:
        logger (logging.Logger): Active logger.
        snapshots (list): List of snapshot metadata dictionaries.
    """
    if not snapshots:
        logger.warning("No snapshots recorded in this session.")
        return

    logger.info(f"{ANSI['CYAN']}[SUMMARY]{ANSI['RESET']} Snapshot Overview:")
    for snap in snapshots:
        sid = snap.get("SnapshotId", "?")
        desc = snap.get("Description", "")
        logger.info(f"   - {sid:30s} {desc}")
    logger.info(f"{ANSI['GRAY']}{'-'*60}{ANSI['RESET']}")
