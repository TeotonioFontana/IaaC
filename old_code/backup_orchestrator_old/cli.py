# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, sys
from typing import Any, Dict, List, Optional
from .utils import normalize_list, load_config_file

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Orchestrate full-region snapshot (IDC + CFN + AMI/EBS)")
    p.add_argument("--config", help="YAML/JSON settings incl. module_configs")

    p.add_argument("--profile", help="AWS named profile")
    p.add_argument("--source-region", help="Region to EXPORT from (read-only)")
    p.add_argument("--home-region", help="IAM Identity Center HOME region")
    p.add_argument("--dest-region", help="Optional target region (splitter/AMI hint)")

    p.add_argument("--instance-arn", help="Identity Center InstanceArn")
    p.add_argument("--identity-store-id", help="IdentityStoreId")
    p.add_argument("--assume", help="Role ARN to assume for sso_exporter")
    p.add_argument("--assume-sts-region", default=None, help="Region for STS AssumeRole")

    p.add_argument("--out-root", help="Root directory for outputs")
    p.add_argument("--tools-dir", help="Directory with helper scripts")

    p.add_argument("--stack-name", default=None, help="Logical CFN name")

    p.add_argument("--enable-ebs", action="store_true")
    p.add_argument("--ebs-config", help="Path to ebs_backup config JSON")
    p.add_argument("--enable-ami", action="store_true")

    p.add_argument("--backup-region", help="(optional) S3 region for CFN split mirror")
    p.add_argument("--cfn-backup-path", help="(optional) S3 URI for CFN split mirror")

    p.add_argument("--s3-bucket", help="(optional) IDC S3 bucket")
    p.add_argument("--s3-prefix", help="(optional) IDC S3 prefix")
    p.add_argument("--s3-region", help="(optional) IDC S3 region")
    p.add_argument("--s3-storage-class",
                   choices=["STANDARD","STANDARD_IA","ONEZONE_IA","INTELLIGENT_TIERING","GLACIER_IR","GLACIER","DEEP_ARCHIVE","REDUCED_REDUNDANCY","EXPRESS_ONEZONE","OUTPOSTS","SNOW","FSX_OPENZFS"])
    p.add_argument("--s3-kms-key-id", help="(optional) IDC SSE-KMS key")

    p.add_argument("--preview", action="store_true")
    p.add_argument("--simulate", action="store_true")
    p.add_argument("--keep-going", action="store_true")

    p.add_argument("--enabled-modules", nargs="*", help="sso_exporter sso_assignments_exporter cfn_exporter cfn_splitter ebs_backup ami_build")

    # ---- Logging flags ----
    p.add_argument("--log-file", default=None, help="Optional path for JSON/text log")
    p.add_argument("--log-json", action="store_true", help="Emit JSON lines")
    p.add_argument("--log-json-array", action="store_true", help="Emit a JSON array")
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO)"
    )

    # Back-compat: ensure attributes exist even if older configs/CLIs don't pass them
    p.set_defaults(
        log_file=None,
        log_json=False,
        log_json_array=False,
        log_level="INFO",
    )

    return p.parse_args(argv)

def apply_config_defaults(args: argparse.Namespace, cfg: dict) -> argparse.Namespace:
    keymap = {
        "profile":"profile","source_region":"source_region","home_region":"home_region","dest_region":"dest_region",
        "instance_arn":"instance_arn","identity_store_id":"identity_store_id","assume":"assume","assume_sts_region":"assume_sts_region",
        "out_root":"out_root","tools_dir":"tools_dir","stack_name":"stack_name","ebs_config":"ebs_config",
        "enabled_modules":"enabled_modules","module_configs":"module_configs",
        "backup_region":"backup_region","cfn_backup_path":"cfn_backup_path",
        "s3_bucket":"s3_bucket","s3_prefix":"s3_prefix","s3_region":"s3_region","s3_storage_class":"s3_storage_class","s3_kms_key_id":"s3_kms_key_id",
        # allow config to set logging fields too
        "log_level":"log_level","log_file":"log_file","log_json":"log_json","log_json_array":"log_json_array",
    }
    for ck, attr in keymap.items():
        cur = getattr(args, attr, None)
        if (cur is None or cur == "" or (attr == "enabled_modules" and not cur)) and ck in cfg and cfg[ck] is not None:
            setattr(args, attr, cfg[ck])

    # Booleans that can be toggled via config when CLI didn't specify them
    for ck, attr in [("enable_ebs","enable_ebs"),("enable_ami","enable_ami"),
                     ("preview","preview"),("simulate","simulate"),("keep_going","keep_going"),
                     ("log_json","log_json"),("log_json_array","log_json_array")]:
        cli_val = getattr(args, attr, False)
        if not cli_val and isinstance(cfg.get(ck), bool):
            setattr(args, attr, bool(cfg[ck]))

    # Normalize lists and modules
    args.enabled_modules = normalize_list(getattr(args, "enabled_modules", None))
    if not isinstance(getattr(args,"module_configs",{}), dict):
        args.module_configs = {}

    return args

def require_after_merge(args: argparse.Namespace) -> None:
    missing = [k for k in ("source_region","home_region","out_root","tools_dir") if not getattr(args, k, None)]
    if missing:
        print("[FATAL] Missing required arguments (after --config): " + ", ".join(m.replace("_","-") for m in missing), file=sys.stderr)
        sys.exit(2)

    # Defaults
    if not args.stack_name:
        args.stack_name = "tf-stack"
    if args.assume and not args.assume_sts_region:
        args.assume_sts_region = "us-east-1"

    # Normalize log level defensively
    if getattr(args, "log_level", None):
        args.log_level = str(args.log_level).upper()

def parse_and_load(argv: Optional[List[str]] = None) -> argparse.Namespace:
    args = parse_args(argv)
    if args.config:
        cfg = load_config_file(args.config)
        args = apply_config_defaults(args, cfg)
    require_after_merge(args)
    return args

def _ensure_logging_attrs(args):
    # Kept for backward-compat calls; parse_args() already sets these.
    if not hasattr(args, "log_file"): args.log_file = None
    if not hasattr(args, "log_json"): args.log_json = False
    if not hasattr(args, "log_json_array"): args.log_json_array = False
    if not hasattr(args, "log_level"): args.log_level = "INFO"
    return args
