"""
Git History Co-Change Coupling Miner (Issue 1 — F05-C3 / MSR Co-Change Analysis).

Identifies repository files that frequently change together across Git commits.
In mining-software-repositories (MSR) literature, historical co-change coupling
captures implicit logical dependencies (e.g. configuration + handler, schema +
migration, backend route + frontend client) that static AST call graphs cannot see.

Safety & Boundedness Guarantees:
- Never invokes a shell (`shell=False`); validates `repo_root` before running `git log`.
- Bounds commit history window (`max_commits = 200` by default) and skips noisy bulk
  commits (`max_files_per_commit = 30`, e.g. repo-wide formatting or initial imports).
- Accepts pre-parsed `commit_file_sets` for deterministic unit testing and offline use.
- Fails open to `[]` when `.git` is absent or git history is unavailable.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
import logging
from pathlib import Path
import subprocess
from typing import Any

from ai.intelligence.models import CoChangeEdge

logger = logging.getLogger(__name__)

DEFAULT_MAX_COMMITS: int = 200
DEFAULT_MAX_FILES_PER_COMMIT: int = 30
DEFAULT_MIN_CO_CHANGES: int = 2
DEFAULT_MIN_JACCARD: float = 0.15


def _normalize_repo_path(path: str) -> str:
    clean = (path or "").strip().replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    return clean.lstrip("/")


class GitCoChangeMiner:
    """Mines pairwise file co-change coupling metrics from Git commit history."""

    def __init__(
        self,
        *,
        max_commits: int = DEFAULT_MAX_COMMITS,
        max_files_per_commit: int = DEFAULT_MAX_FILES_PER_COMMIT,
        min_co_changes: int = DEFAULT_MIN_CO_CHANGES,
        min_jaccard: float = DEFAULT_MIN_JACCARD,
    ) -> None:
        self.max_commits = max(1, max_commits)
        self.max_files_per_commit = max(2, max_files_per_commit)
        self.min_co_changes = max(1, min_co_changes)
        self.min_jaccard = max(0.0, min(1.0, min_jaccard))

    def extract_commits_from_git(self, repo_root: str | Path) -> list[tuple[str, list[str]]]:
        """
        Read recent non-merge commits and their modified file lists from a local Git repository.
        Returns a list of `(commit_sha, [file_path, ...])` tuples (newest first).
        """
        root_path = Path(repo_root).resolve()
        if not root_path.exists() or not (root_path / ".git").exists():
            return []

        cmd = [
            "git",
            "-C",
            str(root_path),
            "log",
            "--no-merges",
            f"-n{self.max_commits}",
            "--name-only",
            "--pretty=format:COMMIT:%H",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if proc.returncode != 0 or not proc.stdout:
                return []
        except Exception as exc:
            logger.debug("Git co-change log extraction skipped for %s: %s", root_path, exc)
            return []

        return self.parse_git_log_output(proc.stdout)

    @staticmethod
    def parse_git_log_output(raw_log: str) -> list[tuple[str, list[str]]]:
        """Parse `git log --name-only --pretty=format:COMMIT:%H` output into `(sha, files)` tuples."""
        commits: list[tuple[str, list[str]]] = []
        current_sha: str | None = None
        current_files: list[str] = []

        for raw_line in raw_log.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("COMMIT:"):
                if current_sha is not None and current_files:
                    commits.append((current_sha, list(dict.fromkeys(current_files))))
                current_sha = line.removeprefix("COMMIT:").strip()
                current_files = []
            elif current_sha is not None:
                norm_f = _normalize_repo_path(line)
                if norm_f:
                    current_files.append(norm_f)

        if current_sha is not None and current_files:
            commits.append((current_sha, list(dict.fromkeys(current_files))))

        return commits

    def mine_co_changes(
        self,
        *,
        repo_root: str | Path | None = None,
        commit_history: Sequence[tuple[str, Sequence[str]] | Sequence[str] | dict[str, Any]] | None = None,
        known_files: Iterable[str] | None = None,
    ) -> list[CoChangeEdge]:
        """
        Compute pairwise file co-change edges from either explicit `commit_history` or `repo_root`.
        """
        known_set: set[str] | None = (
            {_normalize_repo_path(f) for f in known_files if _normalize_repo_path(f)}
            if known_files is not None
            else None
        )

        normalized_commits: list[tuple[str, list[str]]] = []
        if commit_history is not None:
            for idx, item in enumerate(list(commit_history)[: self.max_commits]):
                if isinstance(item, dict):
                    sha = str(item.get("sha") or item.get("commit_sha") or f"commit_{idx}")
                    raw_files = item.get("files") or item.get("paths") or []
                elif (
                    isinstance(item, tuple)
                    and len(item) == 2
                    and isinstance(item[0], str)
                    and not isinstance(item[1], str)
                ):
                    sha = item[0]
                    raw_files = item[1]
                else:
                    sha = f"commit_{idx}"
                    raw_files = item  # type: ignore[assignment]

                cleaned = [
                    _normalize_repo_path(str(p))
                    for p in raw_files
                    if _normalize_repo_path(str(p))
                ]
                if known_set is not None:
                    cleaned = [p for p in cleaned if p in known_set]
                deduped = sorted(set(cleaned))
                if 2 <= len(deduped) <= self.max_files_per_commit:
                    normalized_commits.append((sha, deduped))
                elif len(deduped) == 1:
                    normalized_commits.append((sha, deduped))
        elif repo_root is not None:
            raw_commits = self.extract_commits_from_git(repo_root)
            for sha, f_list in raw_commits:
                cleaned = [p for p in f_list if (known_set is None or p in known_set)]
                deduped = sorted(set(cleaned))
                if 1 <= len(deduped) <= self.max_files_per_commit:
                    normalized_commits.append((sha, deduped))

        if not normalized_commits:
            return []

        file_commit_counts: dict[str, int] = defaultdict(int)
        pair_co_changes: dict[tuple[str, str], int] = defaultdict(int)
        pair_last_commit: dict[tuple[str, str], str] = {}

        for sha, files_in_commit in normalized_commits:
            for f in files_in_commit:
                file_commit_counts[f] += 1
            if len(files_in_commit) < 2:
                continue
            for i in range(len(files_in_commit)):
                for j in range(i + 1, len(files_in_commit)):
                    pair = (files_in_commit[i], files_in_commit[j])
                    pair_co_changes[pair] += 1
                    if pair not in pair_last_commit:
                        pair_last_commit[pair] = sha

        edges: list[CoChangeEdge] = []
        for (file_a, file_b), co_count in pair_co_changes.items():
            if co_count < self.min_co_changes:
                continue
            count_a = file_commit_counts[file_a]
            count_b = file_commit_counts[file_b]
            union = count_a + count_b - co_count
            if union <= 0:
                continue
            jaccard = co_count / union
            if jaccard < self.min_jaccard:
                continue

            conf_a_to_b = co_count / count_a if count_a > 0 else 0.0
            conf_b_to_a = co_count / count_b if count_b > 0 else 0.0
            edges.append(
                CoChangeEdge(
                    file_a=file_a,
                    file_b=file_b,
                    co_change_count=co_count,
                    total_commits_a=count_a,
                    total_commits_b=count_b,
                    jaccard_similarity=round(jaccard, 4),
                    confidence_a_to_b=round(conf_a_to_b, 4),
                    confidence_b_to_a=round(conf_b_to_a, 4),
                    last_co_changed_commit=pair_last_commit.get((file_a, file_b)),
                )
            )

        edges.sort(
            key=lambda e: (e.jaccard_similarity, e.co_change_count, max(e.confidence_a_to_b, e.confidence_b_to_a)),
            reverse=True,
        )
        return edges


__all__ = ["GitCoChangeMiner"]
