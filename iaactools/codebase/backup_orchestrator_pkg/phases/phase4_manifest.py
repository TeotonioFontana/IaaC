# -*- coding: utf-8 -*-
"""
===============================================================================
 phase4_manifest.py — v2.0.0-alpha
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestrator
 Purpose............: Phase 4 — Consolidate snapshot results into a backup manifest
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Aggregates outputs from Phases 1-3 (validated inventories + snapshots)
 into a single `backup_manifest_<run-id>.json` file.
 Each region entry lists:
   • Instances from manifest inventories
   • Volumes validated for backup
   • Snapshots actually created
 The resulting manifest is integrity-hashed for audit and upload in Phase 5.
===============================================================================
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from iaactools.codebase.utils.integrity_utils import safe_save_json


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _load_json(path: Path) -> list | dict:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _collect_phase_outputs(run_id: str, logger: logging.Logger):
    """Collect Phase 1–3 outputs for aggregation."""
    base = Path.cwd() / "results" / "backup_audit" / run_id

    # Phase 1 — inventories
    phase1_path = base / "phase1_init.json"
    phase1 = _load_json(phase1_path)
    inventories = phase1.get("Inventories", {}) if isinstance(phase1, dict) else {}

    # Phase 2 — validated volumes per region
    volumes_by_region = {}
    for vf in base.glob("volumes_*.json"):
        region = vf.stem.replace("volumes_", "")
        volumes_by_region[region] = _load_json(vf)
        logger.debug(f"Loaded {len(volumes_by_region[region])} volumes from {region}")

    # Phase 3 — snapshots per region
    snapshots_by_region = {}
    for sf in base.glob("snapshots_*.json"):
        region = sf.stem.replace("snapshots_", "")
        snapshots_by_region[region] = _load_json(sf)
        logger.debug(f"Loaded {len(snapshots_by_region[region])} snapshots from {region}")

    return inventories, volumes_by_region, snapshots_by_region, base


# -----------------------------------------------------------------------------
# Main Phase Entry
# -----------------------------------------------------------------------------
def run(cfg: dict, logger: logging.Logger) -> dict:
    """Phase 4 — Generate consolidated backup manifest."""
    simulate = bool(cfg.get("audit", {}).get("simulate", False))
    run_id = cfg["audit"]["run_id"]

    result = {
        "Phase": "Manifest",
        "RunID": run_id,
        "Regions": [],
        "TotalInstances": 0,
        "TotalVolumes": 0,
        "TotalSnapshots": 0,
        "ManifestFile": None,
        "Status": "FAILED",
        "Error": None,
        "Simulate": simulate,
        "IntegrityHash": None,
    }

    # output directory
    results_dir = Path.cwd() / "results" / "backup_audit" / run_id
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"backup_manifest_{run_id}.json"

    # ----------------------------------------------------------------------
    # 🧪 Simulation Mode
    # ----------------------------------------------------------------------
    if simulate:
        logger.warning("[SIMULATION MODE] Phase 4 producing synthetic manifest.")
        synthetic = {
            "meta": {"run_id": run_id, "generated_at": datetime.utcnow().isoformat() + "Z"},
            "regions": {
                "us-east-1": {
                    "instances": [{"id": "i-simulated123"}],
                    "volumes": [{"id": "vol-simulated456"}],
                    "snapshots": [{"id": "snap-simulated789"}],
                }
            },
        }
        synthetic_path = out_path
        with synthetic_path.open("w", encoding="utf-8") as f:
            json.dump(synthetic, f, indent=2)
        result.update({
            "Regions": ["us-east-1"],
            "TotalInstances": 1,
            "TotalVolumes": 1,
            "TotalSnapshots": 1,
            "ManifestFile": str(synthetic_path),
            "Status": "SUCCESS",
        })
        result["IntegrityHash"] = safe_save_json(result, results_dir / "phase4_manifest.json", logger)
        logger.info(f"Simulated manifest generated → {synthetic_path}")
        return result

    # ----------------------------------------------------------------------
    # 1️⃣ Load prior phase outputs
    # ----------------------------------------------------------------------
    try:
        inventories, vols_by_region, snaps_by_region, base = _collect_phase_outputs(run_id, logger)
    except Exception as e:
        result["Error"] = f"Failed to collect phase outputs: {e}"
        safe_save_json(result, results_dir / "phase4_manifest.json", logger)
        logger.error(result["Error"])
        return result

    # ----------------------------------------------------------------------
    # 2️⃣ Build consolidated manifest structure
    # ----------------------------------------------------------------------
    manifest = {
        "meta": {
            "manifest_version": "1.0",
            "run_id": run_id,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        },
        "regions": {},
        "summary": {"instances": 0, "volumes": 0, "snapshots": 0},
    }

    for region, region_data in inventories.items():
        instances = region_data.get("instances", [])
        volumes = vols_by_region.get(region, [])
        snapshots = snaps_by_region.get(region, [])

        manifest["regions"][region] = {
            "instances": instances,
            "volumes": volumes,
            "snapshots": snapshots,
        }

        manifest["summary"]["instances"] += len(instances)
        manifest["summary"]["volumes"] += len(volumes)
        manifest["summary"]["snapshots"] += len(snapshots)
        result["Regions"].append(region)

        logger.info(
            f"Region {region}: {len(instances)} instances, "
            f"{len(volumes)} volumes, {len(snapshots)} snapshots."
        )

    # ----------------------------------------------------------------------
    # 3️⃣ Save manifest and register result
    # ----------------------------------------------------------------------
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    result.update({
        "TotalInstances": manifest["summary"]["instances"],
        "TotalVolumes": manifest["summary"]["volumes"],
        "TotalSnapshots": manifest["summary"]["snapshots"],
        "ManifestFile": str(out_path),
        "Status": "SUCCESS",
    })

    result["IntegrityHash"] = safe_save_json(result, results_dir / "phase4_manifest.json", logger)
    logger.info(f"[✔] Backup manifest created → {out_path}")
    return result


# -----------------------------------------------------------------------------
# Stand-alone test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    fake_cfg = {"audit": {"run_id": "20251104T120000Z", "simulate": True}}
    run(fake_cfg, logging.getLogger("Phase4Test"))
