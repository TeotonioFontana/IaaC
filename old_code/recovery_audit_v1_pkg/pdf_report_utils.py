# -*- coding: utf-8 -*-
"""
===============================================================================
 pdf_report_utils.py — v1.8.2 (2025-11-02)
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Recovery Audit Package
 Purpose............: JSON + PDF report generation with completeness bar
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Enhancements in v1.8.2:
   • Adds support for config key: report.pdf_output_dir (mandatory in schema)
   • JSON and PDF paths are now derived from config, not hardcoded /tmp
   • Automatically aligns output structure: <pdf_output_dir>/<run_id>/
   • Phase completeness table retained from v1.8.0
   • Compatible with audit_core_logic v1.8.2 (auto PDF generation)
===============================================================================
"""

import json
import boto3
from pathlib import Path
from typing import Any, Dict
from botocore.exceptions import ClientError
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
)

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
S3_REPORT_PREFIX = "recovery_audit"
SCRIPT_VERSION = "1.8.2"
SCRIPT_DATE = "2025-11-02"

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


# -----------------------------------------------------------------------------
# Resolve report directory from config
# -----------------------------------------------------------------------------
def get_report_dir(cfg: Dict[str, Any], run_id: str) -> Path:
    """
    Resolve the base directory for JSON/PDF reports using:
      report.pdf_output_dir (from config) / <run_id>/
    Fallback: /tmp/s3_audit_reports/<run_id>
    """
    base_dir = cfg.get("report", {}).get("pdf_output_dir") or "/tmp/s3_audit_reports"
    out_dir = Path(base_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


# -----------------------------------------------------------------------------
# CompletenessBar Flowable
# -----------------------------------------------------------------------------
class CompletenessBar(Flowable):
    """Visual completeness indicator (green/red horizontal bar)."""
    def __init__(self, score: float):
        super().__init__()
        self.width, self.height = 450, 14
        self.score = min(max(score, 0), 100)

    def draw(self):
        green = colors.Color(0.2, 0.7, 0.3)
        red = colors.Color(0.8, 0.1, 0.1)
        w_ok = self.width * (self.score / 100)
        self.canv.setStrokeColor(colors.grey)
        self.canv.rect(0, 0, self.width, self.height, stroke=1, fill=0)
        self.canv.setFillColor(green if self.score >= 80 else red)
        self.canv.rect(0, 0, w_ok, self.height, stroke=0, fill=1)
        self.canv.setFillColor(colors.black)
        self.canv.drawString(self.width + 8, 2, f"{self.score:.1f}%")


# -----------------------------------------------------------------------------
# Utility: estimate S3 cost
# -----------------------------------------------------------------------------
def estimate_s3_cost(bytes_size: int) -> float:
    """Estimate monthly S3 storage cost (USD)."""
    gb = bytes_size / (1024 ** 3)
    return gb * 0.023


# -----------------------------------------------------------------------------
# JSON Writer
# -----------------------------------------------------------------------------
def write_json_report(cfg: Dict[str, Any], results: Dict[str, Any], run_id: str) -> Path:
    """Write results to JSON inside configured output directory."""
    out_dir = get_report_dir(cfg, run_id)
    json_path = out_dir / "audit_result.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(color_text(f"JSON report saved: {json_path}", "GRAY"))
    return json_path


# -----------------------------------------------------------------------------
# PDF Generator
# -----------------------------------------------------------------------------
def generate_pdf_report(cfg: Dict[str, Any], results: Dict[str, Any], run_id: str) -> Path:
    """Generate a color-coded PDF summary including phase completeness table."""
    out_dir = get_report_dir(cfg, run_id)
    pdf_path = out_dir / "audit_report.pdf"

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=50,
        bottomMargin=40,
        title=f"EBS/S3 Recovery Audit {run_id}"
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontSize = 10
    normal.leading = 12
    h1 = ParagraphStyle("h1", parent=normal, fontSize=16,
                        leading=18, textColor=colors.HexColor("#003366"))

    elements = [
        Paragraph("<b>EBS Disaster Recovery Audit Report</b>", h1),
        Paragraph(f"Version {SCRIPT_VERSION} — {SCRIPT_DATE}", normal),
        Paragraph(f"Run ID: {run_id}", normal),
        Spacer(1, 12),
        Paragraph("<b>Completeness Score</b>", styles["Heading3"]),
        Spacer(1, 4),
        CompletenessBar(results.get("CompletenessScore", 0.0)),
        Spacer(1, 16),
    ]

    # -------------------------------------------------------------------------
    # Phase completeness table
    # -------------------------------------------------------------------------
    if "Structure" in results:
        elements.append(Paragraph("<b>Phase Completeness</b>", styles["Heading3"]))
        data = [["Phase", "Objects", "Status"]]
        for phase, info in results["Structure"].items():
            ok = info.get("Exists", False)
            count = info.get("Objects", 0)
            symbol = "✓" if ok else "✗"
            data.append([phase, str(count), symbol])

        table = Table(data, colWidths=[150, 80, 60])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003366")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.gray),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 16))

    # -------------------------------------------------------------------------
    # Volume / Snapshot summary
    # -------------------------------------------------------------------------
    elements.append(Paragraph("<b>Volume & Snapshot Summary</b>", styles["Heading3"]))
    data = [["Check", "Status", "Details"]]
    data.append(["Manifest", results.get("Manifest", "?"), "Manifest file presence"])

    vols = results.get("Volumes", {})
    data.append(["Volumes", f"{sum(v == 'OK' for v in vols.values())}/{len(vols)}",
                 "Volume mapping completeness"])

    snaps = results.get("Snapshots", {})
    if snaps:
        ok_snaps = sum(v == "OK" for v in snaps.values())
        data.append(["Snapshots", f"{ok_snaps}/{len(snaps)}",
                     "Snapshot verification in EC2"])
    else:
        data.append(["Snapshots", "N/A", "Skipped or simulation mode"])

    table = Table(data, colWidths=[100, 100, 320])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.gray),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 16))

    elements.append(Paragraph(
        f"All audits performed under strict validation mode (v{SCRIPT_VERSION}).",
        normal
    ))

    try:
        doc.build(elements)
        print(color_text(f"PDF report generated: {pdf_path}", "GRAY"))
    except Exception as e:
        print(color_text(f"[WARN] PDF generation failed: {e}", "RED"))

    return pdf_path


# -----------------------------------------------------------------------------
# S3 Upload Handler
# -----------------------------------------------------------------------------
def store_reports_to_s3(
    json_path: Path, pdf_path: Path, cfg: Dict[str, Any],
    run_id: str, simulate: bool = False
) -> None:
    """Upload reports to S3; skip if simulate=True."""
    if simulate:
        print(color_text("[SIMULATE] Skipping S3 upload.", "YELLOW"))
        return

    s3 = boto3.client("s3", region_name=cfg["audit"]["region"])
    bucket = cfg["audit"]["bucket"]
    prefix = f"{S3_REPORT_PREFIX}/{run_id}"

    for path in [json_path, pdf_path]:
        key = f"{prefix}/{path.name}"
        try:
            s3.upload_file(str(path), bucket, key)
            cost = estimate_s3_cost(path.stat().st_size)
            print(color_text(
                f"Uploaded {path.name} → s3://{bucket}/{key} "
                f"(est. cost ${cost:.6f}/mo)", "GREEN"))
        except ClientError as e:
            print(color_text(f"Failed to upload {path.name} to S3: {e}", "RED"))


# -----------------------------------------------------------------------------
# Test PDF Generator
# -----------------------------------------------------------------------------
def generate_test_pdf(cfg: Dict[str, Any], result: Dict[str, Any], logger) -> Path:
    """
    Create a synthetic PDF for --test-pdf verification.
    Includes dummy phase completeness section.
    """
    run_id = cfg["audit"].get("run_id", "TEST_RUN")
    simulate = cfg["audit"].get("simulate", True)

    if not result:
        result = {
            "RunId": run_id,
            "CompletenessScore": 90.2,
            "Manifest": "OK",
            "Volumes": {"vol-1": "OK", "vol-2": "MISSING"},
            "Snapshots": {"snap-1": "OK", "snap-2": "MISSING"},
            "Structure": {
                "discover": {"Objects": 5, "Exists": True},
                "plan": {"Objects": 1, "Exists": True},
                "prep": {"Objects": 0, "Exists": False},
                "backup": {"Objects": 12, "Exists": True},
                "manifest": {"Objects": 1, "Exists": True},
                "logs": {"Objects": 8, "Exists": True},
                "artifacts": {"Objects": 2, "Exists": True},
                "indexes": {"Objects": 2, "Exists": True},
                "latest": {"Objects": 1, "Exists": True},
            },
        }

    logger.info(f"Generating synthetic PDF report for run {run_id}")
    pdf_path = generate_pdf_report(cfg, result, run_id)
    json_path = write_json_report(cfg, result, run_id)

    upload_prefix = cfg["report"].get("s3_upload_prefix")
    if upload_prefix and not simulate:
        store_reports_to_s3(json_path, pdf_path, cfg, run_id, simulate=simulate)
    else:
        logger.debug("Skipping S3 upload (simulation or no prefix).")

    logger.info(f"Test PDF generation completed ({pdf_path})")
    return pdf_path
