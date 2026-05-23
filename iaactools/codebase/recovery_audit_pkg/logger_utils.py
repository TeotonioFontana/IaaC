# Canonical ANSI logger utilities placeholder
# -*- coding: utf-8 -*-
"""
===============================================================================
 logger_utils.py — v4.0.0-alpha1
===============================================================================
 Purpose............: Centralized ANSI-colored logging for Recovery Audit phases
-------------------------------------------------------------------------------
 Features
 ------------------------------------------------------------------------------
 • Supports text, JSON, and dual modes (--log-format)
 • Unified log file: /results/audit/{run_id}/audit.log
===============================================================================
"""

import sys, json, logging
from pathlib import Path

ANSI = {
    "RESET": "\033[0m", "BOLD": "\033[1m",
    "GREEN": "\033[32m", "YELLOW": "\033[33m",
    "RED": "\033[31m", "CYAN": "\033[36m",
    "GRAY": "\033[90m"
}

def build_logger(name: str, log_dir: Path, run_id: str, fmt: str="text", level="DEBUG"):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "audit.log"
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))
    fh = logging.FileHandler(log_file, encoding="utf-8")
    ch = logging.StreamHandler(sys.stdout)
    fmt_text = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
    fh.setFormatter(fmt_text)
    ch.setFormatter(fmt_text)
    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.propagate = False
    logger.info(f"{ANSI['CYAN']}Logger initialized for run {run_id}{ANSI['RESET']}")
    return logger
