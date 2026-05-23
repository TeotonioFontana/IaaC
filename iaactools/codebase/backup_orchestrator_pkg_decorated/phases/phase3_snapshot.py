# -*- coding: utf-8 -*-
"""
===============================================================================
 phase3_snapshot.py — v3.0.0-alpha
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestrator
 Purpose............: Phase 3 — Snapshot creation based on validated volumes
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Consumes the per-region JSON volume lists produced by Phase 2 instead of
 calling EC2 directly.  Creates or simulates EBS snapshots and stores metadata
 under results/backup_audit/<run-id>/snapshots_<region>.json
===============================================================================
"""
from backup_orchestrator_pkg.result_envelope import enveloped

import boto3
import json
import logging
from pathlib import Path
from datetime import datetime
from botocore.exceptions import ClientError
from iaactools.codebase.utils.integrity_utils import safe_save_json


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _load_validated_volumes(cfg, logger):
    """Load validated volumes produced by Phase 2."""
    run_id = cfg["audit"]["run_id"]
    base = Path.cwd() / "results" / "backup_audit" / run_id
    volume_files = sorted(base.glob("volumes_*.json"))
    if not volume_files:
        raise FileNotFoundError("No validated volume files from Phase 2 found.")
    inventories = {}
    for vf in volume_files:
        region = vf.stem.replace("volumes_", "")
        logger.info(f"Loading validated volumes for region: {region}")
        with vf.open("r", encoding="utf-8") as f:
            inventories[region] = json.load(f)
    return inventories, base


# -----------------------------------------------------------------------------
# Main Phase Entry
# -----------------------------------------------------------------------------
@enveloped(schema={'cfg': {'type': dict, 'required': True}, 'logger': {'required': True}})
def run(cfg: dict, logger: logging.Logger) -> dict:
    """Phase 3 — Snapshot creation (real or simulated)."""
    simulate = bool(cfg.get("audit", {}).get("simulate", False))
    run_id = cfg["audit"]["run_id"]
    profile = cfg["audit"]["profile"]

    result = {
        "Phase": "Snapshot",
        "AWSProfile": profile,
        "SnapshotsCreated": 0,
        "RegionsProcessed": [],
        "Status": "FAILED",
        "Error": None,
        "Simulate": simulate,
        "IntegrityHash": None,
    }

    # result directory
    results_dir = Path.cwd() / "results" / "backup_audit" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / "phase3_snapshot.json"

    # ----------------------------------------------------------------------
    # 🧪 Simulation mode
    # ----------------------------------------------------------------------
    if simulate:
        logger.warning("[SIMULATION MODE] Phase 3 creating synthetic snapshots.")
        snapshots = [{
            "region": "us-east-1",
            "volume_id": "vol-simulated456",
            "snapshot_id": "snap-simulated123",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }]
        with (results_dir / "snapshots_us-east-1.json").open("w", encoding="utf-8") as f:
            json.dump(snapshots, f, indent=2)
        result.update({
            "SnapshotsCreated": len(snapshots),
            "RegionsProcessed": ["us-east-1"],
            "Status": "SUCCESS",
        })
        result["IntegrityHash"] = safe_save_json(result, out_path, logger)
        logger.info(f"Simulated {len(snapshots)} snapshots.")
        return result

    # ----------------------------------------------------------------------
    # 1️⃣ Load validated volume inventories
    # ----------------------------------------------------------------------
    try:
        inventories, base = _load_validated_volumes(cfg, logger)
    except Exception as e:
        result["Error"] = str(e)
        safe_save_json(result, out_path, logger)
        logger.error(result["Error"])
        return result

    total_snaps = 0

    # ----------------------------------------------------------------------
    # 2️⃣ Iterate regions and create snapshots
    # ----------------------------------------------------------------------
    for region, volumes in inventories.items():
        logger.info(f"Starting snapshot operations for region {region}...")
        session = boto3.Session(profile_name=profile, region_name=region)
        ec2 = session.client("ec2")
        region_snaps = []

        for vol in volumes:
            vol_id = vol.get("id")
            if not vol_id:
                logger.warning(f"Skipping invalid volume entry: {vol}")
                continue

            desc = f"IaaC-Backup {run_id} — automated snapshot for {vol_id}"
            try:
                snap = ec2.create_snapshot(VolumeId=vol_id, Description=desc)
                snap_id = snap["SnapshotId"]
                logger.info(f"[OK] Snapshot created: {snap_id} from {vol_id}")
            except ClientError as e:
                msg = f"[FAIL] Snapshot creation error for {vol_id}: {e}"
                logger.error(msg)
                continue

            entry = {
                "region": region,
                "volume_id": vol_id,
                "snapshot_id": snap_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "size_gb": vol.get("size_gb"),
                "state": "pending",
            }
            region_snaps.append(entry)
            total_snaps += 1

        # Save per-region snapshot metadata
        snap_file = base / f"snapshots_{region}.json"
        with snap_file.open("w", encoding="utf-8") as f:
            json.dump(region_snaps, f, indent=2)
        logger.info(f"{len(region_snaps)} snapshot entries written → {snap_file}")
        result["RegionsProcessed"].append(region)

    # ----------------------------------------------------------------------
    # 3️⃣ Finalize
    # ----------------------------------------------------------------------
    result["SnapshotsCreated"] = total_snaps
    result["Status"] = "SUCCESS" if total_snaps > 0 else "EMPTY"
    result["IntegrityHash"] = safe_save_json(result, out_path, logger)
    logger.info(f"Phase 3 completed — {total_snaps} snapshots initiated.")
    return result


# -----------------------------------------------------------------------------
# Stand-alone test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    fake_cfg = {
        "audit": {
            "profile": "default",
            "run_id": "20251104T120000Z",
            "simulate": True,
        }
    }
    run(fake_cfg, logging.getLogger("Phase3Test"))
