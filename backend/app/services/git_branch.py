"""Git branch management service for isolating agent changes.

Deliverable for Parth — Week 2 Day 1:
- create_agent_branch(repository_id, task_id) -> creates 'agent/task-{task_id}' from default branch
- get_default_branch(repository_id) -> returns current default branch name
- branch_exists(repository_id, branch_name) -> boolean check
- delete_branch(repository_id, branch_name) -> cleanup on task cancel

Branch naming convention: agent/task-{task_id} (e.g., agent/task-f47ac10b)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError, ErrorCode
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.schemas import PRMetadata
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository
from app.repositories.pull_request_repository import PullRequestRepository

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


@dataclass(frozen=True)
class CommitResult:
    """Result of staging and committing agent changes in the workspace."""

    commit_sha: str
    branch: str
    message: str
    files_changed: list[str]
    insertions: int = 0
    deletions: int = 0
    author_name: str = "Agent"
    author_email: str = "agent@ai-platform.local"
    pushed: bool = False  # Guaranteed False in Week 2 (push happens only in Week 3)


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

        # Check if agent branch already exists (idempotent resume/re-execution)
        if await self.branch_exists(repository_id, branch_name, user_id):
            logger.info("Agent branch %s already exists for repo %s", branch_name, repo.id)
            existing_sha = ""
            try:
                clean_branch = branch_name.removeprefix("refs/heads/")
                existing_info = await client.get_branch(repo.owner, repo.name, clean_branch)
                if isinstance(existing_info, dict):
                    commit_obj = existing_info.get("commit")
                    if isinstance(commit_obj, dict):
                        existing_sha = commit_obj.get("sha", "")
                    elif isinstance(existing_info.get("sha"), str):
                        existing_sha = existing_info["sha"]
            except Exception:
                existing_sha = ""

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

    # ----- Day 4: Commit Staging -------------------------------------------

    async def _run_git(self, args: list[str], cwd: Path) -> tuple[int, str, str]:
        """Execute a git command asynchronously in the specified workspace directory."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode if proc.returncode is not None else 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def commit(
        self,
        workspace_path: str | Path,
        commit_message: str,
        task_id: UUID | str | None = None,
        repository_id: UUID | str | None = None,
        user_id: UUID | str | None = None,
        files: list[str] | None = None,
        author_name: str = "Agent",
        author_email: str = "agent@ai-platform.local",
        allow_empty: bool = False,
    ) -> CommitResult:
        """Stage agent changes as a Git commit in the local workspace.

        Deliverable for Parth — Week 2 Day 4 (Commit Staging):
        - Creates a commit on the agent branch in the workspace clone:
            agent/task-f47ac10b
              └── commit: "agent: Add JWT service (step 1 of 3)"
        - No push to GitHub yet (Rule 553 & week2.md Day 4: Push happens only in Week 3).
        - Meet's orchestrator calls GitBranchService.commit().
        """
        path = Path(workspace_path).resolve()
        if not path.exists() or not path.is_dir():
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"Workspace path does not exist or is not a directory: {workspace_path}",
            )

        if repository_id is not None:
            self._get_repository(repository_id, user_id)

        # Validate git repository
        code, _, err = await self._run_git(["rev-parse", "--is-inside-work-tree"], path)
        if code != 0:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                f"Workspace path is not a valid git repository: {workspace_path}. {err}".strip(),
            )

        # If task_id is provided, ensure branch matches agent/task-{task_id}
        if task_id is not None:
            expected_branch = format_agent_branch_name(task_id)
            code, curr_branch, _ = await self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], path)
            curr_branch = curr_branch.strip()
            if curr_branch != expected_branch:
                # Check if expected_branch exists
                c_verify, _, _ = await self._run_git(["rev-parse", "--verify", expected_branch], path)
                if c_verify == 0:
                    await self._run_git(["checkout", expected_branch], path)
                else:
                    await self._run_git(["checkout", "-b", expected_branch], path)

        # Stage changes
        if files:
            for f in files:
                c_add, _, err_add = await self._run_git(["add", "--", f], path)
                if c_add != 0:
                    raise APIError(
                        400,
                        ErrorCode.INVALID_REQUEST,
                        f"Failed to stage file '{f}': {err_add}".strip(),
                    )
        else:
            c_add, _, err_add = await self._run_git(["add", "-A"], path)
            if c_add != 0:
                raise APIError(
                    500,
                    ErrorCode.INTERNAL_SERVER_ERROR,
                    f"Failed to stage workspace changes: {err_add}".strip(),
                )

        # Check staged files
        _, staged_out, _ = await self._run_git(["diff", "--cached", "--name-only"], path)
        staged_files = [f.strip() for f in staged_out.splitlines() if f.strip()]

        if not staged_files and not allow_empty:
            raise APIError(
                400,
                ErrorCode.INVALID_REQUEST,
                "No changes staged to commit in workspace.",
            )

        # Create commit
        commit_args = [
            "-c", f"user.name={author_name}",
            "-c", f"user.email={author_email}",
            "commit",
            "-m", commit_message,
        ]
        if allow_empty and not staged_files:
            commit_args.append("--allow-empty")

        c_commit, _, err_commit = await self._run_git(commit_args, path)
        if c_commit != 0:
            raise APIError(
                500,
                ErrorCode.INTERNAL_SERVER_ERROR,
                f"Failed to create git commit: {err_commit}".strip(),
            )

        # Get commit SHA and current branch
        _, sha_out, _ = await self._run_git(["rev-parse", "HEAD"], path)
        commit_sha = sha_out.strip()

        _, branch_out, _ = await self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], path)
        branch_name = branch_out.strip()

        # Parse stats
        insertions = 0
        deletions = 0
        _, stat_out, _ = await self._run_git(["diff", "--shortstat", "HEAD~1..HEAD"], path)
        if stat_out:
            ins_match = re.search(r"(\d+)\s+insertion", stat_out)
            del_match = re.search(r"(\d+)\s+deletion", stat_out)
            if ins_match:
                insertions = int(ins_match.group(1))
            if del_match:
                deletions = int(del_match.group(1))

        logger.info(
            "Created workspace commit %s on %s: %s (%d files staged)",
            commit_sha,
            branch_name,
            commit_message,
            len(staged_files),
        )

        return CommitResult(
            commit_sha=commit_sha,
            branch=branch_name,
            message=commit_message,
            files_changed=staged_files,
            insertions=insertions,
            deletions=deletions,
            author_name=author_name,
            author_email=author_email,
            pushed=False,
        )

    # ----- Day 5: PR Metadata Preparation ----------------------------------

    def prepare_pr_metadata(
        self,
        task_id: UUID | str,
        repository_id: UUID | str,
        branch: str,
        base_branch: str,
        changed_files: list[str],
        commit_message: str,
        test_summary: str,
        verification_summary: str,
        user_id: UUID | str | None = None,
        status: str = "prepared",
    ) -> PRMetadata:
        """Collect and persist PR metadata in database table pull_requests.

        Deliverable for Parth — Week 2 Day 5 (PR Metadata Preparation):
        Collects:
        - task_id: UUID
        - branch: str ("agent/task-f47ac10b")
        - base_branch: str ("main")
        - changed_files: list[str]
        - commit_message: str
        - test_summary: str
        - verification_summary: str

        Stored in database table pull_requests. The actual PR is created in Week 3.
        """
        repo = self._get_repository(repository_id, user_id)
        task_uuid = UUID(str(task_id)) if not isinstance(task_id, UUID) else task_id
        repo_uuid = UUID(str(repo.id)) if not isinstance(repo.id, UUID) else repo.id

        if not commit_message.strip():
            raise APIError(400, ErrorCode.INVALID_REQUEST, "commit_message must not be empty.")
        if not test_summary.strip():
            raise APIError(400, ErrorCode.INVALID_REQUEST, "test_summary must not be empty.")
        if not verification_summary.strip():
            raise APIError(400, ErrorCode.INVALID_REQUEST, "verification_summary must not be empty.")

        repo_layer = PullRequestRepository(self._db)
        pr_record = repo_layer.create_or_update(
            task_id=task_uuid,
            repository_id=repo_uuid,
            branch=branch,
            base_branch=base_branch or repo.default_branch or "main",
            changed_files=changed_files,
            commit_message=commit_message,
            test_summary=test_summary,
            verification_summary=verification_summary,
            status=status,
        )

        return PRMetadata(
            task_id=pr_record.task_id,
            branch=pr_record.branch,
            base_branch=pr_record.base_branch,
            changed_files=pr_record.changed_files,
            commit_message=pr_record.commit_message,
            test_summary=pr_record.test_summary,
            verification_summary=pr_record.verification_summary,
            repository_id=pr_record.repository_id,
            pr_number=pr_record.pr_number,
            pr_url=pr_record.pr_url,
            status=pr_record.status,
        )

    def get_pr_metadata(
        self,
        task_id: UUID | str,
        user_id: UUID | str | None = None,
    ) -> PRMetadata:
        """Retrieve stored PR metadata for a task."""
        task_uuid = UUID(str(task_id)) if not isinstance(task_id, UUID) else task_id
        repo_layer = PullRequestRepository(self._db)
        record = repo_layer.get_by_task_id(task_uuid)
        if record is None:
            raise APIError(
                404,
                ErrorCode.NOT_FOUND,
                f"PR metadata for task {task_id} not found.",
            )

        if user_id is not None:
            self._get_repository(record.repository_id, user_id)

        return PRMetadata(
            task_id=record.task_id,
            branch=record.branch,
            base_branch=record.base_branch,
            changed_files=record.changed_files,
            commit_message=record.commit_message,
            test_summary=record.test_summary,
            verification_summary=record.verification_summary,
            repository_id=record.repository_id,
            pr_number=record.pr_number,
            pr_url=record.pr_url,
            status=record.status,
        )

    async def collect_pr_metadata_from_workspace(
        self,
        workspace_path: str | Path,
        task_id: UUID | str,
        repository_id: UUID | str,
        base_branch: str | None = None,
        test_summary: str = "All tests passed",
        verification_summary: str = "Requirement match: PASS",
        user_id: UUID | str | None = None,
    ) -> PRMetadata:
        """Inspect workspace git state and automatically persist PR metadata."""
        path = Path(workspace_path).resolve()
        repo = self._get_repository(repository_id, user_id)
        effective_base = base_branch or repo.default_branch or "main"

        # Get current branch
        _, branch_out, _ = await self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], path)
        branch = branch_out.strip() or format_agent_branch_name(task_id)

        # Get latest commit message
        _, msg_out, _ = await self._run_git(["log", "-1", "--pretty=%B"], path)
        commit_message = msg_out.strip() or f"agent: Changes for task {task_id}"

        # Get changed files compared to base branch (or HEAD~1 if no base ref)
        _, diff_out, _ = await self._run_git(["diff", "--name-only", f"{effective_base}...HEAD"], path)
        if not diff_out.strip():
            _, diff_out, _ = await self._run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"], path)
        changed_files = [f.strip() for f in diff_out.splitlines() if f.strip()]

        return self.prepare_pr_metadata(
            task_id=task_id,
            repository_id=repository_id,
            branch=branch,
            base_branch=effective_base,
            changed_files=changed_files,
            commit_message=commit_message,
            test_summary=test_summary,
            verification_summary=verification_summary,
            user_id=user_id,
        )
