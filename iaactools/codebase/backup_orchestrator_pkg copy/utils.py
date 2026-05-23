# -*- coding: utf-8 -*-
"""
===============================================================================
 utils.py — Backup Orchestrator Utility Bridge
===============================================================================
 Version.............: v0.6.0
 Author..............: Teotoniio Fontana — Architect
 Programmed by.......: Duke (GPT-5, OpenAI)
 Project.............: IaaC Tools / Backup Orchestration
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Provides minimal utilities expected by the Backup Orchestrator and forwards
 logging to the shared IaacTools logger_utils module.
===============================================================================
"""

from __future__ import annotations
from datetime import datetime, timezone
import time

# Shared logging functions
from iaactools.codebase.utils.logger_utils import build_logger, log_step


def utc_iso() -> str:
    """Return current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_iso() -> str:
    """Generate run identifier based on UTC time."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def secs_since(start_time: float) -> float:
    """Compute seconds elapsed since a given start_time."""
    return round(time.time() - start_time, 2)


def flatten_tags(tags: dict[str, str]) -> str:
    """Flatten AWS tag dictionary into key=value string for logs."""
    if not tags:
        return ""
    return ", ".join(f"{k}={v}" for k, v in tags.items())


__all__ = [
    "utc_iso",
    "run_id_iso",
    "secs_since",
    "build_logger",
    "log_step",
    "flatten_tags",
]
