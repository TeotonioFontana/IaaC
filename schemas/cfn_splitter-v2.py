#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cfn_splitter.py — Split a monolithic CloudFormation template into layered files,
synchronized with cfn_exporter v0.2 metadata and ID strategy.

What’s new (sync with exporter v0.2)
------------------------------------
• Preserves and propagates source **Metadata** (Exporter/AccountId/Regions/ExportedAt/PrefixRegion/Filters)
  into each layer file under `Metadata.Source` and adds `Metadata.Layer`.
• Layer files inherit the source **Description** with a suffix “ — Layer: <name>”.
• Keeps Parameters/Mappings/Outputs if present in the source (so each layer can be deployed independently).
• Categories cover all types exported by v0.2 (VPC/Subnet/IGW/NAT/EIP/RT/Assoc, SG, EC2, etc.).
• Same CLI: mandatory `--output`; optional S3 backup with `--backup-region` + `--backup-path` (both or none).
• Accepts input as positional path, `--input`, or “-” for stdin; defaults to ./results/exported_stack.yaml.

Usage examples:
  # Basic: write outputs locally (mandatory --output)
  python cfn_splitter.py ./results/exported_stack.yaml --output ./results/split

  # Read from stdin
  cat ./results/exported_stack.yaml | python cfn_splitter.py - --output ./results/split

  # Also back up the output files to S3 (requires boto3 and credentials)
  python cfn_splitter.py ./results/exported_stack.yaml \
      --output ./results/split \
      --backup-region us-east-1 \
      --backup-path s3://my-bucket/cfn-splits/prod/
"""
from __future__ import annotations

import argparse
import sys
import mimetypes
from pathlib import Path
from typing import Dict, Any, Optional, Union, TextIO, Tuple

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

RESULTS_DIR = Path("./results")
DEFAULT_INPUT = RESULTS_DIR / "exported_stack.yaml"

# Output file mapping per category (kept stable for CI/scripts)
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

# Type -> category classification (covers exporter v0.2 scope + a bit more)
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


def blank_template(description: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tpl = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": description,
        "Parameters": {},
        "Mappings": {},
        "Resources": {},
        "Outputs": {},
    }
    if metadata:
        tpl["Metadata"] = metadata
    return tpl


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

    # Ensure optional top-level sections exist (for easy propagation)
    for k in ("Parameters", "Mappings", "Outputs", "Metadata", "Description"):
        data.setdefault(k, {} if k != "Description" else "")
    return data


def categorize_resources(resources: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {k: {} for k in CATEGORY_FILES.keys()}
    for logical_id, res in resources.items():
        rtype = (res.get("Type") or "").strip()
        cat = TYPE_TO_CATEGORY.get(rtype, "others")
        buckets[cat][logical_id] = res
    return buckets


def write_buckets(
    buckets: Dict[str, Dict[str, Any]],
    outdir: Path,
    source_description: str,
    source_metadata: Dict[str, Any],
    source_parameters: Dict[str, Any],
    source_mappings: Dict[str, Any],
    source_outputs: Dict[str, Any],
) -> None:
    outdir.mkdir(parents=True, exist_ok=True)

    for cat, resmap in buckets.items():
        # Compose per-layer metadata: copy Source and stamp the layer name
        layer_meta = {
            "Layer": cat,
            "Source": source_metadata or {},
        }

        desc_suffix = f" — Layer: {cat}"
        desc = (source_description or "Split from monolithic template") + desc_suffix

        tpl = blank_template(desc, metadata=layer_meta)
        # Keep params/mappings/outputs identical to source to allow independent deployment when possible
        if source_parameters:
            tpl["Parameters"] = source_parameters
        if source_mappings:
            tpl["Mappings"] = source_mappings
        if source_outputs:
            tpl["Outputs"] = source_outputs

        tpl["Resources"] = resmap

        outpath = outdir / CATEGORY_FILES[cat]
        with outpath.open("w", encoding="utf-8") as f:
            yaml.safe_dump(tpl, f, sort_keys=False)


def split(input_spec: Union[Path, str], outdir: Path) -> Dict[str, int]:
    src = load_template(input_spec)
    resources = src.get("Resources", {})
    buckets = categorize_resources(resources)

    # Extract top-level sections to propagate
    src_desc = src.get("Description", "") or ""
    src_meta = src.get("Metadata", {}) or {}
    src_params = src.get("Parameters", {}) or {}
    src_maps = src.get("Mappings", {}) or {}
    src_out = src.get("Outputs", {}) or {}

    write_buckets(buckets, outdir, src_desc, src_meta, src_params, src_maps, src_out)
    return {k: len(v) for k, v in buckets.items()}


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


def upload_dir_to_s3(local_dir: Path, region: str, s3_uri: str) -> None:
    if boto3 is None:
        print("[ERR] boto3 is required for S3 backup. pip install boto3", file=sys.stderr)
        sys.exit(2)
    bucket, prefix = parse_s3_path(s3_uri)
    client = boto3.client("s3", region_name=region)
    # Upload each file (non-recursive: only the layer YAMLs we created)
    for p in sorted(local_dir.glob("*.yaml")):
        rel_name = p.name  # flat upload
        key = f"{prefix}{rel_name}"
        ctype, _ = mimetypes.guess_type(p.name)
        extra = {"ContentType": ctype} if ctype else {}
        try:
            client.upload_file(str(p), bucket, key, ExtraArgs=extra)
            print(f"[S3] Uploaded {p} -> s3://{bucket}/{key}")
        except (BotoCoreError, ClientError) as e:
            print(f"[ERR] Failed to upload {p} to s3://{bucket}/{key}: {e}", file=sys.stderr)
            sys.exit(2)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Split a CloudFormation template into layered YAML files (exporter v0.2 compatible).")
    ap.add_argument("positional_input", nargs="?", help="Input CFN YAML or '-' for stdin (default: ./results/exported_stack.yaml)", default=None)
    ap.add_argument("-i", "--input", dest="flag_input", help="(Back-compat) Input CFN YAML file path", default=None)
    ap.add_argument("--output", required=True, help="MANDATORY: Local output directory where layered YAMLs will be written.")
    ap.add_argument("--backup-region", required=False, help="If set together with --backup-path, uploads outputs to this AWS region.")
    ap.add_argument("--backup-path", required=False, help="S3 URI where outputs will be copied, e.g., s3://my-bucket/prefix/")
    args = ap.parse_args(argv)

    # Resolve which input to use
    if args.positional_input:
        args.input = args.positional_input
    elif args.flag_input:
        args.input = args.flag_input
    else:
        args.input = str(DEFAULT_INPUT)

    return args


def main() -> None:
    args = parse_args()

    # Resolve input (supports '-' for stdin)
    if args.input == "-":
        input_spec: Union[Path, str] = "-"
        input_display = "<stdin>"
    else:
        input_path = Path(args.input).expanduser().resolve()
        if not input_path.exists():
            print(f"[ERR] Input not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        input_spec = input_path
        input_display = str(input_path)

    # Mandatory output directory
    outdir = Path(args.output).expanduser().resolve()

    counts = split(input_spec, outdir)
    total = sum(counts.values())
    print(f"[OK] Split {total} resources from {input_display} into:")
    for cat, n in counts.items():
        print(f"  - {CATEGORY_FILES[cat]}: {n}")

    # Optional S3 backup
    if (args.backup_region and args.backup_path) or (args.backup_region or args.backup_path):
        if not (args.backup_region and args.backup_path):
            print("[ERR] Both --backup-region and --backup-path must be provided to enable S3 backup.", file=sys.stderr)
            sys.exit(2)
        upload_dir_to_s3(outdir, args.backup_region, args.backup_path)
        print("[OK] S3 backup completed.")


if __name__ == "__main__":
    main()
