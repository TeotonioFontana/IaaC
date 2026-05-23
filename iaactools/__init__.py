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
 This lightweight bridge exposes common time and logging utilities expected by
 the Backup Orchestrator.  It delegates logging operations to the shared
 `iaactools.codebase.utils.logger_utils` module and defines minimal time helpers
 used throughout the orchestration workflow.
===============================================================================
"""

from __future__ import annotations
from datetime import datetime, timezone
import time

# Shared logger utilities
from iaactools.codebase.utils.logger_utils import build_logger, log_step


# -----------------------------------------------------------------------------
# Time & ID helpers
# -----------------------------------------------------------------------------
def utc_iso() -> str:
    """
    Return the current UTC time in ISO-8601 format (Z-suffixed).
    Example: '2025-11-06T23:10:12Z'
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_iso() -> str:
    """
    Generate a run identifier based on current UTC time.
    Example: '20251106_231012'
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return ts


def secs_since(start_time: float) -> float:
    """
    Compute seconds elapsed since `start_time`.
    Used to measure phase durations in orchestrator logs.
    """
    return round(time.time() - start_time, 2)


# -----------------------------------------------------------------------------
# Optional future stubs (placeholders for extended helpers)
# -----------------------------------------------------------------------------
def flatten_tags(tags: dict[str, str]) -> str:
    """Flatten AWS tag dictionary into key=value string for logs."""
    if not tags:
        return ""
    return ", ".join(f"{k}={v}" for k, v in tags.items())


# -----------------------------------------------------------------------------
# Module metadata
# -----------------------------------------------------------------------------
__all__ = [
    "utc_iso",
    "run_id_iso",
    "secs_since",
    "build_logger",
    "log_step",
    "flatten_tags",
]
