# -*- coding: utf-8 -*-
from __future__ import annotations
# Auto-generated compatibility shim to satisfy orchestrator.main imports.
try:
    from iaactools.codebase.ebs_backup_pkg.models import BackupRecord  # type: ignore
except Exception:
    try:
        from ebs_backup_pkg.models import BackupRecord  # type: ignore
    except Exception as _e:
        # Leave an explicit failure at import-time to surface the missing dependency
        raise ImportError("Cannot import models shims: " + str(_e))
__all__ = ['BackupRecord']
