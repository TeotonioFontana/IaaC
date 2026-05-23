# -*- coding: utf-8 -*-
"""
===============================================================================
 fullvol.py — Full-Volume Backup Simulation for IaacTools
===============================================================================
 Version.............: v0.6.0
 Author..............: Teotoniio Fontana — Architect
 Programmed by.......: Duke (GPT-5, OpenAI)
 Project.............: IaaC Tools / Backup Orchestration
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Provides simulated implementations of full-volume backup operations using a
 helper EC2 instance. Real versions would perform EBS attach, block copy, and
 S3 upload, but these are placeholders for non-destructive testing.
===============================================================================
"""

import time
from iaactools.codebase.utils.logger_utils import log_phase_status


# -----------------------------------------------------------------------------
# Helper preclear
# -----------------------------------------------------------------------------
def preclear_helper_instance(helper_instance_id: str | None, logger) -> None:
    """
    Simulate preparing a helper instance for full-volume backup.

    Args:
        helper_instance_id (str | None): The EC2 instance ID of the helper.
        logger (Logger): Active logger.
    """
    if not helper_instance_id:
        logger.warning("No helper instance ID provided — skipping helper preparation.")
        return

    logger.info(f"Simulating helper instance preclear for {helper_instance_id}...")
    time.sleep(1)
    log_phase_status(logger, "HelperInstance", "SUCCESS", f"Preclear simulated for {helper_instance_id}")


# -----------------------------------------------------------------------------
# Full-volume backup
# -----------------------------------------------------------------------------
def perform_full_volume_backup(helper_instance_id: str | None, volumes: list[dict], logger) -> None:
    """
    Simulate performing a full-volume backup.

    Args:
        helper_instance_id (str | None): The EC2 instance used for the operation.
        volumes (list): List of discovered EBS volumes.
        logger (Logger): Active logger.
    """
    if not volumes:
        logger.warning("No volumes provided for full-volume backup.")
        return

    logger.info("Simulating full-volume backup process...")
    for v in volumes:
        vid = v.get("VolumeId", "unknown")
        logger.info(f"Simulated copying data from volume {vid} to S3 via helper {helper_instance_id}")
        time.sleep(0.5)
    log_phase_status(logger, "FullVolume", "SUCCESS", f"Simulated backup for {len(volumes)} volumes.")
