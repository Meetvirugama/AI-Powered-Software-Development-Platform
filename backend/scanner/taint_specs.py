"""Repository-Specific Taint Specification Schema and Loader (Phase 7).

Part of Issue #191: Broaden Security Analysis and Bug Detection Findings.
Provides structured, schema-validated definitions for repository-specific
sources, sinks, and sanitizers that can augment the deterministic TaintAnalyzer.

Treats all user/LLM-supplied rules as untrusted inputs with strict validation.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# Valid identifier pattern preventing regex / injection vectors
_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z0-9_\.\:\(\)\[\]\$\<\>\-]{1,128}$")


class TaintSpecEntry(BaseModel):
    """A single source, sink, or sanitizer specification."""

    name: str = Field(..., min_length=1, max_length=128)
    category: str = Field("custom", max_length=64)
    description: str = Field("", max_length=256)
    confidence: str = Field("medium", pattern="^(high|medium|low)$")

    @field_validator("name")
    @classmethod
    def validate_name_safety(cls, val: str) -> str:
        """Validate specification identifier name to prevent command/path injection."""
        stripped = val.strip()
        if not _IDENTIFIER_PATTERN.match(stripped):
            raise ValueError(f"Invalid specification identifier '{stripped}'. Must match {_IDENTIFIER_PATTERN.pattern}")
        # Reject control characters and newline escapes
        if any(c in stripped for c in ("\x00", "\n", "\r", ";", "`")):
            raise ValueError(f"Dangerous characters in specification name: {stripped}")
        return stripped


class RepositoryTaintSpec(BaseModel):
    """Schema-validated collection of repository-specific taint specifications."""

    repository_id: str | None = None
    version: str = Field("1.0.0", max_length=32)
    sources: list[TaintSpecEntry] = Field(default_factory=list)
    sinks: list[TaintSpecEntry] = Field(default_factory=list)
    sanitizers: list[TaintSpecEntry] = Field(default_factory=list)
    is_active: bool = True

    def validate_specification_safety(self) -> bool:
        """Validate all entries for safety."""
        for entry in (*self.sources, *self.sinks, *self.sanitizers):
            if not _IDENTIFIER_PATTERN.match(entry.name):
                return False
        return True

    def apply_to_taint_analyzer(self, taint_analyzer: Any) -> int:
        """Safely register validated specifications into the active TaintAnalyzer."""
        if not self.is_active or not self.validate_specification_safety():
            return 0

        # Copy existing mappings and sets onto the analyzer instance to prevent
        # mutating shared class/global structures across analyzers.
        for attr in ("SOURCE_PATTERNS", "SANITIZERS"):
            if hasattr(taint_analyzer, attr):
                shared_map = getattr(taint_analyzer, attr)
                if isinstance(shared_map, dict):
                    setattr(taint_analyzer, attr, shared_map.copy())

        for attr in ("SQL_SINKS", "CMD_SINKS", "PATH_SINKS", "SSRF_SINKS"):
            if hasattr(taint_analyzer, attr):
                shared_set = getattr(taint_analyzer, attr)
                if isinstance(shared_set, (set, frozenset)):
                    setattr(taint_analyzer, attr, set(shared_set).copy())

        registered_count = 0
        # Register custom sources
        for s in self.sources:
            if hasattr(taint_analyzer, "SOURCE_PATTERNS"):
                taint_analyzer.SOURCE_PATTERNS[s.name] = (s.name, s.description or "Custom source")
                registered_count += 1

        # Register custom sanitizers
        for san in self.sanitizers:
            if hasattr(taint_analyzer, "SANITIZERS"):
                taint_analyzer.SANITIZERS[san.name] = san.category or "custom_sanitizer"
                registered_count += 1

        # Register custom sinks
        for sk in self.sinks:
            cat = sk.category.lower()
            if "sql" in cat and hasattr(taint_analyzer, "SQL_SINKS"):
                taint_analyzer.SQL_SINKS.add(sk.name)
                registered_count += 1
            elif "cmd" in cat and hasattr(taint_analyzer, "CMD_SINKS"):
                taint_analyzer.CMD_SINKS.add(sk.name)
                registered_count += 1
            elif "path" in cat and hasattr(taint_analyzer, "PATH_SINKS"):
                taint_analyzer.PATH_SINKS.add(sk.name)
                registered_count += 1
            elif "ssrf" in cat and hasattr(taint_analyzer, "SSRF_SINKS"):
                taint_analyzer.SSRF_SINKS.add(sk.name)
                registered_count += 1

        return registered_count
