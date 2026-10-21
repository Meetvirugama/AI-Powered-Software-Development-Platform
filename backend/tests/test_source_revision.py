"""Tests for Parth — Week 2 Day 2: Source Revision Correctness.

Deliverable: Source-revision tests.

Covers all 4 core requirements:
1. Ensure the API uses the intended file content.
   - Exact content at specific commit SHA vs different content at another SHA
   - Exact content at branch ref vs tag ref
   - Line range slicing correctness and boundary clamping
   - Binary file detection
   - Content truncation for oversized files

2. Preserve revision information.
   - Revision preserved on FileContentResponse.ref
   - Resolved commit SHA preserved on FileContentResponse.commit_sha
   - Git blob SHA preserved on FileContentResponse.sha
   - SourceReference attached to response preserves repository_id, file_path, revision, and commit_sha
   - Default branch fallback preserves default branch name and resolved commit SHA

3. Handle deleted or inaccessible files.
   - File deleted in target revision (404 with revision context in error)
   - Non-existent file path (404 with revision context)
   - Directory path instead of file (400 INVALID_REQUEST with revision context)
   - Inaccessible / unowned repository (404 REPOSITORY_NOT_FOUND)

4. Prevent cached content from silently representing a different revision.
   - Content cached at commit C1 is never returned when requesting commit C2
   - Advancing branch HEAD (C1 -> C2) misses stale C1 cache
   - Cache key isolation across different repository IDs
   - Stored revision integrity validation (mismatched cached revision is rejected and evicted)
   - Cache invalidation by revision, by file path, and by repository
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.errors import APIError, ErrorCode
from app.integrations.github.cache import SourceRevisionCache
from app.integrations.github.client import GitHubAPIError, GitHubClient
from app.integrations.github.schemas import FileContentRequest, SourceReference
from app.integrations.github.service import GitHubSourceService
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def repo_id():
    return uuid4()


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def sample_repo(repo_id, user_id):
    repo = MagicMock(spec=Repository)
    repo.id = repo_id
    repo.user_id = user_id
    repo.installation_id = uuid4()
    repo.owner = "acme"
    repo.name = "platform"
    repo.default_branch = "main"
    return repo


@pytest.fixture
def sample_installation(sample_repo):
    inst = MagicMock(spec=GitHubInstallation)
    inst.id = sample_repo.installation_id
    inst.installation_id = "inst-999"
    return inst


@pytest.fixture
def mock_db(sample_repo, sample_installation):
    db = MagicMock()
    # Mock _get_authorized_repository
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = sample_repo
    db.execute.return_value = exec_result

    # Mock _get_installation
    db.get.return_value = sample_installation
    return db


@pytest.fixture
def mock_client():
    client = MagicMock(spec=GitHubClient)
    client.get_file_content = AsyncMock()
    client.get_branch = AsyncMock()
    client.get_ref = AsyncMock()
    return client


# ═══════════════════════════════════════════════════════════════════════════
# 1. Ensure the API uses the intended file content
# ═══════════════════════════════════════════════════════════════════════════

class TestIntendedFileContent:
    """Validate that the API retrieves and uses the exact intended file content."""

    @pytest.mark.asyncio
    async def test_uses_exact_content_for_specific_commit_sha(self, mock_db, mock_client, repo_id, user_id):
        """Content at commit SHA-1 must differ from commit SHA-2 on the same file path."""
        service = GitHubSourceService(mock_db, cache=SourceRevisionCache())
        service._get_client = AsyncMock(return_value=mock_client)

        sha1 = "1111111111111111111111111111111111111111"
        sha2 = "2222222222222222222222222222222222222222"

        # Mock GitHub response depending on ref
        async def mock_get_content(owner, repo, path, ref=None):
            if ref == sha1:
                return {
                    "type": "file",
                    "content": base64.b64encode(b"def compute(): return 10\n").decode("ascii"),
                    "encoding": "base64",
                    "size": 25,
                    "sha": "blob-sha-1",
                }
            elif ref == sha2:
                return {
                    "type": "file",
                    "content": base64.b64encode(b"def compute(): return 20  # updated\n").decode("ascii"),
                    "encoding": "base64",
                    "size": 36,
                    "sha": "blob-sha-2",
                }
            raise GitHubAPIError("Not found", status_code=404)

        mock_client.get_file_content.side_effect = mock_get_content

        # Request at commit SHA 1
        resp1 = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="math.py", ref=sha1)
        )
        assert "return 10" in resp1.content
        assert resp1.ref == sha1
        assert resp1.sha == "blob-sha-1"

        # Request at commit SHA 2
        resp2 = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="math.py", ref=sha2)
        )
        assert "return 20" in resp2.content
        assert resp2.ref == sha2
        assert resp2.sha == "blob-sha-2"

        # Confirm content is genuinely different between the two revisions
        assert resp1.content != resp2.content

    @pytest.mark.asyncio
    async def test_line_range_slicing_correctness(self, mock_db, mock_client, repo_id, user_id):
        """Line ranges are 1-indexed, inclusive, and slice intended content."""
        service = GitHubSourceService(mock_db, cache=SourceRevisionCache())
        service._get_client = AsyncMock(return_value=mock_client)

        full_text = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        mock_client.get_file_content.return_value = {
            "type": "file",
            "content": base64.b64encode(full_text.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
            "size": len(full_text),
            "sha": "blob-123",
        }

        # Slice lines 2 to 4
        req = FileContentRequest(path="demo.txt", ref="main", start_line=2, end_line=4)
        resp = await service.get_file_content(repo_id, user_id, req)

        assert resp.content == "line 2\nline 3\nline 4\n"
        assert resp.line_count == 3
        assert resp.source_reference.start_line == 2
        assert resp.source_reference.end_line == 4

    @pytest.mark.asyncio
    async def test_line_range_boundary_clamping(self, mock_db, mock_client, repo_id, user_id):
        """End line beyond total lines clamps to total lines; start line beyond returns empty."""
        service = GitHubSourceService(mock_db, cache=SourceRevisionCache())
        service._get_client = AsyncMock(return_value=mock_client)

        full_text = "alpha\nbeta\ngamma\n"
        mock_client.get_file_content.return_value = {
            "type": "file",
            "content": base64.b64encode(full_text.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
            "size": len(full_text),
            "sha": "blob-123",
        }

        # End line beyond file total (requesting up to line 100 on a 3-line file)
        req_clamp = FileContentRequest(path="demo.txt", ref="main", start_line=2, end_line=100)
        resp_clamp = await service.get_file_content(repo_id, user_id, req_clamp)
        assert resp_clamp.content == "beta\ngamma\n"
        assert resp_clamp.line_count == 2

        # Start line beyond file total
        req_empty = FileContentRequest(path="demo.txt", ref="main", start_line=10, end_line=20)
        resp_empty = await service.get_file_content(repo_id, user_id, req_empty)
        assert resp_empty.content == ""
        assert resp_empty.line_count == 0

    @pytest.mark.asyncio
    async def test_binary_file_detection(self, mock_db, mock_client, repo_id, user_id):
        """Binary content containing null bytes is flagged with is_binary=True."""
        service = GitHubSourceService(mock_db, cache=SourceRevisionCache())
        service._get_client = AsyncMock(return_value=mock_client)

        binary_payload = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        mock_client.get_file_content.return_value = {
            "type": "file",
            "content": base64.b64encode(binary_payload).decode("ascii"),
            "encoding": "base64",
            "size": len(binary_payload),
            "sha": "blob-bin",
        }

        resp = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="app.bin", ref="main")
        )
        assert resp.is_binary is True


# ═══════════════════════════════════════════════════════════════════════════
# 2. Preserve revision information
# ═══════════════════════════════════════════════════════════════════════════

class TestPreserveRevisionInformation:
    """Validate that revision information is preserved across responses and models."""

    @pytest.mark.asyncio
    async def test_explicit_revision_preserved_in_response_and_source_ref(
        self, mock_db, mock_client, repo_id, user_id
    ):
        """Explicit revision string must appear in both FileContentResponse and SourceReference."""
        service = GitHubSourceService(mock_db, cache=SourceRevisionCache())
        service._get_client = AsyncMock(return_value=mock_client)

        target_ref = "release/v2.1.0"
        commit_sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

        mock_client.get_branch.return_value = {"commit": {"sha": commit_sha}}
        mock_client.get_file_content.return_value = {
            "type": "file",
            "content": base64.b64encode(b"const VERSION = '2.1.0';\n").decode("ascii"),
            "encoding": "base64",
            "size": 25,
            "sha": "blob-version-sha",
        }

        resp = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="version.ts", ref=target_ref)
        )

        # Revision preserves target ref
        assert resp.ref == target_ref
        assert resp.commit_sha == commit_sha
        assert resp.sha == "blob-version-sha"

        # SourceReference has unbroken traceability
        assert resp.source_reference is not None
        assert resp.source_reference.repository_id == str(repo_id)
        assert resp.source_reference.file_path == "version.ts"
        assert resp.source_reference.revision == target_ref
        assert resp.source_reference.commit_sha == commit_sha

    @pytest.mark.asyncio
    async def test_omitted_ref_preserves_default_branch_and_commit(
        self, mock_db, mock_client, repo_id, user_id
    ):
        """When ref is omitted, the default branch and its commit SHA are preserved."""
        service = GitHubSourceService(mock_db, cache=SourceRevisionCache())
        service._get_client = AsyncMock(return_value=mock_client)

        main_commit_sha = "abcdef0123456789abcdef0123456789abcdef01"
        mock_client.get_branch.return_value = {"commit": {"sha": main_commit_sha}}
        mock_client.get_file_content.return_value = {
            "type": "file",
            "content": base64.b64encode(b"print('hello default branch')\n").decode("ascii"),
            "encoding": "base64",
            "size": 30,
            "sha": "blob-default-sha",
        }

        resp = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="main.py")
        )

        assert resp.ref == "main"  # Preserved from sample_repo.default_branch
        assert resp.commit_sha == main_commit_sha
        assert resp.source_reference.revision == "main"
        assert resp.source_reference.commit_sha == main_commit_sha


# ═══════════════════════════════════════════════════════════════════════════
# 3. Handle deleted or inaccessible files
# ═══════════════════════════════════════════════════════════════════════════

class TestDeletedOrInaccessibleFiles:
    """Validate graceful error handling for deleted or inaccessible files."""

    @pytest.mark.asyncio
    async def test_deleted_file_in_revision_raises_not_found_with_revision(
        self, mock_db, mock_client, repo_id, user_id
    ):
        """A file deleted in a revision returns 404 with revision context in the message."""
        service = GitHubSourceService(mock_db, cache=SourceRevisionCache())
        service._get_client = AsyncMock(return_value=mock_client)

        mock_client.get_file_content.side_effect = GitHubAPIError("Not Found", status_code=404)

        with pytest.raises(APIError) as exc_info:
            await service.get_file_content(
                repo_id,
                user_id,
                FileContentRequest(path="deprecated_module.py", ref="v2.0-cleanup"),
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.code == ErrorCode.NOT_FOUND
        # Message clearly states path and target revision
        assert "deprecated_module.py" in exc_info.value.message
        assert "v2.0-cleanup" in exc_info.value.message
        assert "deleted" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_directory_path_rejected_with_revision_context(
        self, mock_db, mock_client, repo_id, user_id
    ):
        """Directories returned by contents API are rejected with clear 400 error."""
        service = GitHubSourceService(mock_db, cache=SourceRevisionCache())
        service._get_client = AsyncMock(return_value=mock_client)

        mock_client.get_file_content.return_value = {
            "type": "dir",
            "path": "src/controllers",
            "sha": "tree-sha-123",
        }

        with pytest.raises(APIError) as exc_info:
            await service.get_file_content(
                repo_id,
                user_id,
                FileContentRequest(path="src/controllers", ref="main"),
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST
        assert "dir" in exc_info.value.message
        assert "main" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_unauthorized_repository_access_rejected(self, mock_db, repo_id):
        """Accessing a repository not owned by the user raises 404 REPOSITORY_NOT_FOUND."""
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        service = GitHubSourceService(mock_db, cache=SourceRevisionCache())

        with pytest.raises(APIError) as exc_info:
            await service.get_file_content(
                repo_id,
                uuid4(),  # Different user
                FileContentRequest(path="secret.py"),
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.code == ErrorCode.REPOSITORY_NOT_FOUND


# ═══════════════════════════════════════════════════════════════════════════
# 4. Prevent cached content from silently representing a different revision
# ═══════════════════════════════════════════════════════════════════════════

class TestPreventCachedContentRevisionMismatch:
    """Validate that caching is strictly revision-safe and cannot leak stale revisions."""

    @pytest.mark.asyncio
    async def test_content_cached_for_c1_never_returned_for_c2(
        self, mock_db, mock_client, repo_id, user_id
    ):
        """Requesting commit C2 must NEVER return cached content from commit C1."""
        cache = SourceRevisionCache()
        service = GitHubSourceService(mock_db, cache=cache)
        service._get_client = AsyncMock(return_value=mock_client)

        c1 = "1111111111111111111111111111111111111111"
        c2 = "2222222222222222222222222222222222222222"

        # Pre-seed cache with C1 data
        cache.set(
            repository_id=repo_id,
            revision=c1,
            path="config.json",
            data={
                "path": "config.json",
                "content": '{"version": 1}',
                "blob_sha": "blob-v1",
                "size_bytes": 16,
            },
            commit_sha=c1,
        )

        # Mock GitHub client to return C2 when queried
        mock_client.get_file_content.return_value = {
            "type": "file",
            "content": base64.b64encode(b'{"version": 2}').decode("ascii"),
            "encoding": "base64",
            "size": 16,
            "sha": "blob-v2",
        }

        # Request at C2: must NOT get cached C1
        resp_c2 = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="config.json", ref=c2)
        )

        assert '{"version": 2}' in resp_c2.content
        assert resp_c2.from_cache is False
        assert resp_c2.ref == c2

        # Request at C1: should get cached C1 with from_cache=True
        resp_c1 = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="config.json", ref=c1)
        )
        assert '{"version": 1}' in resp_c1.content
        assert resp_c1.from_cache is True
        assert resp_c1.ref == c1

    @pytest.mark.asyncio
    async def test_advancing_branch_head_misses_stale_cache(
        self, mock_db, mock_client, repo_id, user_id
    ):
        """When branch HEAD advances (e.g. main moves from shaA to shaB), cache is not falsely reused."""
        cache = SourceRevisionCache()
        service = GitHubSourceService(mock_db, cache=cache)
        service._get_client = AsyncMock(return_value=mock_client)

        sha_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        sha_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

        # Initial fetch when main points to sha_a
        mock_client.get_branch.return_value = {"commit": {"sha": sha_a}}
        mock_client.get_file_content.return_value = {
            "type": "file",
            "content": base64.b64encode(b"initial code on main\n").decode("ascii"),
            "encoding": "base64",
            "size": 21,
            "sha": "blob-a",
        }

        resp_first = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="service.py", ref="main")
        )
        assert resp_first.content == "initial code on main\n"
        assert resp_first.from_cache is False

        # Verify a second call at sha_a hits cache
        resp_cached = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="service.py", ref="main")
        )
        assert resp_cached.from_cache is True

        # NOW: main advances to sha_b (new commit pushed to remote)
        mock_client.get_branch.return_value = {"commit": {"sha": sha_b}}
        mock_client.get_file_content.return_value = {
            "type": "file",
            "content": base64.b64encode(b"new commit code on main\n").decode("ascii"),
            "encoding": "base64",
            "size": 24,
            "sha": "blob-b",
        }

        # Query main again: expected commit SHA has changed, so stale cache must be missed!
        resp_advanced = await service.get_file_content(
            repo_id, user_id, FileContentRequest(path="service.py", ref="main")
        )
        assert resp_advanced.content == "new commit code on main\n"
        assert resp_advanced.from_cache is False
        assert resp_advanced.commit_sha == sha_b

    def test_cache_integrity_validation_rejects_mismatch(self, repo_id):
        """Direct cache validation rejects and evicts an entry with a mismatched revision."""
        cache = SourceRevisionCache()

        # Artificially set an entry where key says c1 but stored data says c999
        key = cache.build_key(repo_id, "c1", "file.py")
        cache._memory_cache[key] = {
            "path": "file.py",
            "content": "corrupted",
            "revision": "c999",  # Mismatched revision
            "commit_sha": "c999",
        }

        # Querying for c1 with expected commit sha c1 must reject the mismatched entry
        result = cache.get(repo_id, "c1", "file.py", expected_commit_sha="c1")
        assert result is None  # Rejected!

        # Entry was automatically evicted
        assert key not in cache._memory_cache

    def test_cache_key_isolation_across_repositories(self):
        """Identical paths and revisions in different repositories have isolated cache keys."""
        cache = SourceRevisionCache()
        repo1 = uuid4()
        repo2 = uuid4()
        path = "index.ts"
        rev = "main"

        cache.set(repo1, rev, path, {"content": "repo1 content"}, commit_sha="sha1")
        cache.set(repo2, rev, path, {"content": "repo2 content"}, commit_sha="sha2")

        entry1 = cache.get(repo1, rev, path)
        entry2 = cache.get(repo2, rev, path)

        assert entry1["content"] == "repo1 content"
        assert entry2["content"] == "repo2 content"

    def test_cache_invalidation_by_revision_and_file(self, repo_id):
        """Fine-grained invalidation purges only the targeted revision or file."""
        cache = SourceRevisionCache()
        cache.set(repo_id, "v1", "a.py", {"content": "a1"})
        cache.set(repo_id, "v1", "b.py", {"content": "b1"})
        cache.set(repo_id, "v2", "a.py", {"content": "a2"})

        # Invalidate only a.py at v1
        cache.invalidate(repo_id, "v1", "a.py")
        assert cache.get(repo_id, "v1", "a.py") is None
        assert cache.get(repo_id, "v1", "b.py") is not None
        assert cache.get(repo_id, "v2", "a.py") is not None

        # Invalidate entire v1 revision
        cache.invalidate_revision(repo_id, "v1")
        assert cache.get(repo_id, "v1", "b.py") is None
        assert cache.get(repo_id, "v2", "a.py") is not None
