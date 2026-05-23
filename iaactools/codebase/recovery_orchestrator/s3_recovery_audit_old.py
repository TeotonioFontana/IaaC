#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
s3_recovery_audit.py — Verify disaster recovery readiness in S3 and EC2
=======================================================================

v1.6.3 — 2025-10-31
Adds --validate-config flag with parsed summary output
------------------------------------------------------
Features:
 - YAML + CLI config with prefixes and policies
 - Run-ID + simulation mode
 - Snapshot verification (EC2)
 - AWS profile validation (must be 'architect')
 - JSON + color-coded PDF reports
 - --test-pdf mode generates synthetic report
 - --validate-config mode checks YAML structure and prints summary
"""

import sys
import json
import yaml
import boto3
import logging
from pathlib import Path
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound
from typing import Dict, Any
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
from iaactools.codebase.ebs_backup_pkg.utils import utc_iso, build_logger

__version__ = "1.6.3"


# ---------------------------------------------------------------------------
# Flowable for completeness bar
# ---------------------------------------------------------------------------
class CompletenessBar(Flowable):
    """Visual completeness indicator (green/red horizontal bar)."""
    def __init__(self, score):
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


# ---------------------------------------------------------------------------
# YAML Loader
# ---------------------------------------------------------------------------
def load_config(path: str) -> Dict[str, Any]:
    """Safely read YAML configuration file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        print(f"[FATAL] Config file not found: {path}", file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        print(f"[FATAL] Failed to load {path}: {e}", file=sys.stderr)
        sys.exit(3)


# ---------------------------------------------------------------------------
# Config Validator
# ---------------------------------------------------------------------------
def verify_config(cfg: Dict[str, Any]) -> None:
    """Verify that YAML config contains all required sections and keys."""
    expected_outline = {
        "audit": {
            "bucket": "S3 bucket name",
            "region": "AWS region",
            "profile": "architect",
            "report_path": "results/recovery_audit.json",
            "run_id": "optional, can be overridden by CLI",
        },
        "prefixes": {
            "base": "hyperdocs/ebs_backups",
            "manifest": "manifest",
            "logs": "logs",
            "artifacts": "artifacts",
            "indexes": "indexes",
            "latest": "latest.json",
        },
        "policy": {
            "stop_on_missing_manifest": True,
            "validate_fullvol_exports": True,
            "validate_snapshots": False,
        },
    }

    missing_sections = [s for s in expected_outline if s not in cfg]
    if missing_sections:
        print(f"[FATAL] Missing config section(s): {', '.join(missing_sections)}", file=sys.stderr)
        print("\nExpected structure (outline):")
        print(json.dumps(expected_outline, indent=2))
        sys.exit(3)

    for section, keys in expected_outline.items():
        missing_keys = [k for k in keys if k not in cfg.get(section, {})]
        if missing_keys:
            print(f"[FATAL] Section '{section}' missing keys: {', '.join(missing_keys)}", file=sys.stderr)
            print("\nExpected structure (outline):")
            print(json.dumps(expected_outline, indent=2))
            sys.exit(3)


def print_config_summary(cfg: Dict[str, Any]):
    """Print compact configuration summary."""
    a = cfg["audit"]
    print("[OK] Config structure is valid.\n")
    print(f"Bucket:   {a.get('bucket', '?')}")
    print(f"Region:   {a.get('region', '?')}")
    print(f"Profile:  {a.get('profile', '?')}")
    print(f"Report:   {a.get('report_path', '?')}")
    print(f"Run ID:   {a.get('run_id', '(not set)')}")
    print("Prefixes:")
    for k, v in cfg.get("prefixes", {}).items():
        print(f"  {k:10s}: {v}")
    print("Policies:")
    for k, v in cfg.get("policy", {}).items():
        print(f"  {k:25s}: {v}")
    print()


# ---------------------------------------------------------------------------
# AWS Profile and Privilege Validation
# ---------------------------------------------------------------------------
def verify_profile_privileges(profile: str, logger):
    """Ensure the AWS CLI profile is 'architect' and has admin-level privileges."""
    if profile != "architect":
        logger.error("[FATAL] Recovery audits must run under profile 'architect'.")
        sys.exit(1)

    try:
        session = boto3.Session(profile_name=profile)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        arn = identity.get("Arn", "")
        logger.info(f"Authenticated as {arn}")
        if not any(word.lower() in arn.lower() for word in ["admin", "architect", "poweruser"]):
            logger.error(f"[FATAL] Insufficient privileges for {arn}.")
            sys.exit(1)
    except (NoCredentialsError, ProfileNotFound):
        logger.error("[FATAL] AWS credentials missing or profile not found.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"[FATAL] Failed to verify AWS identity: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Simulation-safe S3 head_object
# ---------------------------------------------------------------------------
def safe_head_object(s3, simulate, bucket, key) -> bool:
    """Return True if object exists, False otherwise."""
    if simulate:
        print(f"[SIMULATE] Would check s3://{bucket}/{key}")
        return True
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False
    except Exception as e:
        print(f"[WARN] S3 head_object error for {key}: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Snapshot verification
# ---------------------------------------------------------------------------
def verify_snapshots(ec2, manifest, simulate, logger):
    """Cross-verify that snapshots listed in manifest exist in EC2."""
    verified = {}
    if simulate:
        logger.info("[SIMULATE] Skipping EC2 snapshot verification.")
        for rec in manifest.get("Backups", []):
            verified[rec.get("DstSnapshotId") or rec.get("SrcSnapshotId")] = "OK"
        return verified

    all_snaps = {rec.get("DstSnapshotId") or rec.get("SrcSnapshotId") for rec in manifest.get("Backups", []) if rec.get("DstSnapshotId") or rec.get("SrcSnapshotId")}
    if not all_snaps:
        logger.warning("No snapshots found in manifest.")
        return {}

    logger.info("Verifying %d snapshots exist in EC2...", len(all_snaps))
    found = {}
    for sid in all_snaps:
        try:
            resp = ec2.describe_snapshots(SnapshotIds=[sid])
            found[sid] = "OK" if resp.get("Snapshots") else "MISSING"
        except ClientError:
            found[sid] = "MISSING"
    return found


# ---------------------------------------------------------------------------
# PDF Report Generator
# ---------------------------------------------------------------------------
def generate_pdf_report(json_path: Path, result: Dict[str, Any], logger):
    """Generate a compact color-coded PDF summary."""
    try:
        pdf_path = json_path.with_suffix(".pdf")
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, leftMargin=40, rightMargin=40, topMargin=50, bottomMargin=40)
        elements = [
            Paragraph("<b>EBS Disaster Recovery Audit Report</b>", styles["Title"]),
            Spacer(1, 10),
            Paragraph(datetime.utcnow().strftime("Generated: %Y-%m-%d %H:%M UTC"), styles["Normal"]),
            Spacer(1, 14),
            Paragraph("<b>Completeness Score</b>", styles["Heading3"]),
            Spacer(1, 4),
            CompletenessBar(result.get("CompletenessScore", 0)),
            Spacer(1, 16),
        ]
        doc.build(elements)
        logger.info(f"PDF report written to {pdf_path}")
    except Exception as e:
        logger.warning(f"Failed to generate PDF report: {e}")


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
def audit_run(cfg: Dict[str, Any], s3, ec2, logger) -> Dict[str, Any]:
    """Perform full completeness verification for one run."""
    pfx = cfg["prefixes"]
    bucket = cfg["audit"]["bucket"]
    run_id = cfg["audit"]["run_id"]
    simulate = cfg["audit"].get("simulate", False)
    result = {
        "RunId": run_id,
        "Bucket": bucket,
        "Manifest": "MISSING",
        "Logs": "MISSING",
        "Volumes": {},
        "Snapshots": {},
        "CompletenessScore": 0.0,
        "Simulate": simulate,
        "TimestampUTC": utc_iso(),
    }

    manifest_key = f"{pfx['base'].rstrip('/')}/{pfx['manifest'].rstrip('/')}/{run_id}/manifest.json"
    if safe_head_object(s3, simulate, bucket, manifest_key):
        result["Manifest"] = "OK"
        manifest = {"Backups": [{"VolumeId": "vol-simulated", "DstSnapshotId": "snap-simulated"}]} if simulate else json.loads(s3.get_object(Bucket=bucket, Key=manifest_key)["Body"].read().decode("utf-8"))
    else:
        manifest = {"Backups": []}

    for rec in manifest.get("Backups", []):
        vid = rec.get("VolumeId")
        sid = rec.get("DstSnapshotId") or rec.get("SrcSnapshotId")
        result["Volumes"][vid] = "OK" if sid else "MISSING"

    if cfg["policy"].get("validate_snapshots", False):
        result["Snapshots"] = verify_snapshots(ec2, manifest, simulate, logger)

    ok_vols = sum(1 for v in result["Volumes"].values() if v == "OK")
    score = (ok_vols / (len(result["Volumes"]) or 1)) * 100
    result["CompletenessScore"] = round(score, 2)
    return result


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Audit EBS disaster recovery readiness in S3 + EC2.")
    parser.add_argument("--config", required=True, help="Path to YAML config file.")
    parser.add_argument("--run-id", help="Override run_id (optional).")
    parser.add_argument("--report", help="Output JSON path (optional).")
    parser.add_argument("--simulate", action="store_true", help="Dry-run (no AWS access).")
    parser.add_argument("--verify-snapshots", action="store_true", help="Verify snapshots in EC2.")
    parser.add_argument("--test-pdf", action="store_true", help="Generate a test PDF report using YAML report_path.")
    parser.add_argument("--validate-config", action="store_true", help="Validate YAML config structure and exit.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    cfg = load_config(args.config)
    verify_config(cfg)

    if args.run_id:
        cfg["audit"]["run_id"] = args.run_id
    if args.report:
        cfg["audit"]["report_path"] = args.report
    if args.simulate:
        cfg["audit"]["simulate"] = True
    if args.verify_snapshots:
        cfg.setdefault("policy", {})["validate_snapshots"] = True

    # --validate-config mode
    if args.validate_config:
        print_config_summary(cfg)
        sys.exit(0)

    level = getattr(logging, args.log_level.upper(), logging.INFO)
    logger = build_logger("s3-audit", None, False, False, level)

    # --test-pdf mode
    if args.test_pdf:
        fake_result = {
            "RunId": "TEST-RUN-ID",
            "Bucket": "example-bucket",
            "Manifest": "OK",
            "Logs": "OK",
            "Volumes": {"vol-001": "OK", "vol-002": "MISSING"},
            "Snapshots": {"snap-aaa": "OK", "snap-bbb": "MISSING"},
            "CompletenessScore": 85.5,
            "Simulate": True,
            "TimestampUTC": utc_iso(),
        }
        report_path = Path(cfg["audit"]["report_path"])
        report_path.write_text(json.dumps(fake_result, indent=2), encoding="utf-8")
        generate_pdf_report(report_path, fake_result, logger)
        print(f"[TEST-PDF] Generated test report at {report_path}")
        sys.exit(0)

    simulate = cfg["audit"].get("simulate", False)
    region = cfg["audit"]["region"]
    profile = cfg["audit"].get("profile")

    verify_profile_privileges(profile, logger)

    if simulate:
        s3 = ec2 = None
    else:
        session = boto3.Session(region_name=region, profile_name=profile)
        s3, ec2 = session.client("s3"), session.client("ec2")

    logger.info(f"Starting recovery audit for run {cfg['audit']['run_id']} (simulate={simulate})")
    result = audit_run(cfg, s3, ec2, logger)

    if cfg["audit"].get("report_path"):
        report_path = Path(cfg["audit"]["report_path"])
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        generate_pdf_report(report_path, result, logger)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        exc_type, _, tb = sys.exc_info()
        lineno = tb.tb_lineno if tb else "(unknown)"
        print(f"[FATAL] Unexpected error: {e} (line {lineno})", file=sys.stderr)
        sys.exit(1)
