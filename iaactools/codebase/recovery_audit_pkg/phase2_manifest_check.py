# -*- coding: utf-8 -*-
"""
===============================================================================
 phase2_manifest_check.py — v4.0.0-alpha1
===============================================================================
 Purpose............: Validate presence and structure of all manifest files.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Phase 2 ensures that the three critical manifests exist and are internally
 consistent:
   • manifest.json — infrastructure backups
   • manifest_account.json — AWS account configuration
   • manifest_organizations.json — AWS Organizations hierarchy
===============================================================================
"""
import json, boto3, logging
from botocore.exceptions import ClientError

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _load_manifest(s3, bucket, key, logger):
    """Fetch and parse a JSON manifest from S3."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read().decode("utf-8"))
        logger.debug(f"Loaded manifest: s3://{bucket}/{key}")
        return data
    except ClientError as e:
        logger.error(f"Missing or unreadable manifest: s3://{bucket}/{key} — {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format: {key} — {e}")
        return None


# -----------------------------------------------------------------------------
# Main Phase Runner
# -----------------------------------------------------------------------------
def run(cfg, logger: logging.Logger) -> dict:
    """Phase 2 — Validate existence and schema of manifests."""
    s3 = boto3.client("s3", region_name=cfg["audit"]["region"])
    bucket = cfg["audit"]["bucket"]
    base = cfg["prefixes"]["base"]
    run_id = cfg["audit"]["run_id"]

    manifest_prefix = f"{base.rstrip('/')}/runs/{run_id}/manifest"
    manifests = {
        "Infrastructure": f"{manifest_prefix}/manifest.json",
        "Account": f"{manifest_prefix}/manifest_account.json",
        "Organizations": f"{manifest_prefix}/manifest_organizations.json",
    }

    result = {name: {"Exists": False, "Objects": 0} for name in manifests}
    result["Status"] = "FAILED"

    loaded = {}

    for name, key in manifests.items():
        data = _load_manifest(s3, bucket, key, logger)
        if data:
            result[name]["Exists"] = True
            result[name]["Objects"] = 1
            loaded[name] = data

    # Validate schema of each manifest if loaded
    valid = True

    if "Infrastructure" in loaded:
        if "Backups" not in loaded["Infrastructure"]:
            logger.error("manifest.json missing 'Backups' section")
            valid = False

    if "Account" in loaded:
        acc = loaded["Account"]
        required = {"AccountId", "EnabledRegions", "KMS_Keys"}
        if not required.issubset(acc.keys()):
            logger.error("manifest_account.json missing required keys")
            valid = False

    if "Organizations" in loaded:
        org = loaded["Organizations"]
        required = {"OrganizationId", "ChildAccounts", "Policies"}
        if not required.issubset(org.keys()):
            logger.error("manifest_organizations.json missing required keys")
            valid = False

    # Cross integrity check
    if "Account" in loaded and "Organizations" in loaded:
        acc_id = loaded["Account"].get("AccountId")
        master = loaded["Organizations"].get("MasterAccount")
        if acc_id and master and acc_id != master:
            logger.warning(
                f"Account ID mismatch: Account={acc_id}, Org.Master={master}"
            )
        else:
            result["CrossCheck"] = "OK"

    if valid and all(v["Exists"] for v in result.values() if isinstance(v, dict)):
        result["Status"] = "OK"
        logger.info("All manifest files validated successfully.")
    else:
        logger.error("Manifest validation failed for one or more files.")

    return result


if __name__ == "__main__":
    print("Synthetic test: Phase 2 manifest validation stub.")
