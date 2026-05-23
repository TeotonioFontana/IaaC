# -*- coding: utf-8 -*-
"""
===============================================================================
 logger_utils.py — v4.0.0-alpha2
===============================================================================
 Purpose............: Provide unified logging utilities for orchestrator phases.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 This module ensures all audit/backup operations write into a single
 /results/.../audit.log file while simultaneously streaming colorized logs
 to stdout. Supports text, JSON, and dual ("both") modes.

 ANSI color palette is standardized across the Recovery & Backup Suites.
===============================================================================
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime


# -----------------------------------------------------------------------------
# Canonical ANSI palette
# -----------------------------------------------------------------------------
ANSI = {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "GRAY": "\033[90m",
    "RED": "\033[31m",
    "GREEN": "\033[32m",
    "YELLOW": "\033[33m",
    "BLUE": "\033[34m",
    "MAGENTA": "\033[35m",
    "CYAN": "\033[36m",
    "WHITE": "\033[97m",
}


def color_text(text: str, color: str) -> str:
    """Wrap text with ANSI color codes."""
    return f"{ANSI.get(color, '')}{text}{ANSI['RESET']}"


# -----------------------------------------------------------------------------
# Custom Handlers
# -----------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    """Format logs as JSON lines for machine parsing."""
    def format(self, record):
        log_entry = {
            "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "phase": getattr(record, "phase", None),
            "message": record.getMessage(),
        }
        return json.dumps(log_entry, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter with color."""
    COLORS = {
        "DEBUG": "GRAY",
        "INFO": "CYAN",
        "WARNING": "YELLOW",
        "ERROR": "RED",
        "CRITICAL": "MAGENTA",
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname, "WHITE")
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"{timestamp} | {record.levelname:<8s} | {record.getMessage()}"
        return color_text(msg, color)


# -----------------------------------------------------------------------------
# Unified Logger Factory
# -----------------------------------------------------------------------------
def build_logger(name: str, results_dir: Path, run_id: str,
                 mode: str = "both", level: str = "DEBUG") -> logging.Logger:
    """
    Build a logger that writes to both console and file.

    Args:
        name: Logger name (e.g., "RecoveryAudit")
        results_dir: Target directory for audit.log
        run_id: Used in log headers for contextual tracing
        mode: "text", "json", or "both"
        level: Logging level (DEBUG|INFO|WARNING|ERROR)
    """
    log_file = results_dir / "audit.log"
    logger = logging.getLogger(name)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.DEBUG))

    # File handler (always JSON for structured persistence)
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)

    # Console handler(s)
    if mode in ("text", "both"):
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(TextFormatter())
        logger.addHandler(ch)
    if mode == "json":
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(JsonFormatter())
        logger.addHandler(ch)

    logger.propagate = False
    logger.info(f"Logger initialized for run {run_id} → {log_file}")
    return logger


# -----------------------------------------------------------------------------
# Simple test stub
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    test_dir = Path("/tmp/audit_test")
    test_dir.mkdir(exist_ok=True)
    log = build_logger("UnitTest", test_dir, "TEST_RUN", mode="both", level="DEBUG")
    log.info("Sample INFO message")
    log.warning("Sample WARNING message")
    log.error("Sample ERROR message")
    log.debug("Sample DEBUG message")
    print(color_text("Synthetic logger test completed.", "GREEN"))
