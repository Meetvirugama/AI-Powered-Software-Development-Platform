"""Tests for EditSynthesizer & Search/Replace Patch Engine (Issue #202 / Issue #203).

Covers:
1. Structured output parsing & validation (Stage A)
2. Exact single-match enforcement (Stage B)
3. Path guard and plan-bound scope validation (Stage C)
4. In-memory patch application and atomic multi-block changes (Stage D)
5. Multi-language syntax validation (Python AST, JSON) (Stage E)
6. Stale content detection & revision fingerprinting
7. Bounded self-refinement (retries on validation failure up to 3 attempts)
8. AgentExecutionLoop integration (payload priority, synthesis trigger, cross-step isolation)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai.services.agent_execution_loop import (
    AgentExecutionLoop,
    StepExecutionStatus,
)
from ai.services.edit_synthesizer import (
    EditBlock,
    EditSynthesizer,
    EditSynthesisResult,
)
from app.schemas.plan import PlanStep
from app.schemas.workspace import WorkspaceStatus


# ---------------------------------------------------------------------------
# Stage A: Structured Output Validation Tests
# ---------------------------------------------------------------------------

def test_validate_structured_output_valid():
    raw = json.dumps({
        "explanation": "Added input check",
        "edits": [
            {"file": "src/app.py", "search": "def run():", "replace": "def run():\n    check()"}
        ]
    })
    parsed, err = EditSynthesizer.validate_structured_output(raw)
    assert err is None
    assert parsed is not None
    assert len(parsed["edits"]) == 1
    assert parsed["edits"][0]["file"] == "src/app.py"


def test_validate_structured_output_markdown_fence():
    raw = "```json\n" + json.dumps({
        "explanation": "Markdown fenced",
        "edits": [{"file": "src/test.py", "search": "pass", "replace": "return True"}]
    }) + "\n```"
    parsed, err = EditSynthesizer.validate_structured_output(raw)
    assert err is None
    assert parsed is not None
    assert parsed["explanation"] == "Markdown fenced"


def test_validate_structured_output_invalid_json():
    parsed, err = EditSynthesizer.validate_structured_output("not valid json {")
    assert parsed is None
    assert "Failed to parse LLM output as JSON" in err


def test_validate_structured_output_missing_fields():
    # Missing edits list
    parsed, err = EditSynthesizer.validate_structured_output(json.dumps({"explanation": "no edits"}))
    assert parsed is None
    assert "must include an 'edits' list" in err

    # Empty edits list
    parsed, err = EditSynthesizer.validate_structured_output(json.dumps({"edits": []}))
    assert parsed is None
    assert "cannot be empty" in err

    # Missing search or replace
    bad_edit = json.dumps({"edits": [{"file": "a.py", "search": "x"}]})
    parsed, err = EditSynthesizer.validate_structured_output(bad_edit)
    assert parsed is None
    assert "missing 'replace'" in err


# ---------------------------------------------------------------------------
# Stage B: Exact Single-Match Validation Tests
# ---------------------------------------------------------------------------

def test_exact_single_match_success():
    edits = [EditBlock(file="a.py", search="def foo():\n    return 1", replace="def foo():\n    return 2")]
    contents = {"a.py": "import os\n\ndef foo():\n    return 1\n\ndef bar():\n    return 0"}
    ok, err = EditSynthesizer.validate_exact_match(edits, contents)
    assert ok is True
    assert err is None


def test_zero_match_rejection():
    edits = [EditBlock(file="a.py", search="def non_existent():", replace="def bar():")]
    contents = {"a.py": "def foo():\n    return 1"}
    ok, err = EditSynthesizer.validate_exact_match(edits, contents)
    assert ok is False
    assert "Search block not found" in err


def test_multiple_match_rejection():
    edits = [EditBlock(file="a.py", search="return True", replace="return False")]
    contents = {"a.py": "def foo():\n    return True\ndef bar():\n    return True"}
    ok, err = EditSynthesizer.validate_exact_match(edits, contents)
    assert ok is False
    assert "Ambiguous search block" in err
    assert "matches 2 occurrences" in err


# ---------------------------------------------------------------------------
# Stage C: Path Validation Tests
# ---------------------------------------------------------------------------

def test_path_traversal_rejection():
    edits = [EditBlock(file="../secret.py", search="x", replace="y")]
    ok, err = EditSynthesizer.validate_paths(edits, ["../secret.py"])
    assert ok is False
    assert "Unsafe file path" in err


def test_forbidden_file_rejection():
    edits = [EditBlock(file="sub/.env", search="x", replace="y")]
    ok, err = EditSynthesizer.validate_paths(edits, ["sub/.env"])
    assert ok is False
    assert "forbidden" in err.lower()


def test_plan_bound_scope_violation_rejection():
    edits = [EditBlock(file="src/unapproved.py", search="x", replace="y")]
    ok, err = EditSynthesizer.validate_paths(edits, ["src/approved.py"])
    assert ok is False
    assert "Plan-bound scope violation" in err


# ---------------------------------------------------------------------------
# Stage D & E: Patch Application & Syntax Validation Tests
# ---------------------------------------------------------------------------

def test_patch_application_and_syntax_validation():
    edits = [
        EditBlock(
            file="src/calc.py",
            search="def add(a, b):\n    return a - b",
            replace="def add(a, b):\n    return a + b",
        )
    ]
    contents = {"src/calc.py": "def add(a, b):\n    return a - b\n"}
    ok_apply, simulated, err_apply = EditSynthesizer.validate_patch_application(edits, contents)
    assert ok_apply is True
    assert simulated["src/calc.py"] == "def add(a, b):\n    return a + b\n"

    ok_syntax, err_syntax = EditSynthesizer.validate_syntax(simulated)
    assert ok_syntax is True
    assert err_syntax is None


def test_syntax_validation_catches_python_syntax_error():
    simulated = {"src/bad.py": "def syntax_error(:\n    pass\n"}
    ok, err = EditSynthesizer.validate_syntax(simulated)
    assert ok is False
    assert "Python syntax error in 'src/bad.py'" in err


def test_syntax_validation_catches_json_syntax_error():
    simulated = {"config.json": '{"unclosed": "brace"'}
    ok, err = EditSynthesizer.validate_syntax(simulated)
    assert ok is False
    assert "JSON syntax error in 'config.json'" in err


# ---------------------------------------------------------------------------
# Stale Content Detection Tests
# ---------------------------------------------------------------------------

def test_stale_content_detected_when_workspace_mutates():
    ws_mock = MagicMock()
    ws_mock.read_file.return_value = MagicMock(content="new content after edit")

    initial_hashes = {"src/app.py": "old_hash_123"}
    ok, err = EditSynthesizer.verify_no_stale_content(initial_hashes, ws_mock, "task-1")
    assert ok is False
    assert "Stale content detected" in err


# ---------------------------------------------------------------------------
# Bounded Self-Refinement Tests (Reflexion / Self-Refine)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_self_refinement_succeeds_on_second_attempt():
    ws_mock = MagicMock()
    ws_mock.read_file.return_value = MagicMock(success=True, content="def calculate():\n    return 0\n")

    # Mock gateway returning invalid syntax first, then valid syntax on retry
    mock_gateway = MagicMock()
    first_resp = MagicMock(content=json.dumps({
        "explanation": "Bad syntax attempt",
        "edits": [{"file": "calc.py", "search": "return 0", "replace": "return 0 +"}]
    }))
    second_resp = MagicMock(content=json.dumps({
        "explanation": "Corrected attempt",
        "edits": [{"file": "calc.py", "search": "return 0", "replace": "return 42"}]
    }))
    mock_gateway.generate = AsyncMock(side_effect=[first_resp, second_resp])

    synthesizer = EditSynthesizer(llm_gateway=mock_gateway, max_attempts=3)
    step = PlanStep(step_id="step-1", title="Fix calc", description="Update return value", expected_files=["calc.py"])

    res = await synthesizer.synthesize("task-123", step, ws_mock, allowed_files=["calc.py"])

    assert res.status == "VALIDATED"
    assert res.attempts == 2
    assert res.applied is True
    ws_mock.write_file.assert_called_once_with("task-123", "calc.py", "def calculate():\n    return 42\n", create_parents=True)


@pytest.mark.asyncio
async def test_self_refinement_fails_when_retry_budget_exhausted():
    ws_mock = MagicMock()
    ws_mock.read_file.return_value = MagicMock(success=True, content="def calculate():\n    return 0\n")

    mock_gateway = MagicMock()
    bad_resp = MagicMock(content=json.dumps({
        "explanation": "Always bad syntax",
        "edits": [{"file": "calc.py", "search": "return 0", "replace": "return 0 +"}]
    }))
    mock_gateway.generate = AsyncMock(return_value=bad_resp)

    synthesizer = EditSynthesizer(llm_gateway=mock_gateway, max_attempts=3)
    step = PlanStep(step_id="step-1", title="Fix calc", description="Update return value", expected_files=["calc.py"])

    res = await synthesizer.synthesize("task-123", step, ws_mock, allowed_files=["calc.py"])

    assert res.status == "FAILED"
    assert res.attempts == 3
    assert "retry budget exhausted" in res.error_message
    ws_mock.write_file.assert_not_called()


# ---------------------------------------------------------------------------
# AgentExecutionLoop Integration & Payload Isolation Tests
# ---------------------------------------------------------------------------

def test_agent_loop_caller_payload_takes_priority():
    mock_ws = MagicMock()
    mock_ws.get_workspace.return_value = MagicMock(status=WorkspaceStatus.IN_USE)
    mock_synth = MagicMock()

    loop = AgentExecutionLoop(workspace_manager=mock_ws, edit_synthesizer=mock_synth)
    step = PlanStep(step_id="step-1", title="Write file", description="Write code", action_type="edit", expected_files=["app.py"])

    res = loop.execute_plan(
        task_id="task-123",
        plan=[step],
        step_payloads={"step-1": {"content": "caller provided content"}},
    )

    assert res.status == StepExecutionStatus.COMPLETED
    mock_ws.write_file.assert_called_once_with(task_id="task-123", file_path="app.py", content="caller provided content", create_parents=True)
    mock_synth.synthesize_sync.assert_not_called()


def test_agent_loop_missing_payload_triggers_synthesizer():
    mock_ws = MagicMock()
    mock_ws.get_workspace.return_value = MagicMock(status=WorkspaceStatus.IN_USE)

    mock_synth = MagicMock()
    mock_synth.synthesize_sync.return_value = EditSynthesisResult(
        step_id="step-1",
        status="VALIDATED",
        edits=[EditBlock(file="app.py", search="", replace="synthesized code")],
        explanation="Synthesized",
        attempts=1,
        changed_files=["app.py"],
        applied=True,
    )

    loop = AgentExecutionLoop(workspace_manager=mock_ws, edit_synthesizer=mock_synth)
    step = PlanStep(step_id="step-1", title="Auto step", description="Synthesize", action_type="edit", expected_files=["app.py"])

    res = loop.execute_plan(
        task_id="task-123",
        plan=[step],
        step_payloads={},  # No payload provided!
    )

    assert res.status == StepExecutionStatus.COMPLETED
    mock_synth.synthesize_sync.assert_called_once()
    assert res.steps_executed[0].synthesis_attempts == 1
    assert res.steps_executed[0].changed_files == ["app.py"]


def test_agent_loop_cross_step_content_fallback_is_eliminated():
    """Verify that Step 2 does NOT inherit Step 1's content payload."""
    mock_ws = MagicMock()
    mock_ws.get_workspace.return_value = MagicMock(status=WorkspaceStatus.IN_USE)

    # loop without synthesizer should fail closed on step-2 because step-2 has no payload
    loop = AgentExecutionLoop(workspace_manager=mock_ws, edit_synthesizer=None)
    step1 = PlanStep(step_id="step-1", title="Step 1", description="Init", action_type="edit", expected_files=["f1.py"])
    step2 = PlanStep(step_id="step-2", title="Step 2", description="Update", action_type="edit", expected_files=["f2.py"])

    res = loop.execute_plan(
        task_id="task-123",
        plan=[step1, step2],
        step_payloads={"step-1": {"content": "step 1 content"}},  # Only step 1 has content
    )

    assert res.status == StepExecutionStatus.FAILED
    assert "step 'step-2'" in res.error_message
    assert "No content payload provided" in res.error_message
    # f1.py was written with step 1 content, but f2.py was NEVER written with step 1 content!
    written_files = [call.kwargs.get("file_path") for call in mock_ws.write_file.call_args_list]
    assert "f1.py" in written_files
    assert "f2.py" not in written_files

