# -*- coding: utf-8 -*-
"""
===============================================================================
 discovery_ext.py — v2.0.0-canonical
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestrator
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Phase-0 unified orchestrator for AWS environment discovery.
 Compatible with discovery_core v2.0.0-canonical structured returns.

 • Performs full single-region and multi-region discovery
 • Validates each sub-phase strictly (abort region if any fails)
 • Generates phase0 manifest, integrity hash, and summary
 • Produces normalized keys (snake_case) across all sections
===============================================================================
"""

import json
import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from .discovery_core import (
    discover_account_identity,
    discover_cloudformation,
    discover_networking,
    discover_compute,
    discover_storage,
)

# -----------------------------------------------------------------------------
# Utility helpers
# -----------------------------------------------------------------------------
def _sha256_file(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: str | Path, data: Dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _count(value) -> int:
    """Safe counter tolerant to int, iterable, or None."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        return len(value)
    except Exception:
        return 0


# -----------------------------------------------------------------------------
# Canonical normalizers (snake_case schema)
# -----------------------------------------------------------------------------
def _normalize_region_manifest(m: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure normalized key naming for consistency."""
    if not isinstance(m, dict):
        return {}

    out = dict(m)

    # flatten common patterns
    if "AccountId" in out:
        out["account_id"] = out.pop("AccountId")

    # skip deeper normalization here: already snake_case from core v2
    return out


# -----------------------------------------------------------------------------
# Phase 0.0 — Single-region orchestrator
# -----------------------------------------------------------------------------
def discover_environment(cfg: dict, logger) -> Dict[str, Any]:
    """
    Execute all Phase-0 discovery stages for one AWS region.
    Enforces strict validation: aborts region if any sub-phase fails.
    """
    start = time.time()
    region = cfg.get("region")
    manifest = {"region": region, "timestamp": datetime.utcnow().isoformat() + "Z"}

    logger.info(f"=== Phase 0: AWS Account + Region Discovery ({region}) ===")

    try:
        # 0.1 — Identity
        ident = discover_account_identity(cfg, logger)
        if not ident.get("ok"):
            raise RuntimeError(f"AccountIdentity failed: {ident.get('error')}")
        manifest["account_identity"] = ident["data"]

        # 0.2 — CloudFormation
        cfn = discover_cloudformation(cfg, logger)
        if not cfn.get("ok"):
            raise RuntimeError(f"CloudFormation failed: {cfn.get('error')}")
        manifest["cloudformation"] = cfn["data"]

        # 0.3 — Networking
        net = discover_networking(cfg, logger)
        if not net.get("ok"):
            raise RuntimeError(f"Networking failed: {net.get('error')}")
        manifest["networking"] = net["data"]

        # 0.4 — Compute
        comp = discover_compute(cfg, logger)
        if not comp.get("ok"):
            raise RuntimeError(f"Compute failed: {comp.get('error')}")
        manifest["compute"] = comp["data"]

        # 0.5 — Storage
        stor = discover_storage(cfg, logger)
        if not stor.get("ok"):
            raise RuntimeError(f"Storage failed: {stor.get('error')}")
        manifest["storage"] = stor["data"]

    except Exception as e:
        logger.error(f"[✖] Phase 0 discovery failed for region {region}: {e}")
        manifest["error"] = str(e)
        manifest["ok"] = False
        manifest["elapsed"] = round(time.time() - start, 2)
        return manifest

    elapsed = round(time.time() - start, 2)

    # Log short summary counts
    acct = manifest.get("account_identity", {})
    cfn = manifest.get("cloudformation", {})
    net = manifest.get("networking", {})
    comp = manifest.get("compute", {})
    stor = manifest.get("storage", {})

    logger.info(
        f"[✔] 0.1 AccountIdentity — Account={acct.get('account_id')} "
        f"Regions={_count(acct.get('regions_enabled'))} "
        f"IAM_Users={_count(acct.get('iam', {}).get('users'))} "
        f"Roles={_count(acct.get('iam', {}).get('roles'))}"
    )
    logger.info(
        f"[✔] 0.2 CloudFormation — Stacks={_count(cfn.get('stacks'))} "
        f"Failed={_count(cfn.get('failed'))}"
    )
    logger.info(
        f"[✔] 0.3 Networking — VPCs={_count(net.get('vpcs'))} "
        f"Subnets={_count(net.get('subnets'))} SGs={_count(net.get('security_groups'))}"
    )
    logger.info(
        f"[✔] 0.4 Compute — EC2={_count(comp.get('instances'))} "
        f"ASG={_count(comp.get('autoscaling_groups'))} "
        f"ELB={_count(comp.get('load_balancers'))} "
        f"ECS={_count(comp.get('ecs_clusters'))} "
        f"Lambda={_count(comp.get('lambda_functions'))}"
    )
    logger.info(
        f"[✔] 0.5 Storage — S3={_count(stor.get('s3_buckets'))} "
        f"RDS={_count(stor.get('rds_instances'))} "
        f"EFS={_count(stor.get('efs_filesystems'))} "
        f"Snapshots={_count(stor.get('ebs_snapshots'))}"
    )

    manifest["ok"] = True
    manifest["elapsed"] = elapsed
    logger.info(f"    └─ Elapsed: {elapsed:.2f}s")
    return _normalize_region_manifest(manifest)


# -----------------------------------------------------------------------------
# Phase 0 — Multi-region orchestrator
# -----------------------------------------------------------------------------
def discover_environment_multi(cfg: dict, logger, regions_list=None) -> Dict[str, Any]:
    """
    Perform multi-region discovery and aggregate results into unified manifest.
    Stops processing on the first region failure (strict mode).
    """
    start_global = time.time()
    manifest_global = {
        "meta": {
            "manifest_version": "2.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
        },
        "regions": {},
        "summary": {"regions": 0, "instances": 0, "volumes": 0, "snapshots": 0},
    }

    regions = regions_list or cfg.get("regions") or [cfg.get("region")]
    logger.info(f"[🌎] Multi-Region Discovery — scanning {len(regions)} regions")

    total_instances = 0
    total_volumes = 0
    total_snapshots = 0

    for region in regions:
        logger.info(f"─── Region: {region} — STORAGE")
        cfg_region = {**cfg, "region": region}
        start = time.time()

        region_manifest = discover_environment(cfg_region, logger)
        manifest_global["regions"][region] = region_manifest

        if not region_manifest.get("ok"):
            logger.error(f"[✖] Halting multi-region discovery: region {region} failed validation.")
            break

        compute = region_manifest.get("compute", {})
        storage = region_manifest.get("storage", {})

        total_instances += _count(compute.get("instances"))
        total_volumes += _count(storage.get("volumes"))
        total_snapshots += _count(storage.get("ebs_snapshots"))

        elapsed = round(time.time() - start, 2)
        logger.info(f"[✔] Region {region} — Instances={_count(compute.get('instances'))} "
                    f"Volumes={_count(storage.get('volumes'))} Elapsed={elapsed:.2f}s")

    manifest_global["summary"] = {
        "regions": len(regions),
        "instances": total_instances,
        "volumes": total_volumes,
        "snapshots": total_snapshots,
    }

    elapsed_global = round(time.time() - start_global, 2)
    logger.info(
        f"[✔] Phase Discovery: SUCCESS — Regions={len(regions)} "
        f"Instances={total_instances} Volumes={total_volumes} Snapshots={total_snapshots} "
        f"(Elapsed {elapsed_global:.1f}s)"
    )

    # --- Integrity Summary Generation ---------------------------------------
    summary_data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "regions": len(regions),
        "instances": total_instances,
        "volumes": total_volumes,
        "snapshots": total_snapshots,
    }

    output_dir = Path("./results/logs")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest_phase0.json"
    summary_path = output_dir / "phase0_summary.json"

    _write_json(manifest_path, manifest_global)
    _write_json(summary_path, summary_data)
    _write_json(output_dir / "phase0_hash.json", {"sha256": _sha256_file(manifest_path)})

    logger.info("[🔒] Phase 0 integrity summary and hash generated successfully.")
    return manifest_global


# -----------------------------------------------------------------------------
# Phase 0 Integrity Verification
# -----------------------------------------------------------------------------
def verify_phase0_integrity(manifest_path: str, summary_path: str, logger) -> Dict[str, Any]:
    """
    Verify the integrity of Phase 0 discovery results.
    Compares SHA256 hash and validates minimal keys in summary.
    Returns dict with verified=True|False and diagnostic info.
    """
    try:
        hash_file = Path(manifest_path).parent / "phase0_hash.json"
        if not Path(hash_file).exists():
            logger.warning("[⚠️] No hash file found for integrity verification.")
            return {"verified": False, "reason": "hash_missing"}

        with open(hash_file, "r", encoding="utf-8") as f:
            stored_hash = json.load(f).get("sha256")

        current_hash = _sha256_file(manifest_path)
        hash_ok = stored_hash == current_hash

        with open(summary_path, "r", encoding="utf-8") as f:
            summary_data = json.load(f)

        required_keys = {"regions", "instances", "volumes"}
        missing_keys = [k for k in required_keys if k not in summary_data]
        summary_ok = not missing_keys

        verified = hash_ok and summary_ok
        if verified:
            logger.info("[✅] Phase 0 integrity verified successfully.")
        else:
            logger.warning(f"[⚠️] Phase 0 integrity mismatch: hash_ok={hash_ok}, summary_ok={summary_ok}")

        return {
            "verified": verified,
            "hash_ok": hash_ok,
            "summary_ok": summary_ok,
            "missing_keys": missing_keys,
        }

    except Exception as e:
        logger.error(f"[✖] Phase 0 integrity verification failed: {e}")
        return {"verified": False, "error": str(e)}
