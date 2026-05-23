#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cfn_exporter.py — Human-friendly, results-aware CloudFormation exporter
=======================================================================

Goal
----
Snapshot a subset of your AWS infrastructure and emit a **single** CloudFormation
template (YAML) you can later **split** into layered stacks and re-deploy in a
fresh account (e.g., before enabling **SCPs**).

What it captures (v0.2)
-----------------------
Network:
  • VPCs, Subnets, Route Tables + Associations
  • Internet Gateways, NAT Gateways (+ first EIP reference), Elastic IPs
Security:
  • Security Groups (ingress/egress), tags preserved
Compute:
  • EC2 Instances (ImageId, InstanceType, KeyName, Subnet/SGs, safe EBS subset, tags)

Out of scope (add later or by hand)
-----------------------------------
  • IAM (Roles/Policies/InstanceProfiles), S3, RDS, ALB/NLB, Route53, ACM,
    Lambda, ASGs/LaunchTemplates, EKS/ECS, etc.
  • AMI portability: we **copy AMI IDs**; consider swapping to **SSM Parameter**
    lookups (`/aws/service/ami-amazon-linux-latest/...`) when redeploying.

Safety
------
  • Read-only: recommend AWS managed policy **ReadOnlyAccess** or a minimal custom policy.
  • The exporter never mutates your infra.

Results directory
-----------------
If you keep the default output filename (`exported_stack.yaml`) with **no path**,
the file will be written to **./results/exported_stack.yaml**.
If you give a path or a directory in `--output`, that exact path is honored.

CLI
---
Required:
  --stack-name NAME              Logical stack name used in the template Description
  --output FILE.yaml|DIR         Output file path OR directory path
                                 • If .yaml/.yml => write to that file
                                 • Else => treat as directory & write exported_stack.yaml inside
                                 • Default when omitted: ./results/exported_stack.yaml

Optional selection/identity:
  --regions R1 R2 ...            Regions to scan (default: current boto3/config region)
  --profile NAME                 AWS CLI profile to use (default: env/config)

S3 mirror (NEW – same as sso_exporter):
  --s3-bucket NAME
  --s3-prefix PREFIX             (e.g., tf-backup/cfn/)
  --s3-region REGION             (default: first --regions or boto3 default)
  --s3-storage-class CLASS       (default: DEEP_ARCHIVE)
  --s3-kms-key-id KEY_OR_ALIAS   (KMS ARN/alias for SSE-KMS)

Misc:
  --dry-run                      Scan and summarize, but do NOT write files or upload to S3
  --verbose                      Extra progress prints

Config file (NEW):
  --config <path.{yaml|yml|json}>
    Provide defaults (stack_name/output/regions/profile/dry_run/verbose and S3 keys).
    CLI overrides config.

Legacy (kept for compatibility; maps to S3 flags):
  --backup-region REGION
  --backup-path   s3://bucket/prefix/
"""

from __future__ import annotations

import argparse
import sys
import time
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

try:
    import yaml  # type: ignore
except Exception:
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

RESULTS_DIR = Path("results")  # used only when user keeps the default filename with no path
DEFAULT_OUTPUT_FILE = "exported_stack.yaml"

# ----- banner -----
SCRIPT_NAME = "CloudFormation Exporter"
SCRIPT_VERSION = "0.4.3"  # fix: let config override s3_prefix/storage_class

S3_STORAGE_CLASS_CHOICES = [
    "STANDARD","STANDARD_IA","ONEZONE_IA","INTELLIGENT_TIERING","GLACIER_IR","GLACIER",
    "DEEP_ARCHIVE","REDUCED_REDUNDANCY","EXPRESS_ONEZONE","OUTPOSTS","SNOW","FSX_OPENZFS"
]

# ---------------- small utils ----------------
def banner() -> None:
    print(f"[START] {SCRIPT_NAME} — v{SCRIPT_VERSION}", file=sys.stderr)

def fatal(msg: str, ctx: Optional[dict] = None) -> None:
    if ctx:
        print(f"[ERR] {msg}\nContext: {json.dumps(ctx)}", file=sys.stderr)
    else:
        print(f"[ERR] {msg}", file=sys.stderr)
    sys.exit(2)

def ensure_results_dir() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

def boto_session(region: Optional[str] = None, profile: Optional[str] = None) -> boto3.session.Session:
    """Return a boto3 session pinned to an optional region/profile."""
    kwargs: Dict[str, Any] = {}
    if profile:
        kwargs["profile_name"] = profile
    return boto3.Session(region_name=region, **kwargs) if region else boto3.Session(**kwargs)

def tag_list_to_dict(tags: Optional[List[Dict[str, str]]]) -> Dict[str, str]:
    d: Dict[str, str] = {}
    if tags:
        for t in tags:
            k = t.get("Key")
            v = t.get("Value")
            if k is not None and v is not None:
                d[k] = v
    return d

def sanitize_logical_id(name: str) -> str:
    """
    Convert noisy names/ids to a CloudFormation-safe Logical ID.
    Rules:
      • keep alphanumerics, split others to spaces
      • TitleCase and concatenate
      • ensure it doesn't start with a digit
    """
    import re
    s = re.sub(r"[^A-Za-z0-9]", " ", name or "")
    parts = [p.capitalize() for p in s.split() if p]
    out = "".join(parts) or f"Res{int(time.time())}"
    if out[0].isdigit():
        out = "R" + out
    return out[:255]

# ---------------- S3 helpers ----------------
def parse_s3_path(s3_uri: str) -> Tuple[str, str]:
    """Parse s3://bucket/optional/prefix -> (bucket, key_prefix)"""
    if not s3_uri.startswith("s3://"):
        raise ValueError("--backup-path must start with s3://")
    no_scheme = s3_uri[5:]
    parts = no_scheme.split("/", 1)
    bucket = parts[0].strip()
    if not bucket:
        raise ValueError("Invalid S3 URI: missing bucket name")
    key_prefix = parts[1].strip() if len(parts) > 1 else ""
    if key_prefix and not key_prefix.endswith("/"):
        key_prefix += "/"
    return bucket, key_prefix

def _kms_region_from_arn(kms_id: Optional[str]) -> Optional[str]:
    if not kms_id:
        return None
    if kms_id.startswith("arn:") and ":kms:" in kms_id:
        parts = kms_id.split(":")
        return parts[3] if len(parts) > 3 else None
    return None  # alias or key-id only

def _s3_client(profile: Optional[str], region: str):
    sess = boto3.Session(region_name=region, **({"profile_name": profile} if profile else {}))
    return sess.client("s3", region_name=region)

def _kms_client(profile: Optional[str], region: str):
    sess = boto3.Session(region_name=region, **({"profile_name": profile} if profile else {}))
    return sess.client("kms", region_name=region)

def _preflight_validate_kms(profile: Optional[str], s3_region: str, kms_key_id: Optional[str]) -> None:
    kms_region = _kms_region_from_arn(kms_key_id)
    if kms_region and kms_region != s3_region:
        fatal("S3/KMS region mismatch for SSE-KMS.",
              {"s3_region": s3_region, "kms_key_region": kms_region,
               "hint": "Use a key/alias in the same region as the S3 bucket."})
    if kms_key_id:
        try:
            kms = _kms_client(profile, s3_region)
            kms.describe_key(KeyId=kms_key_id)  # supports alias and key-id/arn
        except (ClientError, BotoCoreError) as e:
            fatal("KMS key not usable from this region/account (DescribeKey failed).",
                  {"region": s3_region, "key": kms_key_id, "error": str(e)})

def _s3_put_file(s3, bucket: str, key: str, local_path: Path, storage_class: Optional[str],
                 kms_key_id: Optional[str], simulate: bool) -> None:
    if simulate:
        print(f"[SIMULATE] Would upload {local_path} -> s3://{bucket}/{key}")
        return
    extra: Dict[str, Any] = {}
    if storage_class:
        extra["StorageClass"] = storage_class
    if kms_key_id:
        extra["ServerSideEncryption"] = "aws:kms"
        extra["SSEKMSKeyId"] = kms_key_id
    s3.upload_file(str(local_path), bucket, key, ExtraArgs=extra)

def mirror_to_s3(
    profile: Optional[str],
    local_file: Path,
    s3_bucket: Optional[str],
    s3_prefix: Optional[str],
    s3_region: Optional[str],
    s3_storage_class: Optional[str],
    s3_kms_key_id: Optional[str],
    simulate: bool,
) -> None:
    if not s3_bucket:
        return
    region = s3_region or (boto3.Session(profile_name=profile).region_name or "us-east-1")
    _preflight_validate_kms(profile, region, s3_kms_key_id)
    s3 = _s3_client(profile, region)
    prefix = (s3_prefix or "").strip("/")
    if prefix:
        prefix += "/"
    key = f"{prefix}{local_file.name}"
    try:
        _s3_put_file(
            s3,
            bucket=s3_bucket,
            key=key,
            local_path=local_file,
            storage_class=s3_storage_class,
            kms_key_id=s3_kms_key_id,
            simulate=simulate,
        )
        print(f"[S3] Uploaded {local_file} -> s3://{s3_bucket}/{key}")
    except (ClientError, BotoCoreError) as e:
        fatal("Failed to upload CloudFormation output to S3.",
              {"file": str(local_file), "bucket": s3_bucket, "key": key, "error": str(e)})

# ---------------- Output path resolver ----------------
def resolve_output_path(output_arg: str) -> Path:
    """
    Rules:
      • If output ends with .yaml/.yml => use exactly that file path
      • Else => treat as directory, write DEFAULT_OUTPUT_FILE inside
      • Special case: if output is the default filename with no path,
        write to ./results/DEFAULT_OUTPUT_FILE
    """
    p = Path(output_arg).expanduser()
    if output_arg == DEFAULT_OUTPUT_FILE and p.parent == Path(".."):
        ensure_results_dir()
        out = (RESULTS_DIR / DEFAULT_OUTPUT_FILE).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        return out
    if p.suffix.lower() in (".yaml", ".yml"):
        out = p.resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        return out
    else:
        out_dir = p.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / DEFAULT_OUTPUT_FILE

# ---------------- Config helpers ----------------
def _load_config_file(path: str) -> dict:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        fatal("Config file not found", {"path": str(cfg_path)})
    text = cfg_path.read_text(encoding="utf-8")
    if cfg_path.suffix.lower() in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(text) or {}
        except Exception as e:
            fatal("Failed to parse YAML config", {"error": str(e)})
    else:
        try:
            data = json.loads(text or "{}")
        except Exception as e:
            fatal("Failed to parse JSON config", {"error": str(e)})
    if not isinstance(data, dict):
        fatal("Config top-level must be a mapping/object", {"path": str(cfg_path)})
    return data

def _normalize_regions(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val).strip()
    if not s:
        return []
    if "," in s:
        return [t.strip() for t in s.split(",") if t.strip()]
    if " " in s:
        return [t.strip() for t in s.split() if t.strip()]
    return [s]

def _merge_cli_with_config(args: argparse.Namespace, cfg: dict) -> argparse.Namespace:
    """
    Fill missing CLI values from config. CLI always wins.
    Supported config keys:
      stack_name, output, regions, profile, dry_run, verbose,
      s3_bucket, s3_prefix, s3_region, s3_storage_class, s3_kms_key_id
    """
    mapping = {
        "stack_name": "stack_name",
        "output": "output",
        "regions": "regions",
        "profile": "profile",
        "dry_run": "dry_run",
        "verbose": "verbose",
        # S3
        "s3_bucket": "s3_bucket",
        "s3_prefix": "s3_prefix",
        "s3_region": "s3_region",
        "s3_storage_class": "s3_storage_class",
        "s3_kms_key_id": "s3_kms_key_id",
    }
    for ck, attr in mapping.items():
        cur = getattr(args, attr, None)
        if (cur is None or
            (isinstance(cur, str) and cur == "") or
            (isinstance(cur, bool) and cur is False) or
            (isinstance(cur, list) and not cur)):
            if ck in cfg and cfg[ck] is not None:
                setattr(args, attr, cfg[ck])

    # normalize types
    args.regions = _normalize_regions(getattr(args, "regions", None))
    for b in ("dry_run", "verbose"):
        v = getattr(args, b, None)
        if isinstance(v, str):
            setattr(args, b, v.strip().lower() in ("1", "true", "yes", "y", "on"))

    # normalize/validate storage class
    sc = getattr(args, "s3_storage_class", None)
    if sc:
        scu = str(sc).upper().strip()
        if scu not in S3_STORAGE_CLASS_CHOICES:
            fatal("Invalid s3_storage_class in config/CLI",
                  {"value": scu, "allowed": S3_STORAGE_CLASS_CHOICES})
        args.s3_storage_class = scu

    # post-merge requireds
    missing = []
    if not getattr(args, "stack_name", None):
        missing.append("--stack-name (or config.stack_name)")
    if not getattr(args, "output", None):
        missing.append("--output (or config.output)")
    if not getattr(args, "regions", None):
        missing.append("--regions (or config.regions)")
    if missing:
        fatal("Missing required arguments after applying --config", {"missing": missing})

    return args

# ---------------- Template builder ----------------
class CFNTemplate:
    """Minimal CFN template builder with de-duplication of logical IDs."""
    def __init__(self, stack_name: str):
        self.template: Dict[str, Any] = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": f"Exported stack {stack_name} (best-effort)",
            "Parameters": {},
            "Mappings": {},
            "Resources": {},
            "Outputs": {},
        }
        self.logical_ids: set[str] = set()
    def add_resource(self, logical_id: str, res_type: str, properties: Dict[str, Any]) -> str:
        if logical_id in self.logical_ids:
            i = 2
            base = logical_id
            while logical_id in self.logical_ids:
                logical_id = f"{base}{i}"
                i += 1
        self.logical_ids.add(logical_id)
        self.template["Resources"][logical_id] = {"Type": res_type, "Properties": properties}
        return logical_id
    def yaml(self) -> str:
        return yaml.safe_dump(self.template, sort_keys=False)

# ------------- Exporters -------------
def export_vpcs(ec2, tmpl: CFNTemplate, region: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    vpcs = ec2.describe_vpcs().get("Vpcs", [])
    vpc_id_to_logical: Dict[str, str] = {}
    vpc_meta: Dict[str, Any] = {}
    for v in vpcs:
        vpc_id = v["VpcId"]
        cidr = v.get("CidrBlock")
        tags = tag_list_to_dict(v.get("Tags"))
        lid = sanitize_logical_id(tags.get("Name", vpc_id) + "Vpc")
        props: Dict[str, Any] = {"CidrBlock": cidr}
        if tags:
            props["Tags"] = [{"Key": k, "Value": val} for k, val in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::VPC", props)
        vpc_id_to_logical[vpc_id] = lid
        vpc_meta[vpc_id] = v
    return vpc_id_to_logical, vpc_meta

def export_igws(ec2, tmpl: CFNTemplate, vpc_id_to_logical: Dict[str, str]) -> Dict[str, str]:
    igws = ec2.describe_internet_gateways().get("InternetGateways", [])
    igw_id_to_logical: Dict[str, str] = {}
    for igw in igws:
        tags = tag_list_to_dict(igw.get("Tags"))
        igw_id = igw["InternetGatewayId"]
        lid = sanitize_logical_id(tags.get("Name", igw_id) + "Igw")
        props: Dict[str, Any] = {}
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::InternetGateway", props)
        igw_id_to_logical[igw_id] = lid
        for att in igw.get("Attachments", []):
            if att.get("State") == "available":
                vpc_id = att.get("VpcId")
                if vpc_id in vpc_id_to_logical:
                    attach_id = sanitize_logical_id(lid + "Attach" + vpc_id_to_logical[vpc_id])
                    tmpl.add_resource(
                        attach_id, "AWS::EC2::VPCGatewayAttachment",
                        {"VpcId": {"Ref": vpc_id_to_logical[vpc_id]}, "InternetGatewayId": {"Ref": lid}},
                    )
    return igw_id_to_logical

def export_subnets(ec2, tmpl: CFNTemplate, vpc_id_to_logical: Dict[str, str]) -> Dict[str, str]:
    subnets = ec2.describe_subnets().get("Subnets", [])
    subnet_id_to_logical: Dict[str, str] = {}
    for s in subnets:
        sid = s["SubnetId"]
        cidr = s.get("CidrBlock")
        az = s.get("AvailabilityZone")
        vpc_id = s.get("VpcId")
        tags = tag_list_to_dict(s.get("Tags"))
        lid = sanitize_logical_id(tags.get("Name", sid) + "Subnet")
        props: Dict[str, Any] = {"CidrBlock": cidr, "VpcId": {"Ref": vpc_id_to_logical[vpc_id]}}
        if az:
            props["AvailabilityZone"] = az
        if s.get("MapPublicIpOnLaunch") is not None:
            props["MapPublicIpOnLaunch"] = s["MapPublicIpOnLaunch"]
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::Subnet", props)
        subnet_id_to_logical[sid] = lid
    return subnet_id_to_logical

def export_eips(ec2, tmpl: CFNTemplate) -> Dict[str, str]:
    eips = ec2.describe_addresses().get("Addresses", [])
    eip_id_to_logical: Dict[str, str] = {}
    for e in eips:
        alloc_id = e.get("AllocationId")
        if not alloc_id:
            continue
        tags = tag_list_to_dict(e.get("Tags"))
        lid = sanitize_logical_id(tags.get("Name", alloc_id) + "Eip")
        props: Dict[str, Any] = {"Domain": "vpc"}
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::EIP", props)
        eip_id_to_logical[alloc_id] = lid
    return eip_id_to_logical

def export_nat_gateways(ec2, tmpl: CFNTemplate, subnet_id_to_logical: Dict[str, str],
                        eip_id_to_logical: Dict[str, str]) -> Dict[str, str]:
    ngws = ec2.describe_nat_gateways().get("NatGateways", [])
    nat_id_to_logical: Dict[str, str] = {}
    for n in ngws:
        ngw_id = n["NatGatewayId"]
        subnet_id = n["SubnetId"]
        tags = tag_list_to_dict(n.get("Tags"))
        lid = sanitize_logical_id(tags.get("Name", ngw_id) + "NatGw")
        alloc_ids = [a.get("AllocationId") for a in n.get("NatGatewayAddresses", []) if a.get("AllocationId")]
        props: Dict[str, Any] = {"SubnetId": {"Ref": subnet_id_to_logical[subnet_id]}}
        if alloc_ids:
            a = alloc_ids[0]
            if a in eip_id_to_logical:
                props["AllocationId"] = {"Fn::GetAtt": [eip_id_to_logical[a], "AllocationId"]}
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        tmpl.add_resource(lid, "AWS::EC2::NatGateway", props)
        nat_id_to_logical[ngw_id] = lid
    return nat_id_to_logical

def export_route_tables(ec2, tmpl: CFNTemplate, vpc_id_to_logical: Dict[str, str],
                        subnet_id_to_logical: Dict[str, str], igw_id_to_logical: Dict[str, str],
                        nat_id_to_logical: Dict[str, str]) -> Dict[str, str]:
    rts = ec2.describe_route_tables().get("RouteTables", [])
    rt_id_to_logical: Dict[str, str] = {}
    for rt in rts:
        rtid = rt["RouteTableId"]
        vpc_id = rt.get("VpcId")
        tags = tag_list_to_dict(rt.get("Tags"))
        lid = sanitize_logical_id(tags.get("Name", rtid) + "Rt")
        props: Dict[str, Any] = {"VpcId": {"Ref": vpc_id_to_logical[vpc_id]}}
        routes: List[Dict[str, Any]] = []
        for r in rt.get("Routes", []):
            route: Dict[str, Any] = {}
            if "DestinationCidrBlock" in r:
                route["DestinationCidrBlock"] = r["DestinationCidrBlock"]
            if "GatewayId" in r and str(r["GatewayId"]).startswith("igw-"):
                igw = r["GatewayId"]
                if igw in igw_id_to_logical:
                    route["GatewayId"] = {"Ref": igw_id_to_logical[igw]}
            if "NatGatewayId" in r:
                nat = r["NatGatewayId"]
                if nat in nat_id_to_logical:
                    route["NatGatewayId"] = {"Ref": nat_id_to_logical[nat]}
            if route:
                routes.append(route)
        if routes:
            props["Routes"] = routes
        tmpl.add_resource(lid, "AWS::EC2::RouteTable", props)
        rt_id_to_logical[rtid] = lid
        for assoc in rt.get("Associations", []):
            if assoc.get("Main"):
                continue
            subnet_id = assoc.get("SubnetId")
            if subnet_id in subnet_id_to_logical:
                assoc_id = sanitize_logical_id(lid + "Assoc" + subnet_id_to_logical[subnet_id])
                tmpl.add_resource(
                    assoc_id, "AWS::EC2::SubnetRouteTableAssociation",
                    {"RouteTableId": {"Ref": lid}, "SubnetId": {"Ref": subnet_id_to_logical[subnet_id]}},
                )
    return rt_id_to_logical

def export_security_groups(ec2, tmpl: CFNTemplate, vpc_id_to_logical: Dict[str, str]) -> Dict[str, str]:
    sgs = ec2.describe_security_groups().get("SecurityGroups", [])
    sg_id_to_logical: Dict[str, str] = {}
    for sg in sgs:
        sgid = sg["GroupId"]
        vpc_id = sg.get("VpcId")
        name = sg.get("GroupName", sgid)
        desc = sg.get("Description", f"Exported {name}")
        tags = tag_list_to_dict(sg.get("Tags"))
        lid = sanitize_logical_id(tags.get("Name", name) + "Sg")
        def perms_to_rules(perms: List[Dict[str, Any]], is_egress: bool = False) -> List[Dict[str, Any]]:
            rules: List[Dict[str, Any]] = []
            for ip in perms:
                rule: Dict[str, Any] = {"IpProtocol": ip.get("IpProtocol", "-1")}
                if "FromPort" in ip:
                    rule["FromPort"] = ip["FromPort"]
                if "ToPort" in ip:
                    rule["ToPort"] = ip["ToPort"]
                cidrs = [{"CidrIp": c["CidrIp"]} for c in ip.get("IpRanges", []) if "CidrIp" in c]
                cidrsv6 = [{"CidrIpv6": c["CidrIpv6"]} for c in ip.get("Ipv6Ranges", []) if "CidrIpv6" in c]
                pairs_key = "UserIdGroupPairs"
                pairs = [p for p in ip.get(pairs_key, []) if "GroupId" in p]
                if cidrs:
                    rule["CidrIp"] = cidrs[0]["CidrIp"] if len(cidrs) == 1 else None
                if cidrsv6:
                    rule["CidrIpv6"] = cidrsv6[0]["CidrIpv6"] if len(cidrsv6) == 1 else None
                if pairs:
                    key = "DestinationSecurityGroupId" if is_egress else "SourceSecurityGroupId"
                    rule[key] = pairs[0]["GroupId"] if len(pairs) == 1 else None
                if len(cidrs) > 1:
                    rule["IpRanges"] = cidrs
                if len(cidrsv6) > 1:
                    rule["Ipv6Ranges"] = cidrsv6
                if len(pairs) > 1:
                    rule[pairs_key] = [{"GroupId": p["GroupId"]} for p in pairs]
                rules.append(rule)
            return rules
        ingress = perms_to_rules(sg.get("IpPermissions", []), is_egress=False)
        egress = perms_to_rules(sg.get("IpPermissionsEgress", []), is_egress=True)
        props: Dict[str, Any] = {"GroupDescription": desc, "VpcId": {"Ref": vpc_id_to_logical[vpc_id]}}
        if tags:
            props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
        if name:
            props["GroupName"] = name
        if ingress:
            props["SecurityGroupIngress"] = ingress
        if egress:
            props["SecurityGroupEgress"] = egress
        tmpl.add_resource(lid, "AWS::EC2::SecurityGroup", props)
        sg_id_to_logical[sgid] = lid
    return sg_id_to_logical

def export_instances(ec2, tmpl: CFNTemplate, subnet_id_to_logical: Dict[str, str],
                     sg_id_to_logical: Dict[str, str]) -> None:
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                iid = inst["InstanceId"]
                tags = tag_list_to_dict(inst.get("Tags"))
                name = tags.get("Name", iid)
                lid = sanitize_logical_id(name + "Ec2")
                props: Dict[str, Any] = {
                    "ImageId": inst.get("ImageId"),
                    "InstanceType": inst.get("InstanceType"),
                }
                if inst.get("KeyName"):
                    props["KeyName"] = inst["KeyName"]
                if inst.get("IamInstanceProfile"):
                    props["IamInstanceProfile"] = inst["IamInstanceProfile"].get("Arn")
                sgs: List[Any] = []
                for sg in inst.get("SecurityGroups", []):
                    sgid = sg.get("GroupId")
                    sgs.append({"Ref": sg_id_to_logical[sgid]} if sgid in sg_id_to_logical else sgid)
                if sgs:
                    props["SecurityGroupIds"] = sgs
                if inst.get("SubnetId") and inst["SubnetId"] in subnet_id_to_logical:
                    props["SubnetId"] = {"Ref": subnet_id_to_logical[inst["SubnetId"]]}
                if inst.get("BlockDeviceMappings"):
                    bdm: List[Dict[str, Any]] = []
                    for m in inst["BlockDeviceMappings"]:
                        entry: Dict[str, Any] = {"DeviceName": m.get("DeviceName")}
                        ebs = m.get("Ebs")
                        if ebs:
                            e: Dict[str, Any] = {"DeleteOnTermination": ebs.get("DeleteOnTermination", True)}
                            if ebs.get("VolumeSize"):
                                e["VolumeSize"] = int(ebs["VolumeSize"])
                            if ebs.get("VolumeType"):
                                e["VolumeType"] = ebs["VolumeType"]
                            if ebs.get("Encrypted") is not None:
                                e["Encrypted"] = ebs["Encrypted"]
                            if ebs.get("KmsKeyId"):
                                e["KmsKeyId"] = ebs["KmsKeyId"]
                            entry["Ebs"] = e
                        bdm.append(entry)
                    if bdm:
                        props["BlockDeviceMappings"] = bdm
                if tags:
                    props["Tags"] = [{"Key": k, "Value": v} for k, v in tags.items()]
                tmpl.add_resource(lid, "AWS::EC2::Instance", props)

# ---------------- run/orchestration ----------------
def run(
    stack_name: str,
    output_path: Path,
    regions: List[str],
    profile: Optional[str],
    dry_run: bool,
    verbose: bool,
    s3_bucket: Optional[str],
    s3_prefix: Optional[str],
    s3_region: Optional[str],
    s3_storage_class: Optional[str],
    s3_kms_key_id: Optional[str],
) -> None:

    master_template = CFNTemplate(stack_name)
    total_counts = {"vpc": 0, "igw": 0, "subnet": 0, "eip": 0, "nat": 0, "rt": 0, "sg": 0, "ec2": 0}

    for region in regions:
        if verbose:
            print(f"[INFO] Scanning region: {region}")
        try:
            session = boto_session(region=region, profile=profile)
            ec2 = session.client("ec2", config=Config(retries={"max_attempts": 10, "mode": "standard"}))
            vpc_id_to_logical, _ = export_vpcs(ec2, master_template, region); total_counts["vpc"] += len(vpc_id_to_logical)
            igw_id_to_logical = export_igws(ec2, master_template, vpc_id_to_logical); total_counts["igw"] += len(igw_id_to_logical)
            subnet_id_to_logical = export_subnets(ec2, master_template, vpc_id_to_logical); total_counts["subnet"] += len(subnet_id_to_logical)
            eip_id_to_logical = export_eips(ec2, master_template); total_counts["eip"] += len(eip_id_to_logical)
            nat_id_to_logical = export_nat_gateways(ec2, master_template, subnet_id_to_logical, eip_id_to_logical); total_counts["nat"] += len(nat_id_to_logical)
            rt_id_to_logical = export_route_tables(ec2, master_template, vpc_id_to_logical, subnet_id_to_logical, igw_id_to_logical, nat_id_to_logical); total_counts["rt"] += len(rt_id_to_logical)
            sg_id_to_logical = export_security_groups(ec2, master_template, vpc_id_to_logical); total_counts["sg"] += len(sg_id_to_logical)
            pre_count = len(master_template.template["Resources"])
            export_instances(ec2, master_template, subnet_id_to_logical, sg_id_to_logical)
            post_count = len(master_template.template["Resources"])
            total_counts["ec2"] += max(0, post_count - pre_count)
        except (ClientError, BotoCoreError) as e:
            fatal("AWS error while scanning region", {"region": region, "error": str(e)})

    if dry_run:
        print("[DRY-RUN] Export summary (nothing written):")
        for k in ["vpc", "igw", "subnet", "eip", "nat", "rt", "sg", "ec2"]:
            print(f"  - {k:6s}: {total_counts[k]}")
        return

    # Write YAML
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(master_template.yaml())
        print(f"[OK] Wrote CloudFormation template to {output_path}")
    except Exception as e:
        fatal("Failed to write output file", {"path": str(output_path), "error": str(e)})

    # Optional S3 mirror (single file)
    if s3_bucket:
        # resolve S3 region if still unset
        if not s3_region:
            s3_region = regions[0] if regions else (boto3.Session(profile_name=profile).region_name or "us-east-1")
        mirror_to_s3(
            profile=profile,
            local_file=output_path,
            s3_bucket=s3_bucket,
            s3_prefix=s3_prefix,
            s3_region=s3_region,
            s3_storage_class=s3_storage_class,
            s3_kms_key_id=s3_kms_key_id,
            simulate=dry_run,
        )
        print("[OK] S3 mirror completed.")

# ---------------- argparse ----------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Export AWS infra to CloudFormation YAML (results-aware)")

    # Config support
    p.add_argument("--config", default=None, help="YAML/JSON file with defaults; CLI overrides the file values")

    # Core
    p.add_argument("--stack-name", required=False, help="Logical stack name for the exported template")
    p.add_argument("--output", default=DEFAULT_OUTPUT_FILE,
                   help="Output FILE (.yaml/.yml) or DIR. If DIR, exporter writes exported_stack.yaml inside. "
                        "Default when omitted: ./results/exported_stack.yaml")
    p.add_argument("--regions", nargs="*", default=[], help="Regions to scan; default: current boto3 config region")
    p.add_argument("--profile", default=None, help="AWS profile to use for all calls (default: env/config)")

    # NEW: S3 mirror (defaults are None so config can override)
    p.add_argument("--s3-bucket", dest="s3_bucket", default=None, help="Destination S3 bucket to mirror the exported file.")
    p.add_argument("--s3-prefix", dest="s3_prefix", default=None, help="Key prefix inside the destination bucket.")
    p.add_argument("--s3-region", dest="s3_region", default=None, help="S3 client region (default: first --regions or boto3 default).")
    p.add_argument("--s3-storage-class", dest="s3_storage_class", default=None,
                   choices=S3_STORAGE_CLASS_CHOICES, help="S3 storage class for mirrored object.")
    p.add_argument("--s3-kms-key-id", dest="s3_kms_key_id", default=None, help="KMS key ARN/alias in the destination account for SSE-KMS.")

    # Legacy (mapped to S3 flags)
    p.add_argument("--backup-region", required=False, help="(Deprecated) Use --s3-region instead")
    p.add_argument("--backup-path", required=False, help="(Deprecated) Use --s3-bucket/--s3-prefix instead (s3://bucket/prefix/)")

    # QoL
    p.add_argument("--dry-run", action="store_true", help="Scan and summarize, but do NOT write or upload the YAML")
    p.add_argument("--verbose", action="store_true", help="Extra progress prints")

    return p.parse_args(argv)

# ---------------- main ----------------
if __name__ == "__main__":
    banner()
    args = parse_args()

    # Load and merge config (CLI wins)
    if args.config:
        cfg = _load_config_file(args.config)
        args = _merge_cli_with_config(args, cfg)
    else:
        args.regions = _normalize_regions(args.regions)
        missing = []
        if not args.stack_name:
            missing.append("--stack-name")
        if not args.output:
            missing.append("--output")
        if missing:
            fatal("Missing required arguments", {"missing": missing})

    # Map legacy backup flags to new S3 flags if user provided them and s3_* not set
    if args.backup_path and not args.s3_bucket:
        try:
            b, pfx = parse_s3_path(args.backup_path)
        except Exception as e:
            fatal("Invalid --backup-path", {"value": args.backup_path, "error": str(e)})
        args.s3_bucket = b
        args.s3_prefix = pfx
    if args.backup_region and not args.s3_region:
        args.s3_region = args.backup_region

    # Apply fallbacks ONLY if still unset after merge (so config wins)
    if args.s3_prefix is None:
        args.s3_prefix = "tf-backup/cfn/"
    if args.s3_storage_class is None:
        args.s3_storage_class = "DEEP_ARCHIVE"

    # Resolve output path
    output_path = resolve_output_path(args.output)

    # Regions fallback
    regions = args.regions or [boto3.Session(profile_name=args.profile).region_name or "us-east-1"]

    # Informational print (effective S3 settings)
    if args.s3_bucket:
        s3r = args.s3_region or (regions[0] if regions else "us-east-1")
        print(f"[INFO] S3 mirror enabled: s3://{args.s3_bucket}/{(args.s3_prefix or '').lstrip('/')}"
              f"  Region={s3r}  StorageClass={args.s3_storage_class}"
              f"  KMS={'(SSE-S3 default)' if not args.s3_kms_key_id else args.s3_kms_key_id}")

    run(
        stack_name=args.stack_name,
        output_path=output_path,
        regions=regions,
        profile=args.profile,
        dry_run=args.dry_run,
        verbose=args.verbose,
        s3_bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        s3_region=args.s3_region,
        s3_storage_class=args.s3_storage_class,
        s3_kms_key_id=args.s3_kms_key_id,
    )
