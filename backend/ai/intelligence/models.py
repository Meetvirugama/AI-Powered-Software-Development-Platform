"""
Repository Intelligence Engine (RIE) — Core Models & Schemas.
Reference: task.md §3, §4, §6

Provides Pydantic models for persistent repository intelligence:
- RepositoryIntelligenceSnapshot: Portable, versioned snapshot of the repository's understanding.
- IntelligenceManifest: High-level metadata, statistics, and validation status.
- GraphNode & GraphEdge: AST symbol nodes and relationships (calls, imports, extends, implements, tests, uses).
- ModuleMetadata & FileIntelligenceMetadata: Hierarchical module and file summaries.
- EntryPointMetadata: Discovered API routes, CLI commands, and worker entrypoints.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class OverviewMetadata(BaseModel):
    """Level 1 architectural overview of the repository."""

    project_type: str = "Software Application"
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    architecture: str = "Modular Architecture"
    summary: str = ""
    total_files: int = 0
    total_symbols: int = 0
    primary_language: str = "Unknown"


class ModuleMetadata(BaseModel):
    """Level 2 logical module description and boundaries."""

    id: str
    name: str
    path: str
    responsibility: str = ""
    files_count: int = 0
    symbols_count: int = 0
    files: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class FileIntelligenceMetadata(BaseModel):
    """Metadata and summary for an individual repository file."""

    id: str
    path: str
    language: str = "text"
    content_hash: str = ""
    line_count: int = 0
    size_bytes: int = 0
    summary: str = ""
    symbols: list[str] = Field(default_factory=list)
    module_id: str | None = None
    is_test: bool = False
    is_entry_point: bool = False


class GraphNode(BaseModel):
    """Symbol node in the repository knowledge graph."""

    id: str
    type: str = Field(description="Symbol kind, e.g. 'function', 'class', 'method', 'variable', 'type'")
    name: str
    file: str
    start_line: int = 1
    end_line: int = 1
    signature: str | None = None
    parent_id: str | None = None


class GraphEdge(BaseModel):
    """Relationship edge in the repository knowledge graph."""

    source: str = Field(description="Source symbol ID or name")
    target: str = Field(description="Target symbol ID or name")
    type: Literal["calls", "imports", "extends", "implements", "tests", "uses"] = "calls"
    confidence: float = 1.0


class EntryPointMetadata(BaseModel):
    """Discovered application or API entry point."""

    id: str
    path: str
    symbol: str
    entry_type: Literal["api_route", "cli_command", "worker_job", "main_script"] = "api_route"
    method: str | None = None
    route_path: str | None = None
    framework: str | None = None


class IntelligenceManifest(BaseModel):
    """Lightweight metadata manifest for quick validation and version tracking."""

    schema_version: str = "1.0"
    repository_id: str
    commit_sha: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    file_count: int = 0
    symbol_count: int = 0
    edge_count: int = 0
    module_count: int = 0
    entry_point_count: int = 0
    is_valid: bool = True
    validation_notes: list[str] = Field(default_factory=list)


class RepositoryIntelligenceSnapshot(BaseModel):
    """Complete, self-contained, and portable repository intelligence snapshot."""

    schema_version: str = "1.0"
    repository_id: str
    commit_sha: str
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    overview: OverviewMetadata = Field(default_factory=OverviewMetadata)
    modules: list[ModuleMetadata] = Field(default_factory=list)
    files: list[FileIntelligenceMetadata] = Field(default_factory=list)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    entry_points: list[EntryPointMetadata] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

