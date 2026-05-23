# -*- coding: utf-8 -*-
"""
===============================================================================
 locks.py — Helper Lock Simulation for IaacTools Backup Orchestrator
===============================================================================
 Version.............: v0.6.0
 Author..............: Teotoniio Fontana — Architect
 Programmed by.......: Duke (GPT-5, OpenAI)
 Project.............: IaaC Tools / Backup Orchestration
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Provides simulated distributed lock management used to coordinate helper
 instance usage. The real implementation would use DynamoDB or S3-based
 locks, but this version simply logs actions for testing and dry runs.
===============================================================================
"""

import time
from iaactools.codebase.utils.logger_utils import log_phase_status


# -----------------------------------------------------------------------------
# Acquire lock
# -----------------------------------------------------------------------------
def acquire_helper_lock(helper_instance_id: str | None, logger) -> bool:
    """
    Simulate acquiring a lock for a helper instance.

    Args:
        helper_instance_id (str | None): EC2 instance ID of the helper.
        logger (Logger): Active logger instance.

    Returns:
        bool: True if the lock was successfully "acquired".
    """
    if not helper_instance_id:
        logger.warning("No helper instance ID provided — skipping lock acquisition.")
        return False

    logger.info(f"Simulating lock acquisition for helper {helper_instance_id}...")
    time.sleep(0.5)
    log_phase_status(logger, "HelperLock", "SUCCESS", f"Lock acquired (simulated) for {helper_instance_id}")
    return True


# -----------------------------------------------------------------------------
# Release lock
# -----------------------------------------------------------------------------
def release_helper_lock(helper_instance_id: str | None, logger) -> None:
    """
    Simulate releasing a helper instance lock.

    Args:
        helper_instance_id (str | None): EC2 instance ID of the helper.
        logger (Logger): Active logger instance.
    """
    if not helper_instance_id:
        logger.warning("No helper instance ID provided — skipping lock release.")
        return

    logger.info(f"Simulating release of helper lock for {helper_instance_id}...")
    time.sleep(0.5)
    log_phase_status(logger, "HelperLock", "SUCCESS", f"Lock released (simulated) for {helper_instance_id}")
