#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cfn_splitter.py — Split a monolithic CloudFormation template into layered files,
optionally apply DR-safe transforms for a destination region, and back up splits to S3.

USAGE
=====
Basic (local only):
  python cfn_splitter.py ./results/exported_stack.yaml --output ./cloudformation/production

Read from stdin:
  cat ./results/exported_stack.yaml | python cfn_splitter.py - --output ./cloudformation/production

Region-aware output (writes into <output>/<dest-region>/):
  python cfn_splitter.py ./results/exported_stack.yaml \
      --output ./cloudformation/production \
      --dest-region us-east-1

Include source region (for metadata/logging; required by orchestrator):
  python cfn_splitter.py ./results/exported_stack.yaml \
      --output ./cloudformation/production \
      --region us-east-2 \
      --dest-region us-east-1

Local + S3 backup (NEW mirror flags aligned with sso_exporter):
  python cfn_splitter.py ./results/exported_stack.yaml \
      --output ./cloudformation/production \
      --dest-region us-east-1 \
      --s3-bucket 212533511020-tf-iaac \
      --s3-region us-east-1 \
      --s3-prefix cfn-splits/production/ \
      --s3-storage-class DEEP_ARCHIVE \
      --s3-kms-key-id arn:aws:kms:us-east-1:212533511020:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

Back-compat (still works): --backup-region + --backup-path s3://bucket/prefix/

Plan only (no files written, no S3 upload):
  python cfn_splitter.py ./results/exported_stack.yaml \
      --output ./cloudformation/production \
      --dest-region us-east-1 \
      --dry-run
"""

from __future__ import annotations

import argparse
import sys
import mimetypes
import json
from pathlib import Path
from typing import Dict, Any, Optional, Union, TextIO, Tuple, List
from copy import deepcopy

try:
    import yaml  # type: ignore
except Exception:
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# boto3 is optional unless S3 backup flags are provided
try:
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except Exception:
    boto3 = None  # type: ignore

# -------- Defaults --------
RESULTS_DIR = Path("results")  # used only if no input provided
DEFAULT_INPUT = RESULTS_DIR / "exported_stack.yaml"

CATEGORY_FILES = {
    "network": "network.yaml",
    "security": "security.yaml",
    "compute": "compute.yaml",
    "edge": "edge.yaml",
    "iam": "iam.yaml",
    "data": "data.yaml",
    "observability": "observability.yaml",
    "others": "others.yaml",
}

TYPE_TO_CATEGORY = {
    # Network
    "AWS::EC2::VPC": "network",
    "AWS::EC2::Subnet": "network",
    "AWS::EC2::RouteTable": "network",
    "AWS::EC2::SubnetRouteTableAssociation": "network",
    "AWS::EC2::Route": "network",
    "AWS::EC2::InternetGateway": "network",
    "AWS::EC2::VPCGatewayAttachment": "network",
    "AWS::EC2::NatGateway": "network",
    "AWS::EC2::EIP": "network",
    "AWS::EC2::VPCEndpoint": "network",
    "AWS::EC2::CarrierGateway": "network",
    "AWS::EC2::LocalGatewayRouteTableVPCAssociation": "network",
    "AWS::EC2::TransitGateway": "network",
    "AWS::EC2::TransitGatewayAttachment": "network",

    # Security
    "AWS::EC2::SecurityGroup": "security",
    "AWS::EC2::NetworkAcl": "security",
    "AWS::EC2::NetworkAclEntry": "security",
    "AWS::EC2::SubnetNetworkAclAssociation": "security",

    # Compute
    "AWS::EC2::Instance": "compute",
    "AWS::EC2::LaunchTemplate": "compute",
    "AWS::AutoScaling::AutoScalingGroup": "compute",
    "AWS::AutoScaling::LaunchConfiguration": "compute",
    "AWS::ElasticLoadBalancingV2::TargetGroup": "compute",

    # Edge
    "AWS::ElasticLoadBalancingV2::LoadBalancer": "edge",
    "AWS::ElasticLoadBalancingV2::Listener": "edge",
    "AWS::ElasticLoadBalancingV2::ListenerRule": "edge",
    "AWS::ElasticLoadBalancing::LoadBalancer": "edge",
    "AWS::CloudFront::Distribution": "edge",
    "AWS::Route53::HostedZone": "edge",
    "AWS::Route53::RecordSet": "edge",
    "AWS::Route53::RecordSetGroup": "edge",
    "AWS::CertificateManager::Certificate": "edge",

    # IAM
    "AWS::IAM::Role": "iam",
    "AWS::IAM::Policy": "iam",
    "AWS::IAM::ManagedPolicy": "iam",
    "AWS::IAM::InstanceProfile": "iam",

    # Data
    "AWS::RDS::DBInstance": "data",
    "AWS::RDS::DBSubnetGroup": "data",
    "AWS::RDS::DBCluster": "data",
    "AWS::ElastiCache::CacheCluster": "data",
    "AWS::ElastiCache::SubnetGroup": "data",
    "AWS::OpenSearchService::Domain": "data",
    "AWS::EFS::FileSystem": "data",
    "AWS::EFS::MountTarget": "data",
    "AWS::S3::Bucket": "data",

    # Observability
    "AWS::CloudWatch::Alarm": "observability",
    "AWS::Logs::LogGroup": "observability",
    "AWS::Logs::SubscriptionFilter": "observability",
    "AWS::Events::Rule": "observability",
    "AWS::CloudTrail::Trail": "observability",
    "AWS::Config::ConfigurationRecorder": "observability",
    "AWS::Config::DeliveryChannel": "observability",
    "AWS::Config::ConfigurationAggregator": "observability",
    "AWS::GuardDuty::Detector": "observability",
    "AWS::SecurityHub::Hub": "observability",
}

# -----------------------
# YAML helpers
# -----------------------
def blank_template(description: str) -> Dict[str, Any]:
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": description,
        "Parameters": {},
        "Mappings": {},
        "Resources": {},
        "Outputs": {},
    }

def _safe_yaml_load(fp: Union[Path, TextIO]) -> Dict[str, Any]:
    if isinstance(fp, Path):
        with fp.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    else:
        return yaml.safe_load(fp) or {}

def load_template(input_spec: Union[Path, str]) -> Dict[str, Any]:
    if isinstance(input_spec, str):
        if input_spec == "-":
            data = _safe_yaml_load(sys.stdin)
        else:
            data = _safe_yaml_load(Path(input_spec))
    else:
        data = _safe_yaml_load(input_spec)
    if "Resources" not in data or data["Resources"] is None:
        data["Resources"] = {}
    return data

# -----------------------
# DR pre-processor (routes for public subnets)
# -----------------------
def _tags_to_dict(tags: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if isinstance(tags, list):
        for t in tags:
            k = str(t.get("Key", "")).strip()
            v = str(t.get("Value", "")).strip()
            if k:
                out[k] = v
    elif isinstance(tags, dict):
        for k, v in tags.items():
            out[str(k)] = str(v)
    return out

def _looks_public_subnet(logical_id: str, subnet_res: Dict[str, Any]) -> bool:
    props = subnet_res.get("Properties", {}) or {}
    tags = _tags_to_dict(props.get("Tags", []))
    public_tag = str(tags.get("Public", "")).lower() in ("true", "yes", "1")
    name_tag_public = "public" in str(tags.get("Name", "")).lower()
    id_public = "public" in logical_id.lower()
    return bool(public_tag or name_tag_public or id_public)

def _collect_associations(resources: Dict[str, Any]) -> Dict[str, List[str]]:
    rt_to_subnets: Dict[str, List[str]] = {}
    for lid, res in resources.items():
        if res.get("Type") != "AWS::EC2::SubnetRouteTableAssociation":
            continue
        props = res.get("Properties", {}) or {}
        rt = props.get("RouteTableId")
        sn = props.get("SubnetId")
        if isinstance(rt, dict) and "Ref" in rt:
            rt_ref = rt["Ref"]
        else:
            continue
        if isinstance(sn, dict) and "Ref" in sn:
            sn_ref = sn["Ref"]
        else:
            continue
        rt_to_subnets.setdefault(rt_ref, []).append(sn_ref)
    return rt_to_subnets

def _has_igw_default_route(resources: Dict[str, Any], route_table_id: str) -> bool:
    for _, res in resources.items():
        if res.get("Type") != "AWS::EC2::Route":
            continue
        props = res.get("Properties", {}) or {}
        rtid = props.get("RouteTableId", {})
        if not (isinstance(rtid, dict) and rtid.get("Ref") == route_table_id):
            continue
        if props.get("DestinationCidrBlock") != "0.0.0.0/0":
            continue
        gw = props.get("GatewayId", {})
        if isinstance(gw, dict) and "Ref" in gw:
            return True
    return False

def _find_an_igw(resources: Dict[str, Any]) -> Optional[str]:
    for lid, res in resources.items():
        if res.get("Type") == "AWS::EC2::InternetGateway":
            return lid
    return None

def _ensure_default_route_for_public_subnets(template: Dict[str, Any], dest_region: str, dry_run: bool = False) -> Dict[str, Any]:
    resources: Dict[str, Any] = template.get("Resources", {}) or {}
    subnets = {lid: r for lid, r in resources.items() if r.get("Type") == "AWS::EC2::Subnet"}
    route_tables = {lid: r for lid, r in resources.items() if r.get("Type") == "AWS::EC2::RouteTable"}
    assoc = _collect_associations(resources)
    igw_id = _find_an_igw(resources)

    summary = {
        "transform": "public_subnet_default_routes",
        "dest_region": dest_region,
        "added": [],
        "skipped_no_igw": False,
        "notes": [],
    }

    if not route_tables or not subnets:
        summary["notes"].append("No subnets or route tables present; nothing to do.")
        return summary

    if not igw_id:
        summary["skipped_no_igw"] = True
        summary["notes"].append("No InternetGateway found; skipping route additions.")
        return summary

    for rt_id, subnet_ids in assoc.items():
        if rt_id not in route_tables:
            continue
        public_subnets_here: List[str] = []
        for sn_id in subnet_ids:
            sn_res = subnets.get(sn_id)
            if not sn_res:
                continue
            if _looks_public_subnet(sn_id, sn_res):
                public_subnets_here.append(sn_id)
        if not public_subnets_here:
            continue
        if _has_igw_default_route(resources, rt_id):
            continue

        new_lid = f"{rt_id}DefaultIgwRoute"
        idx = 1
        while new_lid in resources:
            idx += 1
            new_lid = f"{rt_id}DefaultIgwRoute{idx}"

        route_res = {
            "Type": "AWS::EC2::Route",
            "Properties": {
                "RouteTableId": {"Ref": rt_id},
                "DestinationCidrBlock": "0.0.0.0/0",
                "GatewayId": {"Ref": igw_id}
            },
            "Metadata": {
                "cfn_splitter/dr_note": f"Added for DR ({dest_region}) to ensure internet access for public subnets: {public_subnets_here}"
            }
        }
        if not dry_run:
            template["Resources"][new_lid] = route_res
        summary["added"].append({"logical_id": new_lid, "route_table": rt_id, "subnets": public_subnets_here, "igw": igw_id})

    if not summary["added"]:
        summary["notes"].append("No new routes required; all public RTs already had 0.0.0.0/0 via IGW or no public subnets detected.")
    return summary

def apply_dr_transforms_if_requested(template: Dict[str, Any], dest_region: Optional[str], dry_run: bool = False) -> Dict[str, Any]:
    results: Dict[str, Any] = {"applied": False, "steps": []}
    if not dest_region:
        return results
    results["applied"] = True
    step = _ensure_default_route_for_public_subnets(template, dest_region, dry_run=dry_run)
    results["steps"].append(step)
    return results

# -----------------------
# Split helpers
# -----------------------
def categorize_resources(resources: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {k: {} for k in CATEGORY_FILES.keys()}
    for logical_id, res in resources.items():
        rtype = (res.get("Type") or "").strip()
        cat = TYPE_TO_CATEGORY.get(rtype, "others")
        buckets[cat][logical_id] = res
    return buckets

def write_buckets(buckets: Dict[str, Dict[str, Any]], outdir: Path, dry_run: bool = False) -> None:
    if dry_run:
        return
    outdir.mkdir(parents=True, exist_ok=True)
    for cat, resmap in buckets.items():
        tpl = blank_template(f"Layer: {cat}")
        tpl["Resources"] = resmap
        outpath = outdir / CATEGORY_FILES[cat]
        with outpath.open("w", encoding="utf-8") as f:
            yaml.safe_dump(tpl, f, sort_keys=False)

def split(template: Dict[str, Any], outdir: Path, dry_run: bool = False) -> Dict[str, int]:
    resources = template.get("Resources", {})
    buckets = categorize_resources(resources)
    write_buckets(buckets, outdir, dry_run=dry_run)
    return {k: len(v) for k, v in buckets.items()}

# -----------------------
# S3 helpers (new mirror options + back-compat)
# -----------------------
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

def _gather_yaml_files(local_dir: Path) -> List[Path]:
    return [local_dir / CATEGORY_FILES[c] for c in CATEGORY_FILES if (local_dir / CATEGORY_FILES[c]).exists()]

def _s3_client(region: str, profile: Optional[str] = None):
    if boto3 is None:
        print("[ERR] boto3 is required for S3 backup. pip install boto3", file=sys.stderr)
        sys.exit(2)
    sess_kwargs = {}
    if profile:
        sess_kwargs["profile_name"] = profile
    return boto3.Session(region_name=region, **sess_kwargs).client("s3")

def _s3_upload_file(client, bucket: str, key: str, local_path: Path,
                    storage_class: Optional[str], kms_key_id: Optional[str],
                    dry_run: bool = False) -> None:
    if dry_run:
        print(f"[DRY-RUN][S3] Would upload {local_path} -> s3://{bucket}/{key}")
        return
    extra = {}
    ctype, _ = mimetypes.guess_type(local_path.name)
    if ctype:
        extra["ContentType"] = ctype
    if storage_class:
        extra["StorageClass"] = storage_class
    if kms_key_id:
        extra["ServerSideEncryption"] = "aws:kms"
        extra["SSEKMSKeyId"] = kms_key_id
    client.upload_file(str(local_path), bucket, key, ExtraArgs=extra)
    print(f"[S3] Uploaded {local_path} -> s3://{bucket}/{key}")

def mirror_to_s3(
    outdir: Path,
    *,
    # new unified options
    s3_bucket: Optional[str],
    s3_prefix: Optional[str],
    s3_region: Optional[str],
    s3_storage_class: Optional[str],
    s3_kms_key_id: Optional[str],
    # optional back-compat
    backup_region: Optional[str],
    backup_path: Optional[str],
    dest_region: Optional[str],
    profile: Optional[str],
    dry_run: bool
) -> None:
    """
    Mirrors YAML outputs to S3. Supports either:
      - New style:   s3_bucket + s3_prefix (+ s3_region / storage_class / kms)
      - Back-compat: backup_region + backup_path (s3://bucket/prefix)
    If dest_region is present, files are placed under .../<dest-region>/...
    """
    files = _gather_yaml_files(outdir)
    if not files:
        print("[WARN] No split files found to upload.", file=sys.stderr)
        return

    # Resolve target
    if s3_bucket:
        region = s3_region or backup_region  # allow mixing if needed
        if not region:
            # default to explicit safe value
            region = "us-east-1"
        client = _s3_client(region, profile=profile)
        prefix = (s3_prefix or "").strip("/")
        if dest_region:
            prefix = f"{prefix}/{dest_region}" if prefix else dest_region
        if prefix:
            prefix += "/"
        for p in files:
            key = f"{prefix}{p.name}"
            try:
                _s3_upload_file(client, s3_bucket, key, p, s3_storage_class, s3_kms_key_id, dry_run)
            except (BotoCoreError, ClientError) as e:
                print(f"[ERR] Failed to upload {p} to s3://{s3_bucket}/{key}: {e}", file=sys.stderr)
                sys.exit(2)
        return

    # Back-compat path
    if backup_region and backup_path:
        client = _s3_client(backup_region, profile=profile)
        bucket, prefix = parse_s3_path(backup_path)
        if dest_region:
            if not prefix.endswith("/"):
                prefix += "/"
            prefix = f"{prefix}{dest_region}/"
        for p in files:
            key = f"{prefix}{p.name}"
            try:
                _s3_upload_file(client, bucket, key, p, s3_storage_class, s3_kms_key_id, dry_run)
            except (BotoCoreError, ClientError) as e:
                print(f"[ERR] Failed to upload {p} to s3://{bucket}/{key}: {e}", file=sys.stderr)
                sys.exit(2)
        return

    # Nothing to do (no S3 flags)
    return

# -----------------------
# Config helpers (NEW)
# -----------------------
def _fatal(msg: str, ctx: Optional[dict] = None) -> None:
    if ctx:
        print(f"[ERR] {msg}\nContext: {json.dumps(ctx)}", file=sys.stderr)
    else:
        print(f"[ERR] {msg}", file=sys.stderr)
    sys.exit(2)

def _load_config_file(path: str) -> dict:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        _fatal("Config file not found", {"path": str(cfg_path)})
    text = cfg_path.read_text(encoding="utf-8")
    if cfg_path.suffix.lower() in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(text) or {}
        except Exception as e:
            _fatal("Failed to parse YAML config", {"error": str(e)})
    else:
        try:
            data = json.loads(text or "{}")
        except Exception as e:
            _fatal("Failed to parse JSON config", {"error": str(e)})
    if not isinstance(data, dict):
        _fatal("Config top-level must be a mapping/object", {"path": str(cfg_path)})
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

def _as_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return None

def _merge_cli_with_config(args: argparse.Namespace, cfg: dict) -> argparse.Namespace:
    """
    Fill missing CLI values from config. CLI always wins.
    Supported config keys (examples):
      input, output, region, dest_region, profile, dry_run,
      s3_bucket, s3_prefix, s3_region, s3_storage_class, s3_kms_key_id,
      backup_region, backup_path
    """
    # map config->arg attribute
    mapping = {
        "input": "input",
        "output": "output",
        "region": "region",
        "dest_region": "dest_region",
        "profile": "profile",
        "dry_run": "dry_run",
        # S3 new
        "s3_bucket": "s3_bucket",
        "s3_prefix": "s3_prefix",
        "s3_region": "s3_region",
        "s3_storage_class": "s3_storage_class",
        "s3_kms_key_id": "s3_kms_key_id",
        # legacy
        "backup_region": "backup_region",
        "backup_path": "backup_path",
    }
    for ck, attr in mapping.items():
        cur = getattr(args, attr, None)
        if (cur is None or
            (isinstance(cur, str) and cur == "") or
            (isinstance(cur, bool) and cur is False)):
            if ck in cfg and cfg[ck] is not None:
                setattr(args, attr, cfg[ck])

    # Normalize booleans possibly provided as strings
    b = _as_bool(getattr(args, "dry_run", None))
    if b is not None:
        args.dry_run = b

    # Normalize storage class to uppercase if provided
    if getattr(args, "s3_storage_class", None):
        args.s3_storage_class = str(args.s3_storage_class).upper().strip()

    # Regions in this tool: only a single --region is used for metadata/logging;
    # --dest-region is used to place outputs under subdir and S3 prefix.
    return args

# -----------------------
# CLI
# -----------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Split a CloudFormation template into layered YAML files.")
    ap.add_argument("positional_input", nargs="?", help="Input CFN YAML or '-' for stdin (default: ./results/exported_stack.yaml)", default=None)
    ap.add_argument("-i", "--input", dest="flag_input", help="(Back-compat) Input CFN YAML file path", default=None)
    ap.add_argument("--output", required=True, help="MANDATORY: Local output directory where layered YAMLs will be written.")
    ap.add_argument("--region", required=False, help="Source AWS region of the exported template (metadata/logging only).")
    ap.add_argument("--dest-region", required=False, help="Destination AWS region. Enables DR transforms and writes under <output>/<dest-region>/")

    # New S3 mirror options (aligned with sso_exporter)
    ap.add_argument("--s3-bucket", default=None, help="Destination S3 bucket to mirror split YAML files.")
    ap.add_argument("--s3-prefix", default=None, help="Key prefix inside the destination bucket (default: cfn-splits/).")
    ap.add_argument("--s3-region", default=None, help="S3 client region (default: same as --dest-region or us-east-1).")
    ap.add_argument("--s3-storage-class", default=None,
                    choices=["STANDARD","STANDARD_IA","ONEZONE_IA","INTELLIGENT_TIERING","GLACIER_IR","GLACIER",
                             "DEEP_ARCHIVE","REDUCED_REDUNDANCY","EXPRESS_ONEZONE","OUTPOSTS","SNOW","FSX_OPENZFS"],
                    help="S3 storage class for mirrored objects (default: DEEP_ARCHIVE).")
    ap.add_argument("--s3-kms-key-id", default=None, help="KMS key ARN/alias in the destination account for SSE-KMS.")

    # Back-compat S3 options (still supported)
    ap.add_argument("--backup-region", required=False, help="If set together with --backup-path, uploads outputs to this AWS region.")
    ap.add_argument("--backup-path", required=False, help="S3 URI where outputs will be copied, e.g., s3://my-bucket/prefix/")

    ap.add_argument("--profile", default=None, help="AWS profile for S3 uploads (if needed).")
    ap.add_argument("--dry-run", action="store_true", help="Preview only; do not write files or upload to S3.")

    # NEW: config file support (CLI overrides config keys)
    ap.add_argument("--config", default=None, help="YAML/JSON file with defaults; CLI overrides these values.")

    args = ap.parse_args(argv)

    # Resolve which input to use
    if args.positional_input:
        args.input = args.positional_input
    elif args.flag_input:
        args.input = args.flag_input
    else:
        args.input = str(DEFAULT_INPUT)

    # Gentle guidance if user mixed legacy S3 flags incorrectly
    if (args.backup_region and not args.backup_path) or (args.backup_path and not args.backup_region):
        print("[ERR] Both --backup-region and --backup-path must be provided to enable the legacy S3 backup path.", file=sys.stderr)
        sys.exit(2)

    return args

def main() -> None:
    args = parse_args()

    # Load and merge config (CLI wins)
    if args.config:
        cfg = _load_config_file(args.config)
        args = _merge_cli_with_config(args, cfg)

    # Apply effective defaults *after* config/CLI merge so config is honored.
    if args.s3_prefix is None:
        args.s3_prefix = "cfn-splits/"
    if args.s3_storage_class is None:
        args.s3_storage_class = "DEEP_ARCHIVE"

    # Resolve input (supports '-' for stdin)
    if args.input == "-":
        input_display = "<stdin>"
        template = load_template("-")
    else:
        input_path = Path(args.input).expanduser().resolve()
        if not input_path.exists():
            print(f"[ERR] Input not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        input_display = str(input_path)
        template = load_template(input_path)

    # Work on a copy for dry-run friendliness
    tpl_for_process = deepcopy(template)

    # Apply DR transforms if a destination region is provided
    dr_summary = apply_dr_transforms_if_requested(tpl_for_process, args.dest_region, dry_run=args.dry_run)

    # Local output directory (region-aware for DEST only)
    base_outdir = Path(args.output).expanduser().resolve()
    outdir = base_outdir / args.dest_region if args.dest_region else base_outdir

    # Perform splitting (writing only if not dry-run)
    counts = split(tpl_for_process, outdir, dry_run=args.dry_run)
    total = sum(counts.values())

    # Display summary (include source region if provided)
    src_region_text = f"  Source region: {args.region}" if args.region else ""
    if args.dest_region:
        print(f"[OK]{' [DRY-RUN]' if args.dry_run else ''} Split {total} resources for dest-region {args.dest_region} from {input_display} into:")
        print(f"     {outdir}")
        if src_region_text: print(src_region_text)
    else:
        print(f"[OK]{' [DRY-RUN]' if args.dry_run else ''} Split {total} resources from {input_display} into:")
        print(f"     {outdir}")
        if src_region_text: print(src_region_text)
    for cat, n in counts.items():
        print(f"  - {CATEGORY_FILES[cat]}: {n}")

    # DR step preview
    if dr_summary.get("applied"):
        print(f"[DR]{' [DRY-RUN]' if args.dry_run else ''} DR transforms applied for dest-region={args.dest_region}:")
        for step in dr_summary.get("steps", []):
            if step.get("transform") == "public_subnet_default_routes":
                if step.get("skipped_no_igw"):
                    print("  - public_subnet_default_routes: skipped (no InternetGateway found in template)")
                added = step.get("added", [])
                if added:
                    print(f"  - public_subnet_default_routes: would add {len(added)} default route(s) via IGW")
                    for item in added:
                        print(f"      * {item['logical_id']} (rt={item['route_table']}, igw={item['igw']}, subnets={item['subnets']})")
                notes = step.get("notes", [])
                for note in notes:
                    print(f"    note: {note}")

    # Informational S3 banner (mirroring intent)
    if args.s3_bucket or (args.backup_region and args.backup_path):
        s3_region_print = args.s3_region or (args.dest_region if args.dest_region else "us-east-1")
        eff_bucket = args.s3_bucket
        eff_prefix = (args.s3_prefix or "").lstrip("/")
        if not eff_prefix.endswith("/") and eff_prefix:
            eff_prefix += "/"
        # include dest-region subfolder if present
        if args.dest_region:
            eff_prefix = f"{eff_prefix}{args.dest_region}/" if eff_prefix else f"{args.dest_region}/"
        target_text = f"s3://{eff_bucket}/{eff_prefix}" if eff_bucket else args.backup_path
        print(f"[INFO] S3 mirror enabled: {target_text}  Region={s3_region_print}  StorageClass={args.s3_storage_class}  KMS={args.s3_kms_key_id or '(none)'}")

    # Optional S3 backup/mirror
    try:
        mirror_to_s3(
            outdir,
            s3_bucket=args.s3_bucket,
            s3_prefix=args.s3_prefix,
            s3_region=(args.s3_region or (args.dest_region if args.dest_region else None)),
            s3_storage_class=args.s3_storage_class,
            s3_kms_key_id=args.s3_kms_key_id,
            backup_region=args.backup_region,
            backup_path=args.backup_path,
            dest_region=args.dest_region,
            profile=args.profile,
            dry_run=args.dry_run,
        )
        if (args.s3_bucket or (args.backup_region and args.backup_path)):
            if args.dry_run:
                print("[DONE] Dry-run complete (S3 mirror preview printed).")
            else:
                print("[OK] S3 mirror completed.")
        elif args.dry_run:
            print("[DONE] Dry-run complete. No files were written, no S3 uploads performed.")
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as e:
        # Friendly, non-traceback failure for S3
        print(f"[S3][ERROR] Unexpected error while mirroring: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()
