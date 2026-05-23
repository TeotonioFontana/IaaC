# -*- coding: utf-8 -*-
"""
===============================================================================
 audit_core_logic.py — v1.8.0 (2025-11-02)
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Recovery Audit Package
 Purpose............: Core logic for S3 + EC2 validation, IAM checks, simulation
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 v1.8.0 adds:
   • S3 structural inspection via build_structure_overview()
   • Adds "Structure" section in results for PDF phase completeness table
   • Enforces region presence and uses it for all boto3 sessions
   • Fully aligned with pdf_report_utils v1.8.0
===============================================================================
"""

import sys
import json
import boto3
import logging
from pathlib import Path
from typing import Any, Dict
from datetime import datetime
from botocore.exceptions import ClientError

# Local import
from . import pdf_report_utils  # used for --test-pdf


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def utc_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def build_logger(name: str, level=logging.INFO, fmt: str = "text") -> logging.Logger:
    """Structured logger honoring config format."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(logging.Formatter(
            '{"time":"%(asctime)s","module":"%(name)s","level":"%(levelname)s","msg":"%(message)s"}',
            "%Y-%m-%dT%H:%M:%S",
        ))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        ))
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger


# -----------------------------------------------------------------------------
# IAM / Profile Validation
# -----------------------------------------------------------------------------
def verify_profile_privileges(profile: str, logger: logging.Logger) -> None:
    """
    Ensure audit runs under a privileged IAM profile (e.g., architect/admin).
    """
    import boto3
    from botocore.exceptions import ProfileNotFound, NoCredentialsError, SSOError, ClientError

    logger.info(f"Verifying IAM identity for profile '{profile}'")

    try:
        session = boto3.Session(profile_name=profile)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        arn = identity.get("Arn", "")
        account = identity.get("Account", "?")
        logger.info(f"Authenticated as {arn} (Account {account})")

        # privilege pattern check (architect/admin/poweruser)
        if not any(word in arn.lower() for word in ["architect", "admin", "poweruser"]):
            logger.warning(f"Profile '{profile}' authenticated but not privileged: {arn}")
        return

    except ProfileNotFound:
        logger.error(f"[FATAL] AWS profile '{profile}' not found in your configuration.")
    except SSOError:
        logger.error(f"[FATAL] SSO session for '{profile}' is expired or invalid.")
        logger.error("Run: aws sso login --profile {profile}")
    except NoCredentialsError:
        logger.error(f"[FATAL] No valid credentials found for profile '{profile}'.")
    except ClientError as e:
        logger.error(f"[FATAL] Unable to verify IAM identity: {e}")
    except Exception as e:
        logger.error(f"[FATAL] Unexpected AWS error: {e}")

    sys.exit(1)


# -----------------------------------------------------------------------------
# Simulation-safe S3 head_object
# -----------------------------------------------------------------------------
def safe_head_object(s3, simulate: bool, bucket: str, key: str, logger: logging.Logger) -> bool:
    """Return True if object exists (simulation safe)."""
    if simulate:
        logger.debug(f"[SIMULATE] Would check s3://{bucket}/{key}")
        return True
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "404":
            return False
        logger.warning(f"S3 head_object failed for {key}: {e}")
        return False
    except Exception as e:
        logger.warning(f"S3 head_object error for {key}: {e}")
        return False


# -----------------------------------------------------------------------------
# Snapshot Verification
# -----------------------------------------------------------------------------
def verify_snapshots(ec2, manifest: Dict[str, Any], simulate: bool, logger: logging.Logger) -> Dict[str, str]:
    """Cross-verify that snapshots listed in manifest exist in EC2."""
    verified = {}
    if simulate:
        logger.info("[SIMULATE] Skipping EC2 snapshot verification.")
        for rec in manifest.get("Backups", []):
            sid = rec.get("DstSnapshotId") or rec.get("SrcSnapshotId")
            if sid:
                verified[sid] = "OK"
        return verified

    all_snaps = {rec.get("DstSnapshotId") or rec.get("SrcSnapshotId")
                 for rec in manifest.get("Backups", [])
                 if rec.get("DstSnapshotId") or rec.get("SrcSnapshotId")}

    if not all_snaps:
        logger.warning("No snapshots found in manifest.")
        return {}

    logger.info(f"Verifying {len(all_snaps)} snapshots in EC2…")
    for sid in all_snaps:
        try:
            resp = ec2.describe_snapshots(SnapshotIds=[sid])
            verified[sid] = "OK" if resp.get("Snapshots") else "MISSING"
        except ClientError:
            verified[sid] = "MISSING"
    return verified


# -----------------------------------------------------------------------------
# S3 Structure Inspection (new in v1.8.0)
# -----------------------------------------------------------------------------
def build_structure_overview(cfg: Dict[str, Any], s3, simulate: bool, logger: logging.Logger) -> Dict[str, Dict[str, Any]]:
    """
    Inspect key S3 prefixes for orchestrator_backup phases.
    Returns a dict: { phase: {"Objects": count, "Exists": bool} }
    """
    a = cfg["audit"]
    pfx = cfg["prefixes"]
    bucket = a["bucket"]

    phases = ["discover", "plan", "prep", "backup", "manifest", "logs", "artifacts", "indexes", "latest"]
    structure = {}

    logger.info("Inspecting S3 structure for orchestrator phases…")

    for ph in phases:
        prefix = f"{pfx['base'].rstrip('/')}/{ph}/"
        if simulate:
            exists, count = True, 0
            logger.debug(f"[SIMULATE] Would list s3://{bucket}/{prefix}")
        else:
            try:
                resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=5)
                count = resp.get("KeyCount", 0)
                exists = count > 0
            except ClientError as e:
                logger.warning(f"Failed to list {prefix}: {e}")
                count, exists = 0, False
        structure[ph] = {"Objects": count, "Exists": exists}

    return structure


# -----------------------------------------------------------------------------
# Core audit logic
# -----------------------------------------------------------------------------
def audit_run(cfg: Dict[str, Any], s3, ec2, logger: logging.Logger) -> Dict[str, Any]:
    """
    Perform completeness verification for one run, using strict config sections.
    """
    a = cfg["audit"]
    pfx = cfg["prefixes"]
    policy = cfg["policy"]
    report = cfg["report"]

    bucket = a["bucket"]
    run_id = a["run_id"]
    simulate = a.get("simulate", False)
    detail_level = report.get("detail_level", "summary")

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
        "DetailLevel": detail_level,
    }

    manifest_key = f"{pfx['base'].rstrip('/')}/{pfx['manifest'].rstrip('/')}/{run_id}/manifest.json"
    logger.info(f"Checking manifest: s3://{bucket}/{manifest_key}")

    # Try to load manifest from S3
    if safe_head_object(s3, simulate, bucket, manifest_key, logger):
        result["Manifest"] = "OK"
        if simulate:
            manifest = {"Backups": [{"VolumeId": "vol-simulated", "DstSnapshotId": "snap-simulated"}]}
        else:
            data = s3.get_object(Bucket=bucket, Key=manifest_key)["Body"].read().decode("utf-8")
            manifest = json.loads(data)
    else:
        manifest = {"Backups": []}
        logger.warning("Manifest not found — continuing with empty dataset.")

    # Map volumes
    for rec in manifest.get("Backups", []):
        vid = rec.get("VolumeId")
        sid = rec.get("DstSnapshotId") or rec.get("SrcSnapshotId")
        result["Volumes"][vid] = "OK" if sid else "MISSING"

    # Optional snapshot validation
    if policy.get("validate_snapshots", False):
        result["Snapshots"] = verify_snapshots(ec2, manifest, simulate, logger)

    # New: include S3 structure overview
    result["Structure"] = build_structure_overview(cfg, s3, simulate, logger)

    # Compute completeness score
    ok_vols = sum(1 for v in result["Volumes"].values() if v == "OK")
    total_vols = len(result["Volumes"]) or 1
    score = (ok_vols / total_vols) * 100
    result["CompletenessScore"] = round(score, 2)

    logger.info(f"Completeness Score: {score:.2f}% ({ok_vols}/{total_vols} volumes OK)")
    return result


# -----------------------------------------------------------------------------
# Entrypoint used by CLI (integration layer)
# -----------------------------------------------------------------------------
def run_audit_from_cli(args, cfg):
    """
    Full end-to-end entrypoint for recovery_audit_pkg CLI workflow.
    Handles:
      - IAM validation
      - AWS clients initialization
      - Audit run
      - Optional test PDF generation (--test-pdf)
      - Report file output
    """
    a = cfg["audit"]
    log_cfg = cfg["logging"]

    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    logger = build_logger("RecoveryAudit", level=level, fmt=log_cfg.get("format", "text"))

    logger.info("=== S3 Recovery Audit — Core Logic ===")
    verify_profile_privileges(a["profile"], logger)

    session = boto3.Session(profile_name=a["profile"], region_name=a["region"])
    s3 = session.client("s3")
    ec2 = session.client("ec2")

    # Run core audit
    result = audit_run(cfg, s3, ec2, logger)

    # Optional PDF test mode
    if getattr(args, "test_pdf", False):
        logger.info("Generating synthetic test PDF report (per --test-pdf flag)…")
        pdf_report_utils.generate_test_pdf(cfg, result, logger)
        logger.info("Test PDF generated successfully.")
        sys.exit(0)

    # Write JSON report locally
    report_path = Path(a["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Audit report written to {report_path.resolve()}")

    # Optional S3 upload
    upload_prefix = cfg["report"].get("s3_upload_prefix")
    if upload_prefix:
        key = f"{upload_prefix.rstrip('/')}/{a['run_id']}.json"
        logger.info(f"Uploading audit report to s3://{a['bucket']}/{key}")
        if not a.get("simulate", False):
            s3.upload_file(str(report_path), a["bucket"], key)
        else:
            logger.debug(f"[SIMULATE] Would upload report to s3://{a['bucket']}/{key}")

    logger.info("Recovery audit completed successfully.")
    return result
