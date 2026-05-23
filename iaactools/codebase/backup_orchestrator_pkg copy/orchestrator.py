# -*- coding: utf-8 -*-
"""
===============================================================================
 orchestrator.py — IaaC Tools Backup Orchestrator
===============================================================================
 Version.............: v0.7.2-alpha
 Author..............: Teotoniio Fontana — Architect
 Programmed by.......: Duke (GPT-5, OpenAI)
 Project.............: IaaC Tools / Backup Orchestration
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Performs complete backup operations for AWS EBS volumes and AMIs.
 Includes full Phase 0 Global AWS Environment Discovery (Account, CFN,
 Networking, Compute, Storage), with multi-region aggregation support.
 Provides colorized execution header, multi-line config reporting,
 manifest summary, and simulation-safe behavior.
===============================================================================
"""

from __future__ import annotations
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError, WaiterError

# -----------------------------------------------------------------------------
# Local imports — strictly for backup orchestration
# -----------------------------------------------------------------------------
from iaactools.codebase.common.config_validator import load_config
from iaactools.codebase.utils.logger_utils import ANSI, build_logger, log_step, log_phase_status
from .discovery import (
    load_instance_name_map,
    describe_volumes,
    log_discovery_items,
)
from .snapshots import (
    create_snapshot_for_volume,
    wait_snapshot_complete,
)
from .fullvol import (
    preclear_helper_instance,
    perform_full_volume_backup,
)
from .s3_utils import (
    upload_manifest_to_s3,
    upload_log_to_s3_if_present,
    write_latest_pointer,
)
from .discovery_ext import discover_environment_multi

# -----------------------------------------------------------------------------
# Metadata
# -----------------------------------------------------------------------------
SCRIPT_NAME = "IaacTools Backup Orchestrator"
SCRIPT_VERSION = "v0.7.2-alpha"
SCRIPT_OBJECTIVE = (
    "Automate AWS EBS/AMI backup creation, manifest publication, and validation."
)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def safe_sorted_keys(d: Dict) -> List[str]:
    return sorted(list(d.keys())) if isinstance(d, dict) else []

def utc_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def run_id_iso() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")

def secs_since(start: float) -> float:
    return round(time.time() - start, 2)

# -----------------------------------------------------------------------------
# Header and formatting
# -----------------------------------------------------------------------------
def log_run_header(logger, cfg: Dict, results_dir: Path, run_id: str, simulate: bool) -> None:
    profile = cfg.get("profile", "default")
    region = cfg.get("region", "us-east-1")
    config_path = cfg.get("_config_path", "unknown")
    log_path = results_dir / "audit.log"
    manifest_path = results_dir / f"manifest_{run_id}.json"
    banner = f"""
{ANSI['CYAN']}{'='*79}{ANSI['RESET']}
{ANSI['BOLD']} IaacTools Backup Orchestrator — Execution Context {ANSI['RESET']}
{ANSI['GRAY']}{'-'*79}{ANSI['RESET']}
  Profile ........: {ANSI['GREEN']}{profile}{ANSI['RESET']}
  Region .........: {ANSI['GREEN']}{region}{ANSI['RESET']}
  Simulation .....: {ANSI['YELLOW']}{simulate}{ANSI['RESET']}
  Run ID .........: {ANSI['GREEN']}{run_id}{ANSI['RESET']}
  Config file ....: {ANSI['CYAN']}{config_path}{ANSI['RESET']}
  Log file .......: {ANSI['CYAN']}{log_path}{ANSI['RESET']}
  Manifest file ..: {ANSI['CYAN']}{manifest_path}{ANSI['RESET']}
{ANSI['CYAN']}{'='*79}{ANSI['RESET']}
"""
    for line in banner.strip().splitlines():
        logger.info(line)

def format_multiline_config(cfg_path: Path, cfg: Dict) -> str:
    lines = [f"{ANSI['CYAN']}[CONFIG]{ANSI['RESET']} LOADED",
             f"    Path : {cfg_path}",
             "    Keys :"]
    for key in safe_sorted_keys(cfg):
        lines.append(f"       - {key}")
    return "\n".join(lines)

def write_manifest_summary(logger, manifest_path: Path, instances: List, volumes: List) -> None:
    logger.info(f"{ANSI['CYAN']}[MANIFEST]{ANSI['RESET']} Summary")
    logger.info(f"    Manifest saved to: {manifest_path}")
    logger.info(f"    Instances: {len(instances)}")
    logger.info(f"    Volumes  : {len(volumes)}")
    logger.info(f"{ANSI['GRAY']}{'-'*60}{ANSI['RESET']}")

# -----------------------------------------------------------------------------
# Phase 0 — Global AWS Environment Discovery (multi-region aware)
# -----------------------------------------------------------------------------
def phase0_global_discovery(logger, region: str, simulate: bool = False, cfg: Dict | None = None, regions_list: List[str] | None = None) -> Dict:
    start_phase = time.time()
    logger.info(f"{ANSI['BOLD']}{ANSI['BLUE']} PHASE0 — STARTING GLOBAL AWS ENVIRONMENT DISCOVERY {ANSI['RESET']}")
    logger.info(f"{ANSI['GRAY']}{'─'*70}{ANSI['RESET']}")

    multi = True if cfg and cfg.get("multi_region", True) else False
    if multi:
        manifest = discover_environment_multi({"region": region}, logger, regions_list)
    else:
        from .discovery_ext import discover_environment
        manifest, _ = discover_environment({"region": region}, logger)

    acct = manifest.get("account_identity", {})
    compute = manifest.get("compute", {}) or {}
    storage = manifest.get("storage", {}) or {}
    net = manifest.get("networking", {}) or {}
    cloud = manifest.get("cloudformation", {}) or {}
    summary = manifest.get("summary", {})

    total_elapsed = secs_since(start_phase)
    logger.info(f"=== Phase 0 Completed — Total Elapsed={total_elapsed:.2f}s ===")

    summary_line = (
        f"[✔] Phase AccountDiscovery: SUCCESS\n"
        f"        • Regions ............: {len(acct.get('regions_enabled', [])) or summary.get('regions_scanned', 1):>3}\n"
        f"        • CloudFormation .....: {len(cloud.get('stacks', [])):>3} stacks\n"
        f"        • Networking .........: {net.get('vpcs', 0):>3} VPCs, {net.get('subnets', 0):>3} subnets, "
        f"{net.get('security_groups', 0):>3} SGs\n"
        f"        • Compute ............: {compute.get('instances', summary.get('instances_total', 0)):>3} EC2, "
        f"{compute.get('lambda_functions', summary.get('lambda_total', 0)):>3} Lambda, "
        f"{compute.get('ecs_clusters', 0):>3} ECS, "
        f"{compute.get('ecr_repositories', 0):>3} ECR\n"
        f"        • Storage & Backup ...: {storage.get('s3_buckets', summary.get('s3_buckets_total', 0)):>3} S3, "
        f"{storage.get('rds_instances', 0):>3} RDS, {storage.get('efs_filesystems', 0):>3} EFS, "
        f"{storage.get('ebs_snapshots', 0):>3} Snapshots\n"
        f"        • IAM ................: {acct.get('iam', {}).get('users', 0):>3} users, "
        f"{acct.get('iam', {}).get('roles', 0):>3} roles, "
        f"{acct.get('iam', {}).get('groups', 0):>3} groups, "
        f"{acct.get('iam', {}).get('policies', 0):>3} policies"
    )
    for line in summary_line.splitlines():
        logger.info(line)

    logger.info(f"{ANSI['GRAY']}{'-'*70}{ANSI['RESET']}")
    logger.info(f"Phase 0 completed successfully in {total_elapsed:.2f} seconds.\n")
    return manifest

# -----------------------------------------------------------------------------
# Main Orchestration
# -----------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="backup_orchestrator",
        description="IaacTools Backup Orchestrator — EBS snapshots and full-volume backups.",
    )
    parser.add_argument("--config", required=True, help="Path to YAML or JSON configuration file")
    parser.add_argument("--run-id", help="Execution run identifier (ISO UTC format recommended)")
    parser.add_argument("--regions", help="Comma-separated list of regions to limit multi-region discovery (e.g. us-east-1,eu-west-1)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cfg["_config_path"] = str(Path(args.config).resolve())

    run_id = args.run_id or run_id_iso()
    results_dir = Path(cfg.get("log_dir", "./results/logs"))
    results_dir.mkdir(parents=True, exist_ok=True)
    simulate = bool(cfg.get("simulate", False))

    logger = build_logger("backup_orchestrator", results_dir, run_id)
    log_step(logger, "START", SCRIPT_NAME, Version=SCRIPT_VERSION, RunID=run_id)
    log_run_header(logger, cfg, results_dir, run_id, simulate)

    cfg_text = format_multiline_config(Path(args.config).resolve(), cfg)
    for line in cfg_text.splitlines():
        logger.info(line)

    region = cfg.get("region", "us-east-1")
    backup_type = cfg.get("backup_type", "snapshot")
    regions_list = args.regions.split(",") if args.regions else None

    # -------------------------------------------------------------------------
    # Phase 0 — Global or Multi-Region Discovery
    # -------------------------------------------------------------------------
    phase0_global_discovery(logger, region, simulate, cfg, regions_list)

    # -------------------------------------------------------------------------
    # Phase 1 — Instance/Volume Discovery
    # -------------------------------------------------------------------------
    start_time = time.time()
    log_step(logger, "PHASE1", "Discovering volumes and instances")
    ec2 = boto3.client("ec2", region_name=region)
    instances = load_instance_name_map(ec2)
    volumes = describe_volumes(ec2)
    log_discovery_items(logger, instances, volumes)
    log_phase_status(logger, "Discovery", "SUCCESS",
                     f"Instances={len(instances)} Volumes={len(volumes)}")

    # -------------------------------------------------------------------------
    # Phase 2 — Backup execution
    # -------------------------------------------------------------------------
    log_step(logger, "PHASE2", f"Performing {backup_type} backup")
    if backup_type in ("snapshot", "both"):
        for v in volumes:
            create_snapshot_for_volume(ec2, v, logger, simulate=simulate)
        wait_snapshot_complete(ec2, logger, simulate=simulate)
        log_phase_status(logger, "Snapshots", "SUCCESS",
                         "All simulated snapshots completed." if simulate else "All snapshots completed.")
    if backup_type in ("full-volume", "both"):
        helper_id = cfg.get("helper_instance_id")
        preclear_helper_instance(helper_id, logger, simulate=simulate)
        perform_full_volume_backup(helper_id, volumes, logger, simulate=simulate)

    # -------------------------------------------------------------------------
    # Phase 3 — Manifest + S3 Upload
    # -------------------------------------------------------------------------
    log_step(
        logger,
        "PHASE3",
        "Uploading manifests to S3" if not simulate else "Generating local manifest (simulation mode)"
    )

    manifest_path = results_dir / f"manifest_{run_id}.json"
    with manifest_path.open("w", encoding="utf-8") as mf:
        json.dump({
            "run_id": run_id,
            "instances": list(instances),
            "volumes": [v.get("VolumeId", "unknown") for v in volumes]
        }, mf, indent=2)

    if not simulate:
        upload_manifest_to_s3(cfg, logger)
        upload_log_to_s3_if_present(cfg, results_dir / "audit.log", logger)
        write_latest_pointer(cfg, logger)
    else:
        logger.info("[SIMULATION] Skipping S3 uploads to avoid environment pollution.")

    write_manifest_summary(
        logger,
        manifest_path,
        list(instances),
        [v.get("VolumeId", "unknown") for v in volumes]
    )

    # -------------------------------------------------------------------------
    # Wrap-up
    # -------------------------------------------------------------------------
    duration = secs_since(start_time)
    log_step(logger, "COMPLETE", "Backup orchestration finished", RunID=run_id, Duration=f"{duration}s")
    logger.info("All operations completed successfully.")
    sys.exit(0)

# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"{ANSI['RED']}\n[ABORTED] Interrupted by user.{ANSI['RESET']}")
        sys.exit(130)
