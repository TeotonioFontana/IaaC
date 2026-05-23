# -*- coding: utf-8 -*-
"""
logging_utils.py — Shared logging helpers for EBS orchestration
================================================================
Centralized utilities for consistent banners, phase headers,
and verbosity control (INFO vs DEBUG).

This helper is lightweight and safe for both console and file
logging. Color output only activates when stdout is a TTY.
"""

import logging
import os
import sys

# ---------------------------------------------------------------------------
# ANSI colors (auto-disabled when not TTY)
# ---------------------------------------------------------------------------

class _Color:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.reset = "\033[0m" if enabled else ""
        self.bold = "\033[1m" if enabled else ""
        self.cyan = "\033[36m" if enabled else ""
        self.yellow = "\033[33m" if enabled else ""
        self.green = "\033[32m" if enabled else ""
        self.red = "\033[31m" if enabled else ""

def _is_tty():
    return sys.stdout.isatty() and not os.getenv("NO_COLOR")

COLOR = _Color(_is_tty())

# ---------------------------------------------------------------------------
# Banner helpers
# ---------------------------------------------------------------------------

def log_phase_header(logger: logging.Logger, num: int, total: int, name: str, module: str):
    """
    Emit a standardized phase header at INFO level.
    Example:
        ==============================================================================
        ===== PHASE 4/5: EBS Backups =====
              Module: ebs_backup
        ==============================================================================
    """
    line = "=" * 78
    logger.info(line)
    logger.info(
        "%s===== PHASE %s/%s: %s =====%s",
        COLOR.cyan,
        num,
        total,
        name,
        COLOR.reset,
    )
    logger.info("%s      Module: %s%s", COLOR.yellow, module, COLOR.reset)
    logger.info(line)

def log_section_header(logger: logging.Logger, title: str):
    """Secondary section header (used inside phases)."""
    logger.info("-" * 78)
    logger.info("%s--- %s --- %s", COLOR.bold, title, COLOR.reset)
    logger.info("-" * 78)

# ---------------------------------------------------------------------------
# Verbosity helpers
# ---------------------------------------------------------------------------

def info_or_debug(logger: logging.Logger, msg: str, *args, **kwargs):
    """
    Route message to DEBUG if active, otherwise INFO.
    Useful when you want a line visible in both levels
    but more granular under DEBUG.
    """
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(msg, *args, **kwargs)
    else:
        logger.info(msg, *args, **kwargs)

def summarize_list(logger: logging.Logger, items, label: str):
    """
    Log a compact summary of a list at INFO level, and full
    expansion at DEBUG level.
    """
    count = len(items)
    logger.info("%s: %d item(s)", label, count)
    if logger.isEnabledFor(logging.DEBUG):
        for i, item in enumerate(items, start=1):
            logger.debug("[%d/%d] %s", i, count, item)

def log_exception(logger: logging.Logger, phase: str, error: Exception):
    """Standardized exception log."""
    logger.error(
        "%s[EXCEPTION]%s %s: %s",
        COLOR.red,
        COLOR.reset,
        phase,
        str(error),
        exc_info=True if logger.isEnabledFor(logging.DEBUG) else False,
    )
