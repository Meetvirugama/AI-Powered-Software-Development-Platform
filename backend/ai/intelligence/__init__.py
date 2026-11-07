"""
Repository Intelligence Engine (RIE) Module.
Reference: task.md §1, §3, §4, §5, §6

Provides persistent repository intelligence, snapshot storage, dependency impact analysis,
and related-file discovery for Intelligent Explain Code Studio.
"""

from ai.intelligence.builder import RepositoryIntelligenceBuilder
from ai.intelligence.impact import DependencyImpactAnalyzer, ImpactAnalysisReport
from ai.intelligence.models import (
    EntryPointMetadata,
    FileIntelligenceMetadata,
    GraphEdge,
    GraphNode,
    IntelligenceManifest,
    ModuleMetadata,
    OverviewMetadata,
    RepositoryIntelligenceSnapshot,
)
from ai.intelligence.related_files import (
    DiscoveredRelatedFile,
    RelatedFileDiscoveryService,
    RelatedFilesDiscoveryResponse,
)
from ai.intelligence.snapshot_manager import (
    DEFAULT_SNAPSHOT_BASE_DIR,
    RepositoryIntelligenceSnapshotManager,
)

__all__ = [
    "DEFAULT_SNAPSHOT_BASE_DIR",
    "DependencyImpactAnalyzer",
    "DiscoveredRelatedFile",
    "EntryPointMetadata",
    "FileIntelligenceMetadata",
    "GraphEdge",
    "GraphNode",
    "ImpactAnalysisReport",
    "IntelligenceManifest",
    "ModuleMetadata",
    "OverviewMetadata",
    "RelatedFileDiscoveryService",
    "RelatedFilesDiscoveryResponse",
    "RepositoryIntelligenceBuilder",
    "RepositoryIntelligenceSnapshot",
    "RepositoryIntelligenceSnapshotManager",
]

