# -*- coding: utf-8 -*-
from __future__ import annotations
# Auto-generated compatibility shim to satisfy orchestrator.main imports.
try:
    from iaactools.codebase.ebs_backup_pkg.s3_utils import upload_manifest_to_s3, upload_log_to_s3_if_present, append_volume_index_entry, write_latest_pointer, write_snapshot_artifacts  # type: ignore
except Exception:
    try:
        from ebs_backup_pkg.s3_utils import upload_manifest_to_s3, upload_log_to_s3_if_present, append_volume_index_entry, write_latest_pointer, write_snapshot_artifacts  # type: ignore
    except Exception as _e:
        # Leave an explicit failure at import-time to surface the missing dependency
        raise ImportError("Cannot import s3_utils shims: " + str(_e))
__all__ = ['upload_manifest_to_s3', 'upload_log_to_s3_if_present', 'append_volume_index_entry', 'write_latest_pointer', 'write_snapshot_artifacts']
