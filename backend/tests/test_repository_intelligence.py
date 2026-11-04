"""
Unit and integration tests for Repository Intelligence Engine (RIE) and Related Files Discovery.
Reference: task.md §1–§6, §10
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from ai.intelligence.builder import RepositoryIntelligenceBuilder
from ai.intelligence.impact import DependencyImpactAnalyzer
from ai.intelligence.models import (
    GraphEdge,
    GraphNode,
    IntelligenceManifest,
    RepositoryIntelligenceSnapshot,
)
from ai.intelligence.related_files import (
    DiscoveredRelatedFile,
    RelatedFileDiscoveryService,
    RelatedFilesDiscoveryResponse,
)
from ai.intelligence.snapshot_manager import RepositoryIntelligenceSnapshotManager


def test_repository_intelligence_snapshot_models():
    """Verify serialization and validation of RepositoryIntelligenceSnapshot."""
    snap = RepositoryIntelligenceSnapshot(
        schema_version="1.0",
        repository_id="repo-123",
        commit_sha="commit_abc123",
        nodes=[
            GraphNode(id="sym-1", type="function", name="create_user", file="backend/services/user.py"),
            GraphNode(id="sym-2", type="class", name="UserRepository", file="backend/repos/user.py"),
        ],
        edges=[
            GraphEdge(source="sym-1", target="sym-2", type="calls"),
        ],
    )
    data = snap.model_dump(mode="json")
    assert data["repository_id"] == "repo-123"
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    assert data["edges"][0]["type"] == "calls"


def test_snapshot_manager_publish_and_load():
    """Verify atomic publishing and retrieval of intelligence snapshots."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mgr = RepositoryIntelligenceSnapshotManager(base_directory=tmp_dir)
        repo_id = str(uuid4())

        snap = RepositoryIntelligenceSnapshot(
            schema_version="1.0",
            repository_id=repo_id,
            commit_sha="a1b2c3d",
            nodes=[
                GraphNode(id="n1", type="function", name="main", file="main.py"),
            ],
            edges=[],
        )

        manifest = mgr.publish_snapshot(snap)
        assert manifest.is_valid is True
        assert manifest.commit_sha == "a1b2c3d"
        assert manifest.symbol_count == 1

        # Load latest
        latest = mgr.load_latest_snapshot(repo_id)
        assert latest is not None
        assert latest.repository_id == repo_id
        assert latest.commit_sha == "a1b2c3d"
        assert len(latest.nodes) == 1

        # Load specific commit
        pinned = mgr.load_snapshot_for_commit(repo_id, "a1b2c3d")
        assert pinned is not None
        assert pinned.commit_sha == "a1b2c3d"


def test_builder_snapshot_synthesis():
    """Verify RepositoryIntelligenceBuilder extracts modules, files, and entry points."""
    builder = RepositoryIntelligenceBuilder(repository_id="repo-demo", commit_sha="v1.0")

    fake_files = [
        type("File", (), {"id": "f1", "path": "backend/app/api/users.py", "language": "python", "line_count": 50, "size_bytes": 1024, "content_hash": "h1"})(),
        type("File", (), {"id": "f2", "path": "backend/app/services/user_service.py", "language": "python", "line_count": 80, "size_bytes": 2048, "content_hash": "h2"})(),
        type("File", (), {"id": "f3", "path": "backend/tests/test_users.py", "language": "python", "line_count": 40, "size_bytes": 800, "content_hash": "h3"})(),
    ]
    fake_symbols = [
        type("Sym", (), {"id": "s1", "name": "get_users", "kind": "function", "file_id": "f1", "start_line": 10, "end_line": 20, "signature": "def get_users():"}),
        type("Sym", (), {"id": "s2", "name": "UserService", "kind": "class", "file_id": "f2", "start_line": 5, "end_line": 40, "signature": "class UserService:"}),
    ]
    fake_edges = [
        type("Edge", (), {"source_symbol_id": "s1", "target_symbol_id": "s2", "edge_type": "calls"}),
    ]

    snapshot = builder.build_snapshot(
        files=fake_files,
        symbols=fake_symbols,
        edges=fake_edges,
        file_contents={
            "backend/app/api/users.py": '@router.get("/users")\ndef get_users():\n    pass\n',
        },
    )

    assert snapshot.repository_id == "repo-demo"
    assert len(snapshot.files) == 3
    assert len(snapshot.nodes) == 2
    assert len(snapshot.edges) == 1
    assert any(ep.entry_type == "api_route" and ep.route_path == "/users" for ep in snapshot.entry_points)
    assert any(m.id == "backend_app" for m in snapshot.modules)


def test_dependency_impact_analyzer():
    """Verify DependencyImpactAnalyzer detects affected downstream dependents."""
    snap = RepositoryIntelligenceSnapshot(
        schema_version="1.0",
        repository_id="repo-impact",
        commit_sha="c1",
        nodes=[
            GraphNode(id="n_route", type="function", name="get_users_route", file="backend/api/users.py"),
            GraphNode(id="n_svc", type="class", name="UserService", file="backend/services/user_service.py"),
            GraphNode(id="n_db", type="class", name="Database", file="backend/core/database.py"),
        ],
        edges=[
            GraphEdge(source="n_route", target="n_svc", type="calls"),
            GraphEdge(source="n_svc", target="n_db", type="calls"),
        ],
    )

    analyzer = DependencyImpactAnalyzer(snap)
    # If database.py changes, UserService and users.py are affected downstream dependents
    report = analyzer.analyze_impact(["backend/core/database.py"])

    assert "backend/core/database.py" in report.reembed_files
    assert "backend/services/user_service.py" in report.affected_files
    assert "backend/api/users.py" in report.affected_files
    assert "UserService" in report.affected_symbols


def test_related_file_discovery_service():
    """Verify discovery and ranking of related files adhering to task.md §6.1, §6.2."""
    snap = RepositoryIntelligenceSnapshot(
        schema_version="1.0",
        repository_id="repo-rel",
        commit_sha="c1",
        nodes=[
            GraphNode(id="sym_create", type="function", name="create_user", file="backend/app/services/user_service.py"),
            GraphNode(id="sym_repo", type="function", name="save", file="backend/app/repositories/user_repo.py"),
            GraphNode(id="sym_model", type="class", name="User", file="backend/app/models/user.py"),
            GraphNode(id="sym_route", type="function", name="create_user_route", file="backend/app/api/user_routes.py"),
        ],
        edges=[
            GraphEdge(source="sym_create", target="sym_repo", type="calls"),
            GraphEdge(source="sym_create", target="sym_model", type="imports"),
            GraphEdge(source="sym_route", target="sym_create", type="calls"),
        ],
    )

    svc = RelatedFileDiscoveryService(snap)
    related = svc.discover_related_files(
        target_path="backend/app/services/user_service.py",
        target_symbol="create_user",
    )

    paths = [r.path for r in related]
    assert "backend/app/repositories/user_repo.py" in paths
    assert "backend/app/models/user.py" in paths
    assert "backend/app/api/user_routes.py" in paths

    # Callers should have relation "caller"
    caller_item = next(r for r in related if r.path == "backend/app/api/user_routes.py")
    assert caller_item.relation == "caller"
    assert caller_item.relation_label == "Direct Caller"

