# -*- coding: utf-8 -*-
"""
===============================================================================
 discovery_multi.py — v0.8.1-alpha
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestration
 Purpose............: Multi-Region AWS Discovery Orchestrator (clean human view)
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Iterates through all enabled AWS regions, performs the discovery cycle
 (CloudFormation, Networking, Compute, Storage) and classifies regions as:
   • ACTIVE  — Compute resources found (green)
   • STORAGE — No compute, but storage/networking present (yellow)
   • INACTIVE — Empty region (gray)
 Each region prints only one concise summary block.
===============================================================================
"""

import boto3
from datetime import datetime
from iaactools.codebase.utils.logger_utils import ANSI
from .discovery_core import (
    discover_account_identity,
    discover_cloudformation,
    discover_networking,
    discover_compute,
    discover_storage,
)


def _suppress_internal_logs(discover_fn, cfg, logger):
    """Run a discovery function quietly, ignoring its internal info logs."""
    level = logger.level
    logger.setLevel(100)  # temporarily silence info-level logs
    try:
        result = discover_fn(cfg, logger)
    finally:
        logger.setLevel(level)
    return result


def discover_environment_multi(cfg, logger, regions: list[str] | None = None):
    """Perform discovery across all enabled AWS regions and aggregate results."""
    start_global = datetime.utcnow()
    master_region = cfg.get("region", "us-east-1")

    ec2 = boto3.client("ec2", region_name=master_region)
    try:
        all_regions = [
            r["RegionName"]
            for r in ec2.describe_regions(AllRegions=True)["Regions"]
            if r["OptInStatus"] in ("opt-in-not-required", "opted-in")
        ]
    except Exception as e:
        logger.warning(f"Unable to list regions from {master_region}: {e}")
        all_regions = [master_region]

    if regions:
        all_regions = [r for r in all_regions if r in regions]

    logger.info(f"[🌎] Multi-Region Discovery — scanning {len(all_regions)} regions")

    global_manifest = {"account_identity": {}, "regions": {}, "summary": {}}
    account_data, _ = discover_account_identity(cfg, logger)
    global_manifest["account_identity"] = account_data

    total_vpcs = total_instances = total_lambdas = total_s3 = 0
    active_regions = storage_regions = inactive_regions = 0
    region_stats = []

    for region_name in all_regions:
        sub_cfg = cfg.copy()
        sub_cfg["region"] = region_name
        regional = {}
        region_start = datetime.utcnow()

        try:
            # Run all discovery steps quietly (inner logs suppressed)
            regional["cloudformation"], _ = _suppress_internal_logs(discover_cloudformation, sub_cfg, logger)
            regional["networking"], _ = _suppress_internal_logs(discover_networking, sub_cfg, logger)
            regional["compute"], _ = _suppress_internal_logs(discover_compute, sub_cfg, logger)
            regional["storage"], _ = _suppress_internal_logs(discover_storage, sub_cfg, logger)

            compute = regional["compute"]
            storage = regional["storage"]
            has_compute = any(v > 0 for k, v in compute.items() if k != "autoscaling_groups")
            has_storage = any(v > 0 for v in storage.values())
            has_network = regional["networking"].get("vpcs", 0) > 0

            if has_compute:
                color = ANSI["GREEN"]
                status = "ACTIVE"
                active_regions += 1
            elif has_storage or has_network:
                color = ANSI["YELLOW"]
                status = "STORAGE"
                storage_regions += 1
            else:
                color = ANSI["GRAY"]
                status = "INACTIVE"
                inactive_regions += 1

            # concise one-block summary
            if status == "INACTIVE":
                logger.info(f"{color}─── Region: {region_name} — Inactive{ANSI['RESET']}")
            else:
                logger.info(f"{color}─── Region: {region_name} — {status}{ANSI['RESET']}")
                logger.info(
                    f"{color}[✔] 0.2 CloudFormation — Stacks={len(regional['cloudformation'].get('stacks', []))} "
                    f"Failed={len(regional['cloudformation'].get('failed', []))}{ANSI['RESET']}"
                )
                logger.info(
                    f"{color}[✔] 0.3 Networking — VPCs={regional['networking'].get('vpcs',0)} "
                    f"Subnets={regional['networking'].get('subnets',0)} "
                    f"SGs={regional['networking'].get('security_groups',0)}{ANSI['RESET']}"
                )
                logger.info(
                    f"{color}[✔] 0.4 Compute — EC2={compute.get('instances',0)} "
                    f"ASG={compute.get('autoscaling_groups',0)} ELB={compute.get('load_balancers',0)} "
                    f"ECS={compute.get('ecs_clusters',0)} Lambda={compute.get('lambda_functions',0)} "
                    f"ECR={compute.get('ecr_repositories',0)}{ANSI['RESET']}"
                )
                logger.info(
                    f"{color}[✔] 0.5 Storage — S3={storage.get('s3_buckets',0)} "
                    f"RDS={storage.get('rds_instances',0)} EFS={storage.get('efs_filesystems',0)} "
                    f"Snapshots={storage.get('ebs_snapshots',0)}{ANSI['RESET']}"
                )

            total_vpcs += regional["networking"].get("vpcs", 0)
            total_instances += compute.get("instances", 0)
            total_lambdas += compute.get("lambda_functions", 0)
            total_s3 += storage.get("s3_buckets", 0)
            global_manifest["regions"][region_name] = regional

        except Exception as e:
            logger.warning(f"[!] Region {region_name} discovery failed: {e}")
            status = "ERROR"
            color = ANSI["RED"]

        elapsed = (datetime.utcnow() - region_start).total_seconds()
        region_stats.append((region_name, status, elapsed))
        logger.info(f"{ANSI['GRAY']}   └─ Elapsed: {elapsed:.2f}s{ANSI['RESET']}")

    # -------------------------------------------------------------------------
    # Summary aggregation
    # -------------------------------------------------------------------------
    global_manifest["summary"] = {
        "regions_scanned": len(global_manifest["regions"]),
        "active_regions": active_regions,
        "storage_regions": storage_regions,
        "inactive_regions": inactive_regions,
        "vpcs_total": total_vpcs,
        "instances_total": total_instances,
        "lambda_total": total_lambdas,
        "s3_buckets_total": total_s3,
        "elapsed_sec": round((datetime.utcnow() - start_global).total_seconds(), 2),
    }

    logger.info(
        f"[✔] Multi-Region Discovery completed — {len(all_regions)} regions "
        f"({active_regions} active, {storage_regions} storage, {inactive_regions} inactive)."
    )

    # -------------------------------------------------------------------------
    # Final summary table
    # -------------------------------------------------------------------------
    logger.info(f"{ANSI['CYAN']}{'='*72}{ANSI['RESET']}")
    logger.info(f"{ANSI['BOLD']} Multi-Region Summary by Region {ANSI['RESET']}")
    logger.info(f"{ANSI['CYAN']}{'-'*72}{ANSI['RESET']}")
    logger.info(f"{ANSI['BOLD']}  Region{' ' * 20}│ Status     │ Elapsed (s){ANSI['RESET']}")
    logger.info(f"{ANSI['CYAN']}{'-'*72}{ANSI['RESET']}")

    for region_name, status, elapsed in region_stats:
        color = (
            ANSI["GREEN"] if status == "ACTIVE"
            else ANSI["YELLOW"] if status == "STORAGE"
            else ANSI["GRAY"]
        )
        logger.info(
            f"{color}  {region_name:<25}│ {status:<10}│ {elapsed:>8.2f}{ANSI['RESET']}"
        )

    logger.info(f"{ANSI['CYAN']}{'-'*72}{ANSI['RESET']}")
    logger.info(
        f"{ANSI['BOLD']}Total Regions={len(all_regions)} | "
        f"Active={active_regions} | Storage={storage_regions} | Inactive={inactive_regions} | "
        f"Elapsed={global_manifest['summary']['elapsed_sec']}s{ANSI['RESET']}"
    )
    logger.info(f"{ANSI['CYAN']}{'='*72}{ANSI['RESET']}")

    return global_manifest
