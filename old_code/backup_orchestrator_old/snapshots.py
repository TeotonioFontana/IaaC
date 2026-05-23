# -*- coding: utf-8 -*-
from __future__ import annotations
# Auto-generated compatibility shim to satisfy orchestrator.main imports.
try:
    from iaactools.codebase.ebs_backup_pkg.snapshots import create_snapshot_for_volume, wait_snapshot_complete, copy_snapshot  # type: ignore
except Exception:
    try:
        from ebs_backup_pkg.snapshots import create_snapshot_for_volume, wait_snapshot_complete, copy_snapshot  # type: ignore
    except Exception as _e:
        # Leave an explicit failure at import-time to surface the missing dependency
        raise ImportError("Cannot import snapshots shims: " + str(_e))
__all__ = ['create_snapshot_for_volume', 'wait_snapshot_complete', 'copy_snapshot']
