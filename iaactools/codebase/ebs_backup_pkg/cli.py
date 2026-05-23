from __future__ import annotations
import argparse
from typing import Any, Dict, Optional

from .utils import load_config_file

def parse_args() -> argparse.Namespace:
    # Phase 0: capture --config first
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--config", default=None, help="Path to YAML/JSON config file whose values become defaults.")
    pre, _ = base.parse_known_args()
    config: Dict[str, Any] = load_config_file(pre.config) if pre.config else {}

    def cget(key: str, default):
        return config.get(key, default)

    ap = argparse.ArgumentParser(
        description="EBS snapshots, cross-region copies, and/or full-volume images to S3.",
        parents=[base]
    )

    # Core selection
    ap.add_argument("--backup-type", default=cget("backup_type","snapshot"),
                    choices=["snapshot","full-volume","both"])
    ap.add_argument("--profile", default=cget("profile", None))
    ap.add_argument("--src-region", default=cget("src_region","us-east-2"))
    ap.add_argument("--dst-region", default=cget("dst_region","us-east-1"))
    ap.add_argument("--states", default=cget("states","in-use,available"))
    ap.add_argument("--filter-tag", action="append", default=cget("filter_tag", []))
    ap.add_argument("--tag", action="append", default=cget("tag", []))

    # Logging
    ap.add_argument("--log-file", default=cget("log_file", None))
    ap.add_argument("--log-json", action="store_true", default=cget("log_json", False))
    ap.add_argument("--log-json-array", action="store_true", default=cget("log_json_array", False))
    ap.add_argument("--log-level", default=cget("log_level","INFO"), choices=["DEBUG","INFO","WARNING","ERROR"])
    ap.add_argument("--manifest-file", default=cget("manifest_file","results/ebs_backup_manifest.json"))

    # Confirmations
    ap.add_argument("--ssm-inspect", action="store_true", default=cget("ssm_inspect", False))
    ap.add_argument("--verbose", action="store_true", default=cget("verbose", False))
    ap.add_argument("--yes", action="store_true", default=cget("yes", False))

    # Snapshot encryption controls
    ap.add_argument("--encrypt-dst", dest="encrypt_dst", action="store_true", default=cget("encrypt_dst", True))
    ap.add_argument("--no-encrypt-dst", dest="encrypt_dst", action="store_false")
    ap.add_argument("--kms-key-id", default=cget("kms_key_id", None))
    ap.add_argument("--delete-src-after-copy", action="store_true", default=cget("delete_src_after_copy", False))

    # S3 manifest/log upload controls
    ap.add_argument("--s3-bucket", default=cget("s3_bucket", None))
    ap.add_argument("--s3-prefix", default=cget("s3_prefix","tf-backup/"))
    ap.add_argument("--s3-region", default=cget("s3_region", None))
    ap.add_argument("--s3-storage-class", default=cget("s3_storage_class","DEEP_ARCHIVE"),
                    choices=["STANDARD","STANDARD_IA","ONEZONE_IA","INTELLIGENT_TIERING","GLACIER_IR","GLACIER",
                             "DEEP_ARCHIVE","EXPRESS_ONEZONE","OUTPOSTS","SNOW","FSX_OPENZFS","REDUCED_REDUNDANCY"])

    # Full-volume backup controls
    ap.add_argument("--helper-instance-id", default=cget("helper_instance_id", None))
    ap.add_argument("--fullvol-s3-bucket", default=cget("fullvol_s3_bucket", None))
    ap.add_argument("--fullvol-format", default=cget("fullvol_format","raw.gz"), choices=["raw","raw.gz"])
    ap.add_argument("--fullvol-keep-temp-volume", action="store_true", default=cget("fullvol_keep_temp_volume", False))

    # Safety modes
    ap.add_argument("--preview", action="store_true", default=cget("preview", False))
    ap.add_argument("--simulate", action="store_true", default=cget("simulate", False))

    args = ap.parse_args()
    args._config_path = pre.config  # stash for logs
    args._config = config
    return args
