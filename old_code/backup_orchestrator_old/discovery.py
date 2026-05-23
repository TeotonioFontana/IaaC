# -*- coding: utf-8 -*-
from __future__ import annotations
# Auto-generated compatibility shim to satisfy orchestrator.main imports.
try:
    from iaactools.codebase.ebs_backup_pkg.discovery import load_instance_name_map, describe_volumes, ssm_collect_lsblk, log_discovery_items  # type: ignore
except Exception:
    try:
        from ebs_backup_pkg.discovery import load_instance_name_map, describe_volumes, ssm_collect_lsblk, log_discovery_items  # type: ignore
    except Exception as _e:
        # Leave an explicit failure at import-time to surface the missing dependency
        raise ImportError("Cannot import discovery shims: " + str(_e))
__all__ = ['load_instance_name_map', 'describe_volumes', 'ssm_collect_lsblk', 'log_discovery_items']
