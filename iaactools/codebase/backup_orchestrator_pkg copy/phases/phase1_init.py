#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
 phase1_init.py — v4.0.0-alpha4
===============================================================================
 Purpose............: Environment initialization and S3 pre-flight validation.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 This phase ensures the backup environment is ready before any operation.
 It validates:
   • AWS credentials and profile access
   • Target S3 bucket reachability
   • Required local results directory
   • Connectivity to required AWS services

 Simulation mode (`simulate=True`) allows safe dry-runs with synthetic results.
 Integrity is managed centrally via utils.integrity_utils.safe_save_json().
===============================================================================
"""

import boto3
import logging
import json
from pathlib import Path
from botocore.exceptions import NoCredentialsError, ClientError, EndpointConnectionError

# Shared integrity utility
from iaactools.codebase.utils.integrity_utils import safe_save_json


def run(cfg: dict, logger: logging.Logger) -> dict:
    """Phase 1 — Initialization and environment validation."""
    simulate = bool(cfg.get("audit", {}).get("simulate", False))
    run_id = cfg["audit"]["run_id"]

    result = {
        "Phase": "Init",
        "AWSProfile": cfg["audit"]["profile"],
        "Region": cfg["audit"]["region"],
        "Bucket": cfg["audit"]["bucket"],
        "S3Access": False,
        "CredentialsOK": False,
        "ResultsDir": None,
        "Status": "FAILED",
        "Error": None,
        "Simulate": simulate,
        "IntegrityHash": None,
    }

    results_dir = Path.cwd() / "results" / "backup_audit" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    result["ResultsDir"] = str(results_dir)

    out_path = results_dir / "phase1_init.json"

    # ----------------------------------------------------------------------
    # 🧪 Simulation Mode
    # ----------------------------------------------------------------------
    if simulate:
        logger.warning("[SIMULATION MODE] Phase 1 running with no real AWS calls.")
        result.update({
            "S3Access": True,
            "CredentialsOK": True,
            "Status": "SUCCESS",
        })
        result["IntegrityHash"] = safe_save_json(result, out_path, logger)
        logger.info(f"Simulated Phase 1 result saved with hash {result['IntegrityHash']}")
        return result

    # ----------------------------------------------------------------------
    # 1️⃣ Validate AWS credentials
    # ----------------------------------------------------------------------
    try:
        session = boto3.Session(profile_name=cfg["audit"]["profile"], region_name=cfg["audit"]["region"])
        sts = session.client("sts")
        ident = sts.get_caller_identity()
        result["CredentialsOK"] = True
        logger.info(f"Authenticated as {ident.get('Arn')} (Account {ident.get('Account')})")
    except NoCredentialsError:
        msg = "No valid AWS credentials found."
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result
    except Exception as e:
        msg = f"AWS credential check failed: {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result

    # ----------------------------------------------------------------------
    # 2️⃣ Check S3 bucket access
    # ----------------------------------------------------------------------
    try:
        s3 = session.client("s3")
        bucket = cfg["audit"]["bucket"]
        s3.head_bucket(Bucket=bucket)
        result["S3Access"] = True
        logger.info(f"S3 bucket reachable: s3://{bucket}")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        msg = f"S3 bucket check failed ({code}): {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result
    except EndpointConnectionError as e:
        msg = f"S3 endpoint connection failed: {e}"
        logger.error(msg)
        result["Error"] = msg
        safe_save_json(result, out_path, logger)
        return result

    # ----------------------------------------------------------------------
    # 3️⃣ Confirm core AWS services connectivity
    # ----------------------------------------------------------------------
    try:
        ec2 = session.client("ec2")
        _ = ec2.describe_regions()
        logger.debug("Connectivity test to EC2 service succeeded.")
    except Exception as e:
        msg = f"EC2 connectivity test failed: {e}"
        logger.warning(msg)

    # ----------------------------------------------------------------------
    # 4️⃣ Mark phase success and save
    # ----------------------------------------------------------------------
    result["Status"] = "SUCCESS"
    result["IntegrityHash"] = safe_save_json(result, out_path, logger)
    logger.info(f"Phase 1 result saved → {out_path}")
    logger.info(f"Integrity hash: {result['IntegrityHash']}")
    return result


if __name__ == "__main__":
    import logging
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
    run(fake_cfg, logging.getLogger("Phase1Test"))
