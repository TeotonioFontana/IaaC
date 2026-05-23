# -*- coding: utf-8 -*-
"""
===============================================================================
 discovery_core.py — v2.0.0-canonical
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestrator
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 Canonical version of the Phase-0 discovery layer.
 Preserves all logic from v0.8.2-alpha but unifies every discover_*()
 under a deterministic contract:

 {
     "ok": bool,
     "elapsed": float,
     "data": dict,
     "error": str | None
 }

 No tuples.  Always returns elapsed seconds and empty data on failure.
===============================================================================
"""

import time
import boto3
from datetime import datetime
from botocore.exceptions import ClientError, ReadTimeoutError


# -----------------------------------------------------------------------------
# Decorator enforcing canonical return contract
# -----------------------------------------------------------------------------
def phase0_contract(func):
    def wrapper(cfg, logger):
        start = time.time()
        result = {"ok": False, "elapsed": 0.0, "data": {}, "error": None}
        try:
            data = func(cfg, logger)
            if isinstance(data, dict):
                result["data"] = data
                result["ok"] = True
            else:
                result["error"] = f"{func.__name__} returned {type(data).__name__}, expected dict"
        except Exception as e:
            result["error"] = f"{func.__name__} failed: {e}"
        finally:
            result["elapsed"] = round(time.time() - start, 2)
            return result
    return wrapper


# -----------------------------------------------------------------------------
# Discovery helpers
# -----------------------------------------------------------------------------
def safe_paginate(client, method_name: str, result_key: str, **kwargs):
    """Return concatenated pages for any List*/Describe* with pagination."""
    results = []
    try:
        paginator = client.get_paginator(method_name)
        for page in paginator.paginate(**kwargs):
            results.extend(page.get(result_key, []))
    except Exception:
        pass
    return results


def safe_describe(client, func_name: str, **kwargs):
    """Call a boto3 describe_* safely, returning {} on access errors."""
    try:
        func = getattr(client, func_name)
        return func(**kwargs)
    except ClientError as e:
        if any(x in str(e) for x in ["AccessDenied", "UnauthorizedOperation"]):
            raise
        return {}
    except Exception:
        return {}


# -----------------------------------------------------------------------------
# 0.1 — Account & Identity
# -----------------------------------------------------------------------------
@phase0_contract
def discover_account_identity(cfg, logger):
    sts = boto3.client("sts")
    ec2 = boto3.client("ec2", region_name=cfg.get("region", "us-east-1"))
    orgs = boto3.client("organizations")
    iam = boto3.client("iam")

    ident = {"iam": {}}
    try:
        caller = sts.get_caller_identity()
        ident["account_id"] = caller.get("Account")
        ident["caller_arn"] = caller.get("Arn")
    except Exception as e:
        logger.error(f"STS identity failed: {e}")

    try:
        org = orgs.describe_organization()
        ident["organization_id"] = org["Organization"]["Id"]
        ident["master_account_id"] = org["Organization"].get("MasterAccountId")
    except ClientError as e:
        logger.warning(f"No AWS Organizations info available: {e}")

    try:
        regions = ec2.describe_regions(AllRegions=True)
        ident["regions_enabled"] = [
            r["RegionName"]
            for r in regions["Regions"]
            if r["OptInStatus"] in ("opt-in-not-required", "opted-in")
        ]
    except Exception as e:
        logger.warning(f"Region discovery failed: {e}")

    try:
        users = safe_paginate(iam, "list_users", "Users")
        roles = safe_paginate(iam, "list_roles", "Roles")
        groups = safe_paginate(iam, "list_groups", "Groups")
        policies = safe_paginate(iam, "list_policies", "Policies", Scope="Local")
        ident["iam"].update(
            {
                "users": len(users),
                "roles": len(roles),
                "groups": len(groups),
                "policies": len(policies),
            }
        )
    except Exception as e:
        logger.warning(f"IAM discovery failed: {e}")

    logger.info(
        f"[✔] 0.1 AccountIdentity — Account={ident.get('account_id')} "
        f"Regions={len(ident.get('regions_enabled', []))} "
        f"IAM_Users={ident['iam'].get('users',0)} Roles={ident['iam'].get('roles',0)}"
    )
    return ident


# -----------------------------------------------------------------------------
# 0.2 — CloudFormation
# -----------------------------------------------------------------------------
@phase0_contract
def discover_cloudformation(cfg, logger):
    cfn = boto3.client("cloudformation", region_name=cfg.get("region", "us-east-1"))
    stacks, outputs, failed = [], [], []
    try:
        paginator = cfn.get_paginator("list_stacks")
        for page in paginator.paginate():
            for s in page.get("StackSummaries", []):
                stacks.append(s["StackName"])
                if "FAILED" in s["StackStatus"]:
                    failed.append(s["StackName"])
        for name in stacks[:10]:
            desc = cfn.describe_stacks(StackName=name)["Stacks"][0]
            outs = {o["OutputKey"]: o["OutputValue"] for o in desc.get("Outputs", [])}
            outputs.append({"stack": name, "outputs": outs})
    except ClientError as e:
        logger.warning(f"CloudFormation discovery failed: {e}")

    logger.info(f"[✔] 0.2 CloudFormation — Stacks={len(stacks)} Failed={len(failed)}")
    return {"stacks": stacks, "failed": failed, "outputs": outputs}


# -----------------------------------------------------------------------------
# 0.3 — Networking
# -----------------------------------------------------------------------------
@phase0_contract
def discover_networking(cfg, logger):
    ec2 = boto3.client("ec2", region_name=cfg.get("region", "us-east-1"))
    data = {}
    try:
        vpcs = ec2.describe_vpcs().get("Vpcs", [])
        subnets = ec2.describe_subnets().get("Subnets", [])
        sgs = ec2.describe_security_groups().get("SecurityGroups", [])
        igws = ec2.describe_internet_gateways().get("InternetGateways", [])
        data.update(
            {
                "vpcs": len(vpcs),
                "subnets": len(subnets),
                "security_groups": len(sgs),
                "internet_gateways": len(igws),
            }
        )
    except Exception as e:
        logger.error(f"Networking discovery failed: {e}")

    logger.info(
        f"[✔] 0.3 Networking — VPCs={data.get('vpcs',0)} "
        f"Subnets={data.get('subnets',0)} SGs={data.get('security_groups',0)}"
    )
    return data


# -----------------------------------------------------------------------------
# 0.4 — Compute
# -----------------------------------------------------------------------------
@phase0_contract
def discover_compute(cfg, logger):
    region = cfg.get("region", "us-east-1")
    ec2 = boto3.client("ec2", region_name=region)
    asg = boto3.client("autoscaling", region_name=region)
    elb = boto3.client("elbv2", region_name=region)
    ecs = boto3.client("ecs", region_name=region)
    lamb = boto3.client("lambda", region_name=region)
    ecr = boto3.client("ecr", region_name=region)
    compute = {}

    try:
        reservations = ec2.describe_instances().get("Reservations", [])
        compute["instances"] = sum(len(r.get("Instances", [])) for r in reservations)
    except Exception:
        compute["instances"] = 0
    try:
        compute["autoscaling_groups"] = len(asg.describe_auto_scaling_groups().get("AutoScalingGroups", []))
    except Exception:
        compute["autoscaling_groups"] = 0
    try:
        compute["load_balancers"] = len(elb.describe_load_balancers().get("LoadBalancers", []))
    except Exception:
        compute["load_balancers"] = 0
    try:
        compute["ecs_clusters"] = len(ecs.list_clusters().get("clusterArns", []))
    except Exception:
        compute["ecs_clusters"] = 0
    try:
        compute["lambda_functions"] = len(lamb.list_functions().get("Functions", []))
    except Exception:
        compute["lambda_functions"] = 0
    try:
        repos = ecr.describe_repositories().get("repositories", [])
        compute["ecr_repositories"] = len(repos)
    except Exception:
        compute["ecr_repositories"] = 0

    logger.info(
        f"[✔] 0.4 Compute — EC2={compute['instances']} ASG={compute['autoscaling_groups']} "
        f"ELB={compute['load_balancers']} ECS={compute['ecs_clusters']} "
        f"Lambda={compute['lambda_functions']} ECR={compute['ecr_repositories']}"
    )
    return compute


# -----------------------------------------------------------------------------
# 0.5 — Storage & Backup
# -----------------------------------------------------------------------------
@phase0_contract
def discover_storage(cfg, logger):
    region = cfg.get("region", "us-east-1")
    s3 = boto3.client("s3")
    rds = boto3.client("rds", region_name=region)
    efs = boto3.client("efs", region_name=region)
    fsx = boto3.client("fsx", region_name=region)
    kms = boto3.client("kms", region_name=region)
    backup = boto3.client("backup", region_name=region)
    ec2 = boto3.client("ec2", region_name=region)
    storage = {}

    try:
        buckets = s3.list_buckets().get("Buckets", [])
        regional = []
        for b in buckets:
            try:
                loc = s3.get_bucket_location(Bucket=b["Name"]).get("LocationConstraint") or "us-east-1"
                if loc == region:
                    regional.append(b["Name"])
            except Exception:
                continue
        storage["s3_buckets"] = len(regional)
    except Exception:
        storage["s3_buckets"] = 0

    try:
        storage["rds_instances"] = len(rds.describe_db_instances().get("DBInstances", []))
    except Exception:
        storage["rds_instances"] = 0
    try:
        storage["efs_filesystems"] = len(efs.describe_file_systems().get("FileSystems", []))
    except Exception:
        storage["efs_filesystems"] = 0
    try:
        storage["fsx_filesystems"] = len(fsx.describe_file_systems().get("FileSystems", []))
    except Exception:
        storage["fsx_filesystems"] = 0
    try:
        storage["kms_keys"] = len(kms.list_keys().get("Keys", []))
    except Exception:
        storage["kms_keys"] = 0
    try:
        storage["backup_vaults"] = len(backup.list_backup_vaults().get("BackupVaultList", []))
    except Exception:
        storage["backup_vaults"] = 0
    try:
        storage["ebs_snapshots"] = len(ec2.describe_snapshots(OwnerIds=["self"]).get("Snapshots", []))
    except Exception:
        storage["ebs_snapshots"] = 0

    logger.info(
        f"[✔] 0.5 Storage — S3={storage['s3_buckets']} RDS={storage['rds_instances']} "
        f"EFS={storage['efs_filesystems']} Snapshots={storage['ebs_snapshots']}"
    )
    return storage
ReadTimeoutError