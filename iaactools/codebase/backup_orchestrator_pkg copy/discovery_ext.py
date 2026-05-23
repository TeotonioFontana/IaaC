# -*- coding: utf-8 -*-
"""
===============================================================================
 discovery_ext.py — v0.8.1-alpha
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestration
 Purpose............: Unified entrypoint for AWS environment discovery
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 High-level wrapper combining:
   • discovery_core.py  → phases 0.1 to 0.5
   • discovery_multi.py → multi-region orchestration
 Provides:
   - discover_environment() for single-region scans
   - discover_environment_multi() for multi-region sweeps
===============================================================================
"""

from datetime import datetime
from .discovery_core import (
    discover_account_identity,
    discover_cloudformation,
    discover_networking,
    discover_compute,
    discover_storage,
)
from .discovery_multi import discover_environment_multi


# -----------------------------------------------------------------------------
# Single-region discovery wrapper
# -----------------------------------------------------------------------------
def discover_environment(cfg, logger):
    """Perform all Phase 0 discovery steps for a single region."""
    start = datetime.utcnow()
    manifest = {}

    logger.info("=== Phase 0: AWS Account & Infrastructure Discovery ===")

    manifest["account_identity"], _ = discover_account_identity(cfg, logger)
    manifest["cloudformation"], _ = discover_cloudformation(cfg, logger)
    manifest["networking"], _ = discover_networking(cfg, logger)
    manifest["compute"], _ = discover_compute(cfg, logger)
    manifest["storage"], _ = discover_storage(cfg, logger)

    elapsed = (datetime.utcnow() - start).total_seconds()
    logger.info(f"=== Phase 0 Completed — Total Elapsed={elapsed:.2f}s ===")

    return manifest, {"elapsed_sec": round(elapsed, 2)}


# -----------------------------------------------------------------------------
# Public interface exports
# -----------------------------------------------------------------------------
__all__ = [
    "discover_environment",
    "discover_environment_multi",
    "discover_account_identity",
    "discover_cloudformation",
    "discover_networking",
    "discover_compute",
    "discover_storage",
]
