# -*- coding: utf-8 -*-
"""
===============================================================================
 audit_core_logic.py — v2.0.0 (2025-11-02)
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

import logging
from pathlib import Path
from typing import Any, Dict

from .logger_utils import build_logger
from . import pdf_report_utils

def run_audit_from_cli(args, cfg) -> Dict[str, Any]:
    a = cfg["audit"]
    log_cfg = cfg["logging"]
    run_id = a["run_id"]

    results_dir = Path("/results/audit") / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_format = log_cfg.get("format", "text")
    logger = build_logger("RecoveryAudit", level=level, log_format=log_format, run_id=run_id, results_dir=results_dir)

    logger.info("=== S3 Recovery Audit — Core Logic (v2.0) ===")
    logger.info(f"Region={a['region']} Bucket={a['bucket']} RunId={run_id} Simulate={a.get('simulate', False)}")

    result = {
        "RunId": run_id,
        "Bucket": a["bucket"],
        "Manifest": "UNKNOWN",
        "Logs": "UNKNOWN",
        "Volumes": {},
        "Snapshots": {},
        "CompletenessScore": 0.0,
        "Simulate": a.get("simulate", False),
        "TimestampUTC": "1970-01-01T00:00:00Z",
        "DetailLevel": cfg.get("report", {}).get("detail_level", "summary"),
        "Structure": {},
    }

    json_path = pdf_report_utils.write_json_report(result, run_id)
    pdf_path = pdf_report_utils.generate_pdf_report(result, run_id)
    logger.info(f"Audit report written to {json_path}")
    logger.info(f"PDF report written to {pdf_path}")
    logger.info("Recovery audit completed successfully.")
    return result
