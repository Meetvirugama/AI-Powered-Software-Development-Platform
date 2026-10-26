"""AI Developer Intelligence Services.

Owner: Dev — Week 2 AI Analysis Engines
Reference: Docs/week2.md §5 & §6

Exports:
- CodeExplanationService (Day 2)
"""

from __future__ import annotations

from .bug_detection_engine import BugDetectionEngine
from .explanation_service import CodeExplanationService

__all__ = [
    "BugDetectionEngine",
    "CodeExplanationService",
]
