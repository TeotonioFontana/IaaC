# -*- coding: utf-8 -*-
"""
===============================================================================
 phase5_upload.py — v2.0.0-alpha
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestrator
 Purpose............: Phase 5 — Upload consolidated backup manifest to S3
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Uploads the `backup_manifest_<run-id>.json` and `phase4_manifest.json`
 integrity record to the target S3 bucket defined in the audit config.
 Uses boto3 for actual upload or simulation mode for dry runs.
===============================================================================
"""
from backup_orchestrator_pkg.result_envelope import enveloped

import boto3
import logging
from pathlib import Path
from datetime import datetime
from botocore.exceptions import ClientError, EndpointConnectionError
from iaactools.codebase.utils.integrity_utils import safe_save_json


# -----------------------------------------------------------------------------
# Main Phase Entry
# -----------------------------------------------------------------------------
@enveloped(schema={'cfg': {'type': dict, 'required': True}, 'logger': {'required': True}})
def run(cfg: dict, logger: logging.Logger) -> dict:
    """Phase 5 — Upload manifest and integrity record to S3."""
    simulate = bool(cfg.get("audit", {}).get("simulate", False))
    audit = cfg["audit"]
    run_id = audit["run_id"]
    profile = audit["profile"]
    region = audit["region"]
    bucket = audit["bucket"]

    result = {
        "Phase": "Upload",
        "RunID": run_id,
        "Bucket": bucket,
        "Region": region,
        "ManifestUploaded": False,
        "IntegrityRecordUploaded": False,
        "Status": "FAILED",
        "Error": None,
        "Simulate": simulate,
        "IntegrityHash": None,
    }

    results_dir = Path.cwd() / "results" / "backup_audit" / run_id
    manifest_path = results_dir / f"backup_manifest_{run_id}.json"
    integrity_path = results_dir / "phase4_manifest.json"
    out_path = results_dir / "phase5_upload.json"

    # ----------------------------------------------------------------------
    # 🧪 Simulation Mode
    # ----------------------------------------------------------------------
    if simulate:
        logger.warning("[SIMULATION MODE] Phase 5 running without real S3 uploads.")
        logger.info(f"Would upload: {manifest_path.name} and {integrity_path.name}")
        result.update({
            "ManifestUploaded": True,
            "IntegrityRecordUploaded": True,
            "Status": "SUCCESS",
        })
        result["IntegrityHash"] = safe_save_json(result, out_path, logger)
        return result

    # ----------------------------------------------------------------------
    # 1️⃣ Establish S3 session
    # ----------------------------------------------------------------------
    try:
        session = boto3.Session(profile_name=profile, region_name=region)
        s3 = session.client("s3")
        s3.head_bucket(Bucket=bucket)
        logger.info(f"S3 bucket reachable: s3://{bucket}")
    except EndpointConnectionError as e:
        msg = f"S3 endpoint connection failed: {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result
    except ClientError as e:
        msg = f"S3 bucket access error: {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result

    # ----------------------------------------------------------------------
    # 2️⃣ Upload files
    # ----------------------------------------------------------------------
    try:
        timestamp = datetime.utcnow().strftime("%Y/%m/%d")
        s3_prefix = f"backup_manifests/{timestamp}/{run_id}"
        manifest_key = f"{s3_prefix}/{manifest_path.name}"
        integrity_key = f"{s3_prefix}/{integrity_path.name}"

        # Upload manifest
        s3.upload_file(str(manifest_path), bucket, manifest_key)
        result["ManifestUploaded"] = True
        logger.info(f"Uploaded manifest → s3://{bucket}/{manifest_key}")

        # Upload integrity record
        s3.upload_file(str(integrity_path), bucket, integrity_key)
        result["IntegrityRecordUploaded"] = True
        logger.info(f"Uploaded integrity record → s3://{bucket}/{integrity_key}")

    except Exception as e:
        msg = f"Upload failure: {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result

    # ----------------------------------------------------------------------
    # 3️⃣ Finalize
    # ----------------------------------------------------------------------
    result["Status"] = "SUCCESS"
    result["IntegrityHash"] = safe_save_json(result, out_path, logger)
    logger.info(f"Phase 5 complete — manifest and integrity uploaded successfully.")
    return result


# -----------------------------------------------------------------------------
# Stand-alone test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    fake_cfg = {
        "audit": {
            "profile": "default",
            "region": "us-east-1",
            "bucket": "my-test-bucket",
            "run_id": "20251104T120000Z",
            "simulate": True,
        }
    }
    run(fake_cfg, logging.getLogger("Phase5Test"))
