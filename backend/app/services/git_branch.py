"""Git branch management service for isolating agent changes.

Deliverable for Parth — Week 2 Day 1:
- create_agent_branch(repository_id, task_id) -> creates 'agent/task-{task_id}' from default branch
- get_default_branch(repository_id) -> returns current default branch name
- branch_exists(repository_id, branch_name) -> boolean check
- delete_branch(repository_id, branch_name) -> cleanup on task cancel

Branch naming convention: agent/task-{task_id} (e.g., agent/task-f47ac10b)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentBranchInfo:
    """Metadata for an agent execution branch created when task enters EXECUTING."""

    branch_name: str
    base_branch: str
    base_sha: str
    repository_id: str
    task_id: str
    status: str  # "created" or "ready"


def format_agent_branch_name(task_id: UUID | str) -> str:
    """Format an agent branch name following the convention: agent/task-{task_id}.

    Example:
        format_agent_branch_name(UUID("f47ac10b-58cc-4372-a567-0e02b2c3d479"))
        -> "agent/task-f47ac10b"
    """
    raw = str(task_id).strip()
    if "-" in raw:
        short_id = raw.split("-")[0]
    else:
        short_id = raw[:8] if len(raw) >= 8 else raw
    return f"agent/task-{short_id}"


class GitBranchService:
    """Manage Git branches for agent task isolation.

    Used by the Agent Orchestrator to create isolated branches before
    executing tasks and cleaning them up if tasks are cancelled.
    """

    def __init__(self, db: Session, client: GitHubClient | None = None) -> None:
        self._db = db
        self._client = client

    # ----- Internal helpers ------------------------------------------------

    def _get_repository(
        self,
        repository_id: UUID | str,
        user_id: UUID | str | None = None,
    ) -> Repository:
        """Fetch repository, optionally validating ownership."""
        repo_uuid = UUID(str(repository_id)) if not isinstance(repository_id, UUID) else repository_id
        stmt = select(Repository).where(Repository.id == repo_uuid)
        if user_id is not None:
            user_uuid = UUID(str(user_id)) if not isinstance(user_id, UUID) else user_id
            stmt = stmt.where(Repository.user_id == user_uuid)

        repo = self._db.scalars(stmt).first()
        if repo is None:
            raise APIError(
                404,
                ErrorCode.REPOSITORY_NOT_FOUND,
                f"Repository {repository_id} not found or access denied.",
            )
        return repo

    async def _get_client_for_repo(self, repo: Repository) -> GitHubClient:
        """Resolve an authenticated GitHubClient for the repository's installation."""
        if self._client is not None:
            return self._client

        installation = None
        if hasattr(self._db, "get"):
            try:
                installation = self._db.get(GitHubInstallation, repo.installation_id)
            except Exception:
                installation = None

        if installation is None:
            stmt = select(GitHubInstallation).where(
                GitHubInstallation.installation_id == str(repo.installation_id),
            )
            installation = self._db.scalars(stmt).first()

        access_token = getattr(installation, "access_token", None) if installation else None
        if access_token:
            token = access_token
        else:
            ext_inst_id = (
                installation.installation_id
                if installation is not None and getattr(installation, "installation_id", None)
                else str(repo.installation_id)
            )
            token = await GitHubClient.get_installation_token(str(ext_inst_id))

        return GitHubClient(token)

    # ----- Day 1 Public Operations -----------------------------------------

    async def get_default_branch(
        self,
        repository_id: UUID | str,
        user_id: UUID | str | None = None,
    ) -> str:
        """Return the current default branch name for the repository."""
        repo = self._get_repository(repository_id, user_id)
        return repo.default_branch or "main"

    async def branch_exists(
        self,
        repository_id: UUID | str,
        branch_name: str,
        user_id: UUID | str | None = None,
    ) -> bool:
        """Check whether a branch exists in the repository."""
        repo = self._get_repository(repository_id, user_id)
        client = await self._get_client_for_repo(repo)

        clean_branch = branch_name.removeprefix("refs/heads/")
        try:
            await client.get_branch(repo.owner, repo.name, clean_branch)
            return True
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                return False
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"Failed to check branch existence: {exc}",
                retryable=exc.retryable,
            ) from exc

    async def on_task_executing(
        self,
        repository_id: UUID | str,
        task_id: UUID | str,
        user_id: UUID | str | None = None,
        base_branch: str | None = None,
    ) -> AgentBranchInfo:
        """Triggered when execution starts (task transitions to EXECUTING).

        Creates the isolated agent branch from default branch (main):
        main
          └── agent/task-f47ac10b    ← created here

        All agent file edits stay in the workspace directory only during Week 2.
        The branch exists in Git pointing to base_sha without any commits yet.
        """
        repo = self._get_repository(repository_id, user_id)
        client = await self._get_client_for_repo(repo)

        branch_name = format_agent_branch_name(task_id)
        source_branch = base_branch or repo.default_branch or "main"

        # Check if agent branch already exists first (idempotent resume/re-execution)
        if await self.branch_exists(repository_id, branch_name, user_id):
            logger.info("Agent branch %s already exists for repo %s", branch_name, repo.id)
            existing_sha = ""
            try:
                clean_branch = branch_name.removeprefix("refs/heads/")
                existing_info = await client.get_branch(repo.owner, repo.name, clean_branch)
                if isinstance(existing_info, dict):
                    existing_sha = existing_info.get("commit", {}).get("sha", "")
            except GitHubAPIError:
                pass

            return AgentBranchInfo(
                branch_name=branch_name,
                base_branch=source_branch,
                base_sha=existing_sha,
                repository_id=str(repository_id),
                task_id=str(task_id),
                status="ready",
            )

        # Resolve latest commit SHA of source branch only when creating new branch
        try:
            branch_info = await client.get_branch(repo.owner, repo.name, source_branch)
            source_sha = branch_info.get("commit", {}).get("sha") if isinstance(branch_info, dict) else None
            if not source_sha:
                ref_info = await client.get_ref(repo.owner, repo.name, f"heads/{source_branch}")
                if isinstance(ref_info, dict):
                    source_sha = ref_info.get("object", {}).get("sha")
        except GitHubAPIError as exc:
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"Failed to resolve base branch '{source_branch}': {exc}",
                retryable=exc.retryable,
            ) from exc

        if not source_sha:
            raise APIError(
                500,
                ErrorCode.INTERNAL_SERVER_ERROR,
                f"Could not determine commit SHA for base branch '{source_branch}'.",
            )

        # Create branch ref pointing to source_sha
        try:
            await client.create_branch(repo.owner, repo.name, branch_name, source_sha)
            logger.info("Created agent branch %s at %s for repo %s", branch_name, source_sha, repo.id)
        except GitHubAPIError as exc:
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"Failed to create agent branch '{branch_name}': {exc}",
                retryable=exc.retryable,
            ) from exc

        return AgentBranchInfo(
            branch_name=branch_name,
            base_branch=source_branch,
            base_sha=source_sha,
            repository_id=str(repository_id),
            task_id=str(task_id),
            status="created",
        )

    async def create_agent_branch(
        self,
        repository_id: UUID | str,
        task_id: UUID | str,
        user_id: UUID | str | None = None,
        base_branch: str | None = None,
    ) -> str:
        """Create an isolated branch agent/task-{task_id} from the default branch.

        Returns the created branch name (e.g. 'agent/task-f47ac10b').
        """
        info = await self.on_task_executing(repository_id, task_id, user_id, base_branch)
        return info.branch_name

    async def delete_branch(
        self,
        repository_id: UUID | str,
        branch_name: str,
        user_id: UUID | str | None = None,
    ) -> bool:
        """Delete a branch (e.g. on task cancellation).

        Returns True if deleted or already absent.
        """
        repo = self._get_repository(repository_id, user_id)
        client = await self._get_client_for_repo(repo)

        clean_branch = branch_name.removeprefix("refs/heads/")
        # Do not allow deleting the default branch
        if clean_branch == (repo.default_branch or "main"):
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"Cannot delete repository default branch '{clean_branch}'.",
            )

        try:
            await client.delete_branch(repo.owner, repo.name, clean_branch)
            logger.info("Deleted branch %s for repo %s", clean_branch, repo.id)
            return True
        except GitHubAPIError as exc:
            if exc.status_code == 404:
                return True
            raise APIError(
                502,
                ErrorCode.SERVICE_UNAVAILABLE,
                f"Failed to delete branch '{clean_branch}': {exc}",
                retryable=exc.retryable,
            ) from exc
