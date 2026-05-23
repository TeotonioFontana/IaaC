# -*- coding: utf-8 -*-
"""
===============================================================================
 logger_utils.py — v4.0.1-alpha
===============================================================================
 Author.............: Teotonio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Shared Logging Utilities
 Purpose............: Provide consistent, colorized, and unified logging
                      across all orchestrators and phases.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Features:
   • Colorized console output (always on)
   • UTF-8 unified file log (audit.log)
   • Dynamic verbosity control (set_global_log_level)
   • Phase status helper (log_phase_status)
   • Decorative phase-block banners (new in v4.0.1)
   • Canonical ANSI palette for consistent visual identity

 Log file location:
     /results/(audit|backup_audit)/{run_id}/audit.log
===============================================================================
"""

import logging
import sys
from pathlib import Path
from datetime import datetime

# -----------------------------------------------------------------------------
# ANSI color palette (canonical)
# -----------------------------------------------------------------------------
ANSI = {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "GRAY": "\033[90m",
    "RED": "\033[31m",
    "GREEN": "\033[32m",
    "YELLOW": "\033[33m",
    "BLUE": "\033[34m",
    "CYAN": "\033[36m",
    "MAGENTA": "\033[35m",
}

# -----------------------------------------------------------------------------
# ColorFormatter
# -----------------------------------------------------------------------------
class ColorFormatter(logging.Formatter):
    """Custom formatter adding ANSI colors for levels and timestamps."""

    LEVEL_COLORS = {
        logging.DEBUG: ANSI["CYAN"],
        logging.INFO: ANSI["GREEN"],
        logging.WARNING: ANSI["YELLOW"],
        logging.ERROR: ANSI["RED"],
        logging.CRITICAL: ANSI["MAGENTA"],
    }

    def format(self, record: logging.LogRecord) -> str:
        level_color = self.LEVEL_COLORS.get(record.levelno, "")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = f"{ANSI['GRAY']}{ts}{ANSI['RESET']} | {ANSI['BOLD']}{record.name}{ANSI['RESET']}"
        level = f"{level_color}{record.levelname:<8}{ANSI['RESET']}"
        msg = record.getMessage()
        return f"{prefix} | {level} | {msg}"

# -----------------------------------------------------------------------------
# FileFormatter
# -----------------------------------------------------------------------------
class FileFormatter(logging.Formatter):
    """Simple log formatter for persistent log file (no ANSI)."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"{ts} | {record.name} | {record.levelname:<8} | {record.getMessage()}"

# -----------------------------------------------------------------------------
# Logger Builder
# -----------------------------------------------------------------------------
def build_logger(name: str, results_dir: Path, run_id: str, level: int = logging.DEBUG) -> logging.Logger:
    """
    Create a unified logger with colorized console output and persistent file log.

    Args:
        name (str): Logical logger name (e.g., "BackupOrchestrator")
        results_dir (Path): Base directory where audit.log will be written
        run_id (str): Identifier of current run
        level (int): Logging level (default: DEBUG)

    Returns:
        logging.Logger: Configured logger instance
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # avoid duplicate handlers in re-entrant imports

    logger.setLevel(level)
    log_path = results_dir / "audit.log"

    # --- Console handler (colorized)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(ColorFormatter())

    # --- File handler (UTF-8)
    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(FileFormatter())

    # --- Add handlers
    logger.addHandler(ch)
    logger.addHandler(fh)

    logger.debug(f"Logger initialized at {log_path}")
    return logger

# -----------------------------------------------------------------------------
# Dynamic verbosity control
# -----------------------------------------------------------------------------
def set_global_log_level(level_name: str) -> None:
    """
    Dynamically adjust logging level for all active loggers.

    Args:
        level_name (str): One of {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} (case-insensitive)

    Raises:
        ValueError: If level_name is invalid.
    """
    level_name = level_name.upper().strip()
    if level_name not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"Invalid log level '{level_name}'")

    new_level = getattr(logging, level_name)
    root_logger = logging.getLogger()
    root_logger.setLevel(new_level)

    for name, logger in logging.root.manager.loggerDict.items():
        if isinstance(logger, logging.Logger):
            logger.setLevel(new_level)
    print(f"{ANSI['YELLOW']}[LOG] Verbosity changed globally to {level_name}{ANSI['RESET']}")

# -----------------------------------------------------------------------------
# Phase status helper
# -----------------------------------------------------------------------------
def log_phase_status(logger: logging.Logger, phase_name: str, status: str, details: str | None = None) -> None:
    """
    Log a standardized per-phase status line with colored icons.

    Args:
        logger (logging.Logger): The target logger instance.
        phase_name (str): Human-readable name of the phase.
        status (str): One of {"SUCCESS", "FAILED", "WARNING"} (case-insensitive).
        details (str, optional): Additional context message.
    """
    status = status.upper().strip()
    msg = details or ""

    if status == "SUCCESS":
        icon = f"{ANSI['GREEN']}✔{ANSI['RESET']}"
        logger.info(f"[{icon}] Phase {phase_name}: SUCCESS — {msg}")
    elif status == "FAILED":
        icon = f"{ANSI['RED']}✖{ANSI['RESET']}"
        logger.error(f"[{icon}] Phase {phase_name}: FAILED — {msg}")
    elif status == "WARNING":
        icon = f"{ANSI['YELLOW']}⚠{ANSI['RESET']}"
        logger.warning(f"[{icon}] Phase {phase_name}: WARNING — {msg}")
    else:
        icon = f"{ANSI['CYAN']}?{ANSI['RESET']}"
        logger.debug(f"[{icon}] Phase {phase_name}: {status} — {msg}")

# -----------------------------------------------------------------------------
# Decorative phase-block helper (NEW)
# -----------------------------------------------------------------------------
def log_phase_block(logger: logging.Logger, phase: str, message: str, mode: str = "start", **kwargs) -> None:
    """
    Prints decorative headers and footers for phase sections.

    Args:
        logger  : logging.Logger
        phase   : Phase label (e.g., "PHASE1", "PHASE2", "SUMMARY", "COMPLETE")
        message : Text describing the section
        mode    : 'start', 'summary', or 'end'
    """
    line = "═" * 71 if mode == "start" else "─" * 71
    header_color = ANSI["CYAN"] if mode == "start" else ANSI["GRAY"]
    banner = f"{header_color}{line}{ANSI['RESET']}"
    msg_color = ANSI["BLUE"] if mode == "start" else ANSI["GREEN"]

    if mode == "start":
        logger.info(banner)
        logger.info(f"{msg_color}{ANSI['BOLD']} {phase.upper()} — {message.upper()} {ANSI['RESET']}")
        logger.info(f"{ANSI['CYAN']}{'─'*71}{ANSI['RESET']}")
    elif mode == "summary":
        kv = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        logger.info(f"{ANSI['CYAN']}{'─'*71}{ANSI['RESET']}")
        logger.info(f"{ANSI['GREEN']}[✔]{ANSI['RESET']} {message} {kv}")
        logger.info(banner)
    elif mode == "end":
        logger.info(banner)

# -----------------------------------------------------------------------------
# Backward-compatibility bridge
# -----------------------------------------------------------------------------
def log_step(logger: logging.Logger, phase: str, message: str, **kwargs) -> None:
    """
    Legacy orchestration helper used by older IaacTools components.

    Args:
        logger  (logging.Logger): Active logger from build_logger()
        phase   (str): Phase label (e.g., "PHASE1", "CONFIG", "COMPLETE")
        message (str): Main event message.
        **kwargs: Optional key=value metadata appended to the line.

    Behavior:
        • Prints a structured line with UTC timestamp and colored phase tag.
        • Delegates to standard logger.info() for persistence.
        • For PHASE*/SUMMARY/COMPLETE, calls log_phase_block() for visual framing.
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    kv = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""

    upper = phase.upper()
    if upper.startswith("PHASE"):
        log_phase_block(logger, phase, message, mode="start")
    elif upper in ("SUMMARY", "COMPLETE"):
        log_phase_block(logger, phase, message, mode="summary", **kwargs)
    else:
        text = f"[{phase}] {message}"
        if kv:
            text += f" | {kv}"
        logger.info(f"{ANSI['CYAN']}{timestamp} {text}{ANSI['RESET']}")

# -----------------------------------------------------------------------------
# Test entrypoint
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    path = Path.cwd() / "results" / "audit" / "TEST_RUN"
    path.mkdir(parents=True, exist_ok=True)
    logger = build_logger("LoggerUtilsTest", path, "TEST_RUN")
    logger.info("Logger test initialized.")
    log_step(logger, "PHASE1", "Discovery started")
    log_step(logger, "INFO", "Enumerating 47 volumes")
    log_phase_status(logger, "1 (Discovery)", "SUCCESS", "9 instances found.")
    log_step(logger, "SUMMARY", "Phase Discovery: SUCCESS", Duration="2.31s", Volumes=47)
    log_step(logger, "PHASE2", "Snapshot Backup")
    log_step(logger, "INFO", "Simulating 47 snapshots")
    log_phase_status(logger, "2 (Snapshots)", "SUCCESS", "All snapshot tasks simulated.")
    log_step(logger, "SUMMARY", "Phase Snapshots: SUCCESS", Duration="5.0s")
    log_step(logger, "COMPLETE", "Backup orchestration finished", RunID="20251107_191102")
    print(f"\nAudit log written to: {path/'audit.log'}")
