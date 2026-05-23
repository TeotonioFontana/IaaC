# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class PhaseOutcome:
    complete: bool
    notes: Dict[str, Any] = field(default_factory=dict)
