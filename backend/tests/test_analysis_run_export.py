"""Unit and integration tests for Analysis Run Evaluation Dataset Export (Issue #195).

Verifies:
1. Exporting analysis history into JSONL and JSON datasets.
2. Structure of exported evaluation samples (input, output, findings, feedback_summary, metadata).
3. Filtering by feature_type (including aliases), status, and feedback presence (include_feedback_only).
4. Multi-tenant repository isolation: no cross-tenant leakage during dataset export.
5. Error handling for unsupported format options.
6. Empty repository handling.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session

from app.models.analysis_finding import AnalysisFinding
from app.models.analysis_run import AnalysisFeature, AnalysisRun, AnalysisRunStatus
from app.models.github_installation import GitHubInstallation
from app.models.repository import Repository, SyncStatus
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.services.analysis_run_history_service import AnalysisRunHistoryService


@pytest.fixture
def sample_data(db_session: Session):
    """Seed test repositories, runs, findings, and developer feedback."""
    user = User(
        id=uuid.uuid4(),
        github_id="gh_195",
        email="developer@example.com",
        login="dev195",
        avatar_url="",
    )
    db_session.add(user)
    db_session.flush()

    inst = GitHubInstallation(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id="inst_195",
        account_login=user.login,
        permissions={},
    )
    db_session.add(inst)
    db_session.flush()

    repo1 = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=inst.id,
        github_repo_id="19501",
        owner=user.login,
        name="platform-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    repo2 = Repository(
        id=uuid.uuid4(),
        user_id=user.id,
        installation_id=inst.id,
        github_repo_id="19502",
        owner=user.login,
        name="isolated-repo",
        default_branch="main",
        sync_status=SyncStatus.SYNCED,
    )
    db_session.add_all([repo1, repo2])
    db_session.flush()

    run_repo = AnalysisRunRepository(db_session)

    # 1. Bug Detection Run on repo1 (with 2 findings, 1 with feedback)
    run_bugs = run_repo.create_run(
        repository_id=repo1.id,
        user_id=user.id,
        feature_type="detect_bugs",
        status=AnalysisRunStatus.COMPLETED.value,
        target_path="src/auth/tokens.py",
        target_symbol="verify_jwt",
        start_line=12,
        end_line=45,
        source_revision="commit_sha_195a",
        result_payload={"summary": "Detected 2 vulnerabilities"},
        findings=[
            {
                "category": "security",
                "severity": "HIGH",
                "title": "Unvalidated JWT signature",
                "description": "JWT is parsed without verifying signature",
                "file_path": "src/auth/tokens.py",
                "start_line": 20,
                "end_line": 25,
                "evidence": "jwt.decode(token, verify=False)",
                "suggested_fix": "jwt.decode(token, key, algorithms=['HS256'])",
                "confidence": "high",
                "metadata": {
                    "feedback": {
                        "feedback_type": "useful",
                        "user_id": str(user.id),
                        "comment": "Accurate finding, fixed immediately.",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                },
            },
            {
                "category": "performance",
                "severity": "LOW",
                "title": "Redundant hash computation",
                "description": "Key is hashed in loop",
                "file_path": "src/auth/tokens.py",
                "start_line": 35,
                "end_line": 38,
                "evidence": "hashlib.sha256(key)",
                "confidence": "medium",
            },
        ],
    )

    # 2. Code Review Run on repo1 (without feedback)
    run_review = run_repo.create_run(
        repository_id=repo1.id,
        user_id=user.id,
        feature_type="review",
        status=AnalysisRunStatus.COMPLETED.value,
        target_path="src/main.py",
        source_revision="commit_sha_195b",
        result_payload={"summary": "Review complete"},
        findings=[
            {
                "category": "style",
                "severity": "INFO",
                "title": "Missing docstring",
                "description": "Public function lacks docstring",
                "file_path": "src/main.py",
                "start_line": 1,
                "end_line": 5,
                "evidence": "def main():",
                "confidence": "high",
            }
        ],
    )

    # 3. Failed Run on repo1
    run_failed = run_repo.create_run(
        repository_id=repo1.id,
        user_id=user.id,
        feature_type="generate_tests",
        status=AnalysisRunStatus.FAILED.value,
        target_path="src/failing.py",
        error_message="SyntaxError in source file",
    )

    # 4. Run on repo2 (for tenant isolation test)
    run_other_repo = run_repo.create_run(
        repository_id=repo2.id,
        user_id=user.id,
        feature_type="detect_bugs",
        status=AnalysisRunStatus.COMPLETED.value,
        target_path="src/secret.py",
        findings=[],
    )

    return {
        "user": user,
        "repo1": repo1,
        "repo2": repo2,
        "run_bugs": run_bugs,
        "run_review": run_review,
        "run_failed": run_failed,
        "run_other_repo": run_other_repo,
    }


def test_export_evaluation_dataset_jsonl_structure(db_session: Session, sample_data: dict):
    """Test exporting runs in JSONL format with complete evaluation sample schema."""
    service = AnalysisRunHistoryService()
    repo1_id = sample_data["repo1"].id

    jsonl_output = service.export_evaluation_dataset(
        repo1_id,
        format="jsonl",
        db=db_session,
    )

    assert isinstance(jsonl_output, str)
    lines = [line.strip() for line in jsonl_output.strip().split("\n") if line.strip()]
    assert len(lines) == 3  # run_bugs, run_review, run_failed

    parsed_records = [json.loads(line) for line in lines]
    bug_record = next(r for r in parsed_records if r["id"] == str(sample_data["run_bugs"].id))

    # Verify standard evaluation sample contract
    assert bug_record["repository_id"] == str(repo1_id)
    assert bug_record["feature_type"] == "detect_bugs"
    assert bug_record["status"] == "COMPLETED"
    assert bug_record["input"]["target_path"] == "src/auth/tokens.py"
    assert bug_record["input"]["target_symbol"] == "verify_jwt"
    assert bug_record["input"]["start_line"] == 12
    assert bug_record["input"]["end_line"] == 45
    assert bug_record["input"]["source_revision"] == "commit_sha_195a"

    # Verify findings and embedded feedback
    assert len(bug_record["findings"]) == 2
    f1 = bug_record["findings"][0]
    assert f1["title"] == "Unvalidated JWT signature"
    assert f1["category"] == "security"
    assert f1["severity"] == "HIGH"
    assert f1["feedback"] is not None
    assert f1["feedback"]["feedback_type"] == "useful"
    assert "Accurate finding" in f1["feedback"]["comment"]

    # Verify feedback summary aggregation
    assert bug_record["feedback_summary"]["has_feedback"] is True
    assert bug_record["feedback_summary"]["total_feedback"] == 1
    assert bug_record["feedback_summary"]["by_type"]["useful"] == 1


def test_export_evaluation_dataset_json_format(db_session: Session, sample_data: dict):
    """Test exporting runs in standard JSON format."""
    service = AnalysisRunHistoryService()
    repo1_id = sample_data["repo1"].id

    json_output = service.export_evaluation_dataset(
        repo1_id,
        format="json",
        db=db_session,
    )

    assert isinstance(json_output, str)
    data = json.loads(json_output)
    assert isinstance(data, list)
    assert len(data) == 3
    ids = {d["id"] for d in data}
    assert str(sample_data["run_bugs"].id) in ids
    assert str(sample_data["run_review"].id) in ids
    assert str(sample_data["run_failed"].id) in ids


def test_export_evaluation_records_filtering(db_session: Session, sample_data: dict):
    """Test filtering by feature_type, status, and include_feedback_only."""
    service = AnalysisRunHistoryService()
    repo1_id = sample_data["repo1"].id

    # 1. Filter by feature type
    bugs_only = service.export_evaluation_records(
        repo1_id,
        feature_type="detect_bugs",
        db=db_session,
    )
    assert len(bugs_only) == 1
    assert bugs_only[0]["id"] == str(sample_data["run_bugs"].id)

    # Alias check
    bugs_alias = service.export_evaluation_records(
        repo1_id,
        feature_type="bugs",
        db=db_session,
    )
    assert len(bugs_alias) == 1

    # 2. Filter by status
    failed_only = service.export_evaluation_records(
        repo1_id,
        status="FAILED",
        db=db_session,
    )
    assert len(failed_only) == 1
    assert failed_only[0]["id"] == str(sample_data["run_failed"].id)
    assert failed_only[0]["metadata"]["error_message"] == "SyntaxError in source file"

    # 3. Filter by include_feedback_only
    feedback_only = service.export_evaluation_records(
        repo1_id,
        include_feedback_only=True,
        db=db_session,
    )
    assert len(feedback_only) == 1
    assert feedback_only[0]["id"] == str(sample_data["run_bugs"].id)
    assert feedback_only[0]["feedback_summary"]["has_feedback"] is True


def test_export_multi_tenant_isolation(db_session: Session, sample_data: dict):
    """Ensure runs from one repository are never exposed in another repository's export."""
    service = AnalysisRunHistoryService()
    repo2_id = sample_data["repo2"].id

    records = service.export_evaluation_records(
        repo2_id,
        db=db_session,
    )
    assert len(records) == 1
    assert records[0]["id"] == str(sample_data["run_other_repo"].id)
    assert records[0]["repository_id"] == str(repo2_id)
    assert records[0]["input"]["target_path"] == "src/secret.py"


def test_export_invalid_format_raises_error(db_session: Session, sample_data: dict):
    """Verify ValueError is raised when an unsupported format is requested."""
    service = AnalysisRunHistoryService()
    repo1_id = sample_data["repo1"].id

    with pytest.raises(ValueError, match="Unsupported dataset export format 'xml'"):
        service.export_evaluation_dataset(
            repo1_id,
            format="xml",
            db=db_session,
        )


def test_export_empty_repository(db_session: Session):
    """Verify empty repositories return empty exports gracefully without errors."""
    service = AnalysisRunHistoryService()
    empty_repo_id = uuid.uuid4()

    jsonl_output = service.export_evaluation_dataset(
        empty_repo_id,
        format="jsonl",
        db=db_session,
    )
    assert jsonl_output == ""

    json_output = service.export_evaluation_dataset(
        empty_repo_id,
        format="json",
        db=db_session,
    )
    assert json.loads(json_output) == []


def test_export_endpoint_via_client(client, db_session: Session, sample_data: dict, monkeypatch):
    """Test GET /api/v1/repositories/{repository_id}/analysis-runs/export via HTTP client."""
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-12345-secure-32bytes!")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.core.security import create_access_token

    token, _ = create_access_token(user_id=str(sample_data["user"].id))
    headers = {"Authorization": f"Bearer {token}"}
    repo_id = sample_data["repo1"].id

    # 1. Test JSONL export endpoint
    resp = client.get(
        f"/api/v1/repositories/{repo_id}/analysis-runs/export?format=jsonl",
        headers=headers,
    )
    assert resp.status_code == 200
    assert "application/x-ndjson" in resp.headers["content-type"]
    assert f'filename="analysis-eval-{repo_id}.jsonl"' in resp.headers["content-disposition"]
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    assert len(lines) == 3

    # 2. Test JSON export endpoint
    resp_json = client.get(
        f"/api/v1/repositories/{repo_id}/analysis-runs/export?format=json",
        headers=headers,
    )
    assert resp_json.status_code == 200
    assert "application/json" in resp_json.headers["content-type"]
    data = resp_json.json()
    assert isinstance(data, list)
    assert len(data) == 3

    # 3. Test filter include_feedback_only
    resp_fb = client.get(
        f"/api/v1/repositories/{repo_id}/analysis-runs/export?format=json&include_feedback_only=true",
        headers=headers,
    )
    assert resp_fb.status_code == 200
    fb_data = resp_fb.json()
    assert len(fb_data) == 1
    assert fb_data[0]["id"] == str(sample_data["run_bugs"].id)

    # 4. Test Langfuse format export endpoint
    resp_lf = client.get(
        f"/api/v1/repositories/{repo_id}/analysis-runs/export?format=langfuse",
        headers=headers,
    )
    assert resp_lf.status_code == 200
    assert "application/x-ndjson" in resp_lf.headers["content-type"]
    assert f'filename="analysis-eval-{repo_id}-langfuse.jsonl"' in resp_lf.headers["content-disposition"]
    lf_lines = [l for l in resp_lf.text.strip().split("\n") if l.strip()]
    assert len(lf_lines) == 3
    sample_lf = json.loads(lf_lines[0])
    assert "input" in sample_lf
    assert "expected_output" in sample_lf
    assert "metadata" in sample_lf


def test_export_evaluation_dataset_langfuse_format(db_session: Session, sample_data: dict):
    """Test exporting runs formatted specifically for Langfuse datasets (input, expected_output, metadata)."""
    service = AnalysisRunHistoryService()
    repo1_id = sample_data["repo1"].id

    lf_output = service.export_evaluation_dataset(
        repo1_id,
        format="langfuse",
        db=db_session,
    )

    assert isinstance(lf_output, str)
    lines = [l for l in lf_output.strip().split("\n") if l.strip()]
    assert len(lines) == 3

    items = [json.loads(l) for l in lines]
    bug_item = next(i for i in items if i["id"] == str(sample_data["run_bugs"].id))

    # Verify Langfuse dataset item schema
    assert bug_item["input"]["feature_type"] == "detect_bugs"
    assert bug_item["input"]["target_path"] == "src/auth/tokens.py"
    assert "findings" in bug_item["expected_output"]
    assert bug_item["expected_output"]["findings_count"] == 2
    assert bug_item["metadata"]["repository_id"] == str(repo1_id)
    assert bug_item["metadata"]["feedback_summary"]["has_feedback"] is True


def test_export_evaluation_records_with_code_review_alias(db_session: Session, sample_data: dict):
    """Test that 'code_review' shorthand alias maps correctly to 'review' feature type."""
    service = AnalysisRunHistoryService()
    repo1_id = sample_data["repo1"].id

    review_records = service.export_evaluation_records(
        repo1_id,
        feature_type="code_review",
        db=db_session,
    )
    assert len(review_records) == 1
    assert review_records[0]["id"] == str(sample_data["run_review"].id)
    assert review_records[0]["feature_type"] == "review"


