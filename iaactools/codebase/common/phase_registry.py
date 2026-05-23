# -*- coding: utf-8 -*-
"""
phase_registry.py — Phase mapping and availability tracking.
"""

def get_phases_for(tool: str):
    """
    Return list of phases for the given orchestrator.
    tool can be: 'backup' or 'recovery'
    """
    if tool == "backup":
        return [
            "phase1_discovery",
            "phase2_snapshot_creation",
            "phase3_manifest_upload",
            "phase4_s3_validation",
        ]
    elif tool == "recovery":
        return [
            "phase1_discovery",
            "phase2_manifest_check",
            "phase3_volume_verification",
            "phase4_snapshot_verification",
            "phase5_cross_validation",
            "phase6_orphan_detection",
            # phase7_recovery_simulation — future
            # phase8_ai_policy_check — future
        ]
    else:
        raise ValueError(f"Unknown orchestrator tool: {tool}")
