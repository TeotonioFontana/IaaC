# -*- coding: utf-8 -*-
"""
===============================================================================
 logger_utils.py — v2.0.0 (2025-11-02)
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Recovery Audit Package
 Purpose............: Core subsystem of the IaaC Recovery Suite (Audit + Recovery)
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 This module is part of the v2.0 refactor: modular, testable, SaaS‑ready.
===============================================================================
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

ANSI = {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "GREEN": "\033[32m",
    "YELLOW": "\033[33m",
    "RED": "\033[31m",
    "GRAY": "\033[90m",
}

def color_text(text: str, color: str) -> str:
    return f"{ANSI.get(color, '')}{text}{ANSI['RESET']}"

def _json_formatter(record: logging.LogRecord) -> str:
    payload = {
        "time": logging.Formatter("%Y-%m-%dT%H:%M:%S").formatTime(record),
        "level": record.levelname,
        "logger": record.name,
        "msg": record.getMessage(),
    }
    return json.dumps(payload, ensure_ascii=False)

class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _json_formatter(record)

def build_logger(name: str,
                 level: int = logging.INFO,
                 log_format: str = "text",
                 run_id: Optional[str] = None,
                 results_dir: Optional[Path] = None) -> logging.Logger:
    # Build a logger with modes: text | json | both.
    # - text: colorized console
    # - json: JSON lines to console
    # - both: colorized console + JSONL file under results_dir/logs/audit.jsonl
    logger = logging.getLogger(name)
    if logger.handlers:
        logger.setLevel(level)
        return logger

    logger.setLevel(level)

    ch = logging.StreamHandler(sys.stdout)
    if log_format in ("text", "both"):
        ch.setFormatter(logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s",
                                          "%Y-%m-%d %H:%M:%S"))
    else:
        ch.setFormatter(JsonLineFormatter())
    logger.addHandler(ch)

    if log_format == "both" and results_dir:
        logs_dir = Path(results_dir) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(logs_dir / "audit.jsonl"), encoding="utf-8")
        fh.setFormatter(JsonLineFormatter())
        logger.addHandler(fh)

    return logger
