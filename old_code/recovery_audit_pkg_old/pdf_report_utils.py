# -*- coding: utf-8 -*-
"""
===============================================================================
 pdf_report_utils.py — v2.0.0 (2025-11-02)
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

from pathlib import Path
from typing import Any, Dict

DEFAULT_RESULTS_ROOT = Path("/results/audit")

def _ensure_run_dir(run_id: str) -> Path:
    run_dir = DEFAULT_RESULTS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    return run_dir

def write_json_report(results: Dict[str, Any], run_id: str) -> Path:
    import json
    out_dir = _ensure_run_dir(run_id)
    json_path = out_dir / "audit_result.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    return json_path

def generate_pdf_report(results: Dict[str, Any], run_id: str) -> Path:
    out_dir = _ensure_run_dir(run_id)
    pdf_path = out_dir / "audit_report.pdf"
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("<b>EBS/S3 Recovery Audit Report</b>", styles["Heading1"]),
            Paragraph(f"Run ID: {run_id}", styles["Normal"]),
            Spacer(1, 12),
            Paragraph(f"Completeness: {results.get('CompletenessScore', 0)}%", styles["Normal"]),
        ]
        doc.build(story)
    except Exception as e:
        with pdf_path.open("w", encoding="utf-8") as f:
            f.write(f"EBS/S3 Recovery Audit Report (placeholder)\nRun ID: {run_id}\nError: {e}\n")
    return pdf_path
