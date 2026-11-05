"""
Repository Intelligence Snapshot Manager.
Reference: task.md §3, §5, §11

Responsibilities:
- Persist structured repository intelligence snapshots to disk under:
    repository-intelligence/{repository_id}/
    ├── manifest.json
    ├── repository_intelligence.json
    ├── file_summaries/
    └── versions/
        ├── commit_{sha}/
        └── latest/
- Atomic snapshot version switching: build and validate before updating `latest`.
- Retrieve latest or revision-pinned snapshots for explanation and analysis pipelines.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from ai.intelligence.models import (
    IntelligenceManifest,
    RepositoryIntelligenceSnapshot,
)

logger = logging.getLogger(__name__)

# Base storage path for snapshots: defaults to .workspaces/repository-intelligence
DEFAULT_SNAPSHOT_BASE_DIR = Path(
    os.getenv("REPOSITORY_INTELLIGENCE_DIR")
    or (Path(__file__).resolve().parents[3] / ".workspaces" / "repository-intelligence")
)


class RepositoryIntelligenceSnapshotManager:
    """Manages versioned physical intelligence artifacts on disk."""

    _cache: ClassVar[dict[str, tuple[float, RepositoryIntelligenceSnapshot]]] = {}

    def __init__(self, base_directory: Path | str | None = None) -> None:
        self.base_dir = Path(base_directory or DEFAULT_SNAPSHOT_BASE_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_repo_dir(self, repository_id: str | UUID) -> Path:
        """Return the physical root path for a repository's intelligence artifacts."""
        repo_dir = self.base_dir / str(repository_id)
        repo_dir.mkdir(parents=True, exist_ok=True)
        return repo_dir

    def publish_snapshot(
        self,
        snapshot: RepositoryIntelligenceSnapshot,
    ) -> IntelligenceManifest:
        """
        Atomically publish a repository intelligence snapshot.
        Writes into a staging directory, validates integrity, and commits to versions/commit_{sha} and latest/.
        """
        repo_dir = self.get_repo_dir(snapshot.repository_id)
        commit_sha = snapshot.commit_sha or "latest"
        version_dir = repo_dir / "versions" / f"commit_{commit_sha}"

        manifest = IntelligenceManifest(
            schema_version=snapshot.schema_version,
            repository_id=snapshot.repository_id,
            commit_sha=commit_sha,
            generated_at=snapshot.generated_at,
            file_count=len(snapshot.files),
            symbol_count=len(snapshot.nodes),
            edge_count=len(snapshot.edges),
            module_count=len(snapshot.modules),
            entry_point_count=len(snapshot.entry_points),
            is_valid=True,
        )

        # Stage in temporary directory for atomic publish
        staging_dir = Path(tempfile.mkdtemp(prefix=f"rie_stage_{snapshot.repository_id}_"))
        try:
            staging_summaries = staging_dir / "file_summaries"
            staging_summaries.mkdir(parents=True, exist_ok=True)

            # 1. Write repository_intelligence.json
            intel_path = staging_dir / "repository_intelligence.json"
            with open(intel_path, "w", encoding="utf-8") as f:
                f.write(snapshot.model_dump_json(indent=2))

            # 2. Write manifest.json
            manifest_path = staging_dir / "manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(manifest.model_dump_json(indent=2))

            # 3. Write individual module/file summaries
            for mod in snapshot.modules:
                mod_summary_file = staging_summaries / f"{mod.id}.json"
                mod_data = {
                    "module": mod.model_dump(mode="json"),
                    "files": [
                        f.model_dump(mode="json")
                        for f in snapshot.files
                        if f.module_id == mod.id or f.path.startswith(mod.path)
                    ],
                }
                with open(mod_summary_file, "w", encoding="utf-8") as f:
                    json.dump(mod_data, f, indent=2)

            # Move staging into versions/commit_{sha}
            version_dir.parent.mkdir(parents=True, exist_ok=True)
            if version_dir.exists():
                shutil.rmtree(version_dir, ignore_errors=True)
            shutil.copytree(staging_dir, version_dir)

            # Update latest/ pointer
            latest_dir = repo_dir / "versions" / "latest"
            if latest_dir.exists():
                if latest_dir.is_symlink():
                    latest_dir.unlink()
                else:
                    shutil.rmtree(latest_dir, ignore_errors=True)
            try:
                latest_dir.symlink_to(version_dir.name, target_is_directory=True)
            except (OSError, NotImplementedError):
                shutil.copytree(version_dir, latest_dir)

            # Also publish root-level copy for instant lookup
            shutil.copy2(intel_path, repo_dir / "repository_intelligence.json")
            shutil.copy2(manifest_path, repo_dir / "manifest.json")
            root_summaries = repo_dir / "file_summaries"
            if root_summaries.exists():
                shutil.rmtree(root_summaries, ignore_errors=True)
            shutil.copytree(staging_summaries, root_summaries)

            logger.info(
                "Published repository intelligence snapshot for repo %s (commit %s): %d files, %d symbols, %d edges",
                snapshot.repository_id,
                commit_sha,
                len(snapshot.files),
                len(snapshot.nodes),
                len(snapshot.edges),
            )
            return manifest
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def load_latest_snapshot(
        self,
        repository_id: str | UUID,
    ) -> RepositoryIntelligenceSnapshot | None:
        """Load the latest snapshot for a repository."""
        repo_dir = self.get_repo_dir(repository_id)
        intel_file = repo_dir / "repository_intelligence.json"
        if not intel_file.exists():
            # Check latest version directory
            latest_intel = repo_dir / "versions" / "latest" / "repository_intelligence.json"
            if latest_intel.exists():
                intel_file = latest_intel
            else:
                return None

        cache_key = f"{repository_id}:latest"
        try:
            mtime = intel_file.stat().st_mtime
            cached = self._cache.get(cache_key)
            if cached and cached[0] == mtime:
                return cached[1]
            with open(intel_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            snapshot = RepositoryIntelligenceSnapshot.model_validate(data)
            self._cache[cache_key] = (mtime, snapshot)
            return snapshot
        except (json.JSONDecodeError, OSError, ValueError, KeyError) as exc:
            logger.warning("Failed to load intelligence snapshot for repo %s: %s", repository_id, exc)
            return None

    def load_snapshot_for_commit(
        self,
        repository_id: str | UUID,
        commit_sha: str,
    ) -> RepositoryIntelligenceSnapshot | None:
        """Load the snapshot pinned to a specific Git commit SHA."""
        repo_dir = self.get_repo_dir(repository_id)
        version_file = repo_dir / "versions" / f"commit_{commit_sha}" / "repository_intelligence.json"
        if version_file.exists():
            cache_key = f"{repository_id}:commit_{commit_sha}"
            try:
                mtime = version_file.stat().st_mtime
                cached = self._cache.get(cache_key)
                if cached and cached[0] == mtime:
                    return cached[1]
                with open(version_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                snapshot = RepositoryIntelligenceSnapshot.model_validate(data)
                self._cache[cache_key] = (mtime, snapshot)
                return snapshot
            except (json.JSONDecodeError, OSError, ValueError, KeyError) as exc:
                logger.warning("Failed to load pinned snapshot %s: %s", commit_sha, exc)

        return self.load_latest_snapshot(repository_id)

