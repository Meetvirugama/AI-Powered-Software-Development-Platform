"""
Repository Intelligence Engine (RIE) — Core Models & Schemas.
Reference: task.md §3, §4, §6 & Issue 1 (PageRank F05-C3 + Co-Change Coupling)

Provides Pydantic models for persistent repository intelligence:
- RepositoryIntelligenceSnapshot: Portable, versioned snapshot of the repository's understanding.
- IntelligenceManifest: High-level metadata, statistics, and validation status.
- GraphNode & GraphEdge: AST symbol nodes and relationships (calls, imports, extends, implements, tests, uses).
- CoChangeEdge: Historical Git file co-change coupling metrics.
- ModuleMetadata & FileIntelligenceMetadata: Hierarchical module and file summaries with PageRank importance.
- EntryPointMetadata: Discovered API routes, CLI commands, and worker entrypoints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

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
    importance_score: float = 0.0


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
    importance_score: float = 0.0


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
    importance_score: float = 0.0


class GraphEdge(BaseModel):
    """Relationship edge in the repository knowledge graph."""

    source: str = Field(description="Source symbol ID or name")
    target: str = Field(description="Target symbol ID or name")
    type: Literal["calls", "imports", "extends", "implements", "tests", "uses"] = "calls"
    confidence: float = 1.0
    provenance: str = "tree_sitter"
    resolution_status: str = "resolved"
    weight: float = 1.0


class CoChangeEdge(BaseModel):
    """Historical Git co-change coupling between two repository files."""

    file_a: str
    file_b: str
    co_change_count: int = 1
    total_commits_a: int = 1
    total_commits_b: int = 1
    jaccard_similarity: float = 0.0
    confidence_a_to_b: float = 0.0
    confidence_b_to_a: float = 0.0
    last_co_changed_commit: str | None = None


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

    schema_version: str = "1.1"
    repository_id: str
    commit_sha: str
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    file_count: int = 0
    symbol_count: int = 0
    edge_count: int = 0
    co_change_edge_count: int = 0
    module_count: int = 0
    entry_point_count: int = 0
    is_valid: bool = True
    validation_notes: list[str] = Field(default_factory=list)


class RepositoryIntelligenceSnapshot(BaseModel):
    """Complete, self-contained, and portable repository intelligence snapshot."""

    schema_version: str = "1.1"
    repository_id: str
    commit_sha: str
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    overview: OverviewMetadata = Field(default_factory=OverviewMetadata)
    modules: list[ModuleMetadata] = Field(default_factory=list)
    files: list[FileIntelligenceMetadata] = Field(default_factory=list)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    co_change_edges: list[CoChangeEdge] = Field(default_factory=list)
    top_important_files: list[str] = Field(default_factory=list)
    entry_points: list[EntryPointMetadata] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
