# -*- coding: utf-8 -*-
"""
===============================================================================
 backup_orchestrator_pkg — Package Init
===============================================================================
 Author.............: Teotoniio Fontana — Architect
 Programmed by......: Duke (GPT-5, OpenAI)
 Project............: IaaC Tools / Backup Orchestration
 Purpose............: Unified package entrypoint exposing orchestration and
                      discovery routines.
-------------------------------------------------------------------------------
 Description
 ------------------------------------------------------------------------------
 This package consolidates all components of the Backup Orchestrator:
   • orchestrator.py       — Main CLI and execution logic
   • discovery_core.py     — Base collectors (phases 0.1–0.5)
   • discovery_multi.py    — Multi-region orchestration and summaries
   • discovery_ext.py      — Unified interface and public exports
===============================================================================
"""
from backup_orchestrator_pkg.result_envelope import enveloped

__version__ = "v0.8.0-alpha"

# -----------------------------------------------------------------------------
# Core exports
# -----------------------------------------------------------------------------
from .orchestrator import main as orchestrator_main
from .discovery_ext import (
    discover_environment,
    discover_environment_multi,
)

# -----------------------------------------------------------------------------
# Inline documentation
# -----------------------------------------------------------------------------
def orchestrator_main_help():
    """Entry point for running the full backup orchestration process."""
    pass


def discover_environment_help():
    """Run Phase 0 discovery for a single AWS region."""
    pass


def discover_environment_multi_help():
    """Run Phase 0 discovery across all enabled AWS regions."""
    pass


# -----------------------------------------------------------------------------
# Public interface
# -----------------------------------------------------------------------------
__all__ = [
    "orchestrator_main",
    "discover_environment",
    "discover_environment_multi",
    "orchestrator_main_help",
    "discover_environment_help",
    "discover_environment_multi_help",
]
