# -*- coding: utf-8 -*-
"""
===============================================================================
 phase4_manifest.py — v4.0.0-alpha2
===============================================================================
 Purpose............: Assemble comprehensive backup manifests including
                      volumes, snapshots, account properties, and
                      organization structure.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Generates three JSON manifests in the local results directory:
   1. backup_manifest.json — core backup inventory
   2. account_manifest.json — AWS account properties
   3. organization_manifest.json — AWS Organizations metadata (if available)

 Enhancements in v4.0.0-alpha2:
   • Embeds metadata about the KMS shadow key used for encryption.
   • Includes generation timestamp, IAM identity, and backup software version.
   • Designed to work under orchestrator abort-on-failure control.
===============================================================================
"""

import json, boto3, logging
from datetime import datetime
from pathlib import Path
from botocore.exceptions import ClientError


SCRIPT_VERSION = "4.0.0-alpha2"


def run(cfg: dict, logger: logging.Logger) -> Path:
    """
    Phase 4 — Assemble and write the manifests.
    Generates three JSON files inside /results/backup_audit/{run_id}/:
      - backup_manifest.json
      - account_manifest.json
      - organization_manifest.json
    """
    session = boto3.Session(profile_name=cfg["backup"]["profile"],
                            region_name=cfg["backup"]["region"])
    sts = session.client("sts")
    iam = session.client("iam")
    org = session.client("organizations")

    run_id = cfg["backup"]["run_id"]
    base_dir = Path.cwd() / "results" / "backup_audit" / run_id
    base_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    manifests = {}

    # -------------------------------------------------------------------------
    # 1. Get current AWS account info
    # -------------------------------------------------------------------------
    try:
        identity = sts.get_caller_identity()
        account_id = identity["Account"]
        arn = identity["Arn"]
        user_name = arn.split("/")[-1]
        logger.info(f"Account identity resolved: {arn}")
    except ClientError as e:
        logger.error(f"Failed to get caller identity: {e}")
        raise

    # -------------------------------------------------------------------------
    # 2. Account manifest
    # -------------------------------------------------------------------------
    try:
        account_aliases = iam.list_account_aliases().get("AccountAliases", [])
    except ClientError:
        account_aliases = []

    account_manifest = {
        "schema": "account_manifest_schema.json",
        "version": SCRIPT_VERSION,
        "generated_at": timestamp,
        "account_id": account_id,
        "account_aliases": account_aliases,
        "iam_summary": {},
        "kms_shadow_arn": cfg["backup"].get("kms_shadow_arn", "none"),
        "shadow_encrypted": cfg["backup"].get("shadow_encrypted", False),
    }

    try:
        iam_summary = iam.get_account_summary().get("SummaryMap", {})
        account_manifest["iam_summary"] = iam_summary
    except ClientError as e:
        logger.warning(f"Could not retrieve IAM summary: {e}")

    account_path = base_dir / "account_manifest.json"
    account_path.write_text(json.dumps(account_manifest, indent=2), encoding="utf-8")
    logger.info(f"Account manifest created: {account_path}")

    # -------------------------------------------------------------------------
    # 3. Organization manifest (optional)
    # -------------------------------------------------------------------------
    try:
        org_info = org.describe_organization()["Organization"]
        org_manifest = {
            "schema": "organization_manifest_schema.json",
            "version": SCRIPT_VERSION,
            "generated_at": timestamp,
            "organization_id": org_info.get("Id"),
            "master_account_id": org_info.get("MasterAccountId"),
            "master_account_email": org_info.get("MasterAccountEmail"),
            "feature_set": org_info.get("FeatureSet"),
            "accounts": [],
        }
        paginator = org.get_paginator("list_accounts")
        for page in paginator.paginate():
            for acct in page["Accounts"]:
                org_manifest["accounts"].append({
                    "id": acct["Id"],
                    "email": acct.get("Email"),
                    "status": acct.get("Status"),
                    "joined_method": acct.get("JoinedMethod"),
                    "joined_timestamp": acct.get("JoinedTimestamp").isoformat(),
                })

        org_path = base_dir / "organization_manifest.json"
        org_path.write_text(json.dumps(org_manifest, indent=2), encoding="utf-8")
        logger.info(f"Organization manifest created: {org_path}")
    except ClientError as e:
        logger.warning(f"No AWS Organization data available: {e}")
        org_path = None

    # -------------------------------------------------------------------------
    # 4. Backup manifest (core index)
    # -------------------------------------------------------------------------
    backup_manifest = {
        "schema": "backup_manifest_schema.json",
        "version": SCRIPT_VERSION,
        "generated_at": timestamp,
        "run_id": run_id,
        "bucket": cfg["backup"]["bucket"],
        "region": cfg["backup"]["region"],
        "profile": cfg["backup"]["profile"],
        "kms_shadow_arn": cfg["backup"].get("kms_shadow_arn", "none"),
        "shadow_encrypted": cfg["backup"].get("shadow_encrypted", False),
        "account_manifest": str(account_path),
        "organization_manifest": str(org_path) if org_path else None,
        "phases": {
            "volume": "OK",
            "snapshot": "OK",
            "upload": "PENDING",
            "validation": "PENDING",
        },
    }

    backup_path = base_dir / "backup_manifest.json"
    backup_path.write_text(json.dumps(backup_manifest, indent=2), encoding="utf-8")
    logger.info(f"Backup manifest created: {backup_path}")

    manifests["account"] = str(account_path)
    if org_path:
        manifests["organization"] = str(org_path)
    manifests["backup"] = str(backup_path)

    return backup_path


if __name__ == "__main__":
    print("Synthetic test: Phase4 manifest assembler stub executed.")
