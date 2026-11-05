"""
Unit tests for AI Prompts subsystem and PromptBuilder integration.
Owner: Meet / Dev — W1-12
"""

from __future__ import annotations

import pytest
from ai.prompts import (
    PROMPT_REGISTRY,
    PromptMetadata,
    PromptNotFoundError,
    PromptRenderError,
    clear_prompt_cache,
    get_prompt_metadata,
    list_available_prompts,
    load_prompt,
    render_prompt,
)
from ai.schemas.prompt_builder import PromptBuilder


class TestPromptsSubsystem:
    def setup_method(self) -> None:
        clear_prompt_cache()

    def test_load_prompt_with_and_without_extension(self) -> None:
        text1 = load_prompt("chat_system")
        text2 = load_prompt("chat_system.txt")
        assert len(text1) > 0
        assert text1 == text2

    def test_load_prompt_caches_result(self) -> None:
        load_prompt("chat_system")
        info1 = load_prompt.cache_info()
        assert info1.hits == 0 or info1.misses == 1

        load_prompt("chat_system")
        info2 = load_prompt.cache_info()
        assert info2.hits >= 1

    def test_clear_prompt_cache(self) -> None:
        load_prompt("chat_system")
        clear_prompt_cache()
        info = load_prompt.cache_info()
        assert info.hits == 0
        assert info.misses == 0

    def test_load_prompt_nonexistent_raises_not_found(self) -> None:
        with pytest.raises(PromptNotFoundError):
            load_prompt("non_existent_prompt_template_xyz")

    def test_load_prompt_path_traversal_blocked(self) -> None:
        with pytest.raises(PromptNotFoundError):
            load_prompt("../../etc/passwd")

    def test_list_available_prompts_contains_core_templates(self) -> None:
        prompts = list_available_prompts()
        assert "chat_system" in prompts
        assert "summary_system" in prompts
        assert "grounding_system" in prompts
        assert "repair_system" in prompts

    def test_render_prompt_substitutes_variables(self) -> None:
        rendered = render_prompt(
            "repair_system",
            schema_name="RepositoryAnswer",
            error_message="Missing field 'answer'",
            invalid_content="{}",
        )
        assert "RepositoryAnswer" in rendered
        assert "Missing field 'answer'" in rendered

    def test_render_prompt_missing_key_raises_render_error(self) -> None:
        with pytest.raises(PromptRenderError):
            render_prompt("repair_system", schema_name="RepositoryAnswer")

    def test_get_prompt_metadata_registered_and_unregistered(self) -> None:
        meta = get_prompt_metadata("chat_system")
        assert meta is not None
        assert isinstance(meta, PromptMetadata)
        assert meta.prompt_id == "prompt-chat-sys-001"
        assert meta.version == "1.0.0"
        assert meta.capability == "chat"
        assert meta.owner == "AI Team"

        meta_with_ext = get_prompt_metadata("chat_system.txt")
        assert meta_with_ext == meta

        none_meta = get_prompt_metadata("unknown_prompt_xyz")
        assert none_meta is None

    def test_prompt_registry_covers_core_prompts(self) -> None:
        expected = [
            "chat_system",
            "repository_chat",
            "bug_detection_system",
            "code_review_system",
            "explanation_system",
            "test_generation_system",
            "test_planning_system",
            "test_review_system",
            "repair_system",
            "grounding_system",
        ]
        for name in expected:
            assert name in PROMPT_REGISTRY
            meta = PROMPT_REGISTRY[name]
            assert meta.prompt_id.startswith("prompt-")
            assert meta.version
            assert meta.capability

    def test_render_prompt_user_templates_with_placeholders(self) -> None:
        chat_rendered = render_prompt(
            "repository_chat",
            file_path="src/main.py",
            start_line=1,
            end_line=20,
            repository_context="def run(): pass",
            question="What does run do?",
        )
        assert "src/main.py" in chat_rendered
        assert "What does run do?" in chat_rendered

        ctx_rendered = render_prompt(
            "context_summary",
            file_path="src/utils.py",
            start_line=10,
            end_line=30,
            code_content="def helper(): return True",
        )
        assert "src/utils.py" in ctx_rendered
        assert "def helper()" in ctx_rendered

        ground_rendered = render_prompt(
            "source_grounding",
            verified_file_list="src/auth.py",
            answer="Handles login",
            claimed_sources="src/auth.py:1-10",
        )
        assert "Handles login" in ground_rendered
        assert "src/auth.py" in ground_rendered


class TestPromptBuilderExtended:
    def test_build_chat_prompt_respects_custom_system_instruction(self) -> None:
        builder = PromptBuilder()
        custom_system = "You are a custom security auditor."
        messages = builder.build_chat_prompt(
            context="int x = 1;",
            question="Is this safe?",
            system_instruction=custom_system,
        )
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[0].content == custom_system

    def test_build_grounding_prompt(self) -> None:
        builder = PromptBuilder()
        messages = builder.build_grounding_prompt(
            verified_files="src/auth.py lines 1-50",
            answer="Auth is in src/auth.py",
            claimed_sources="src/auth.py:1-50",
        )
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        assert "VERIFIED REPOSITORY FILES:" in messages[1].content
        assert "Auth is in src/auth.py" in messages[1].content

    def test_build_repair_prompt(self) -> None:
        builder = PromptBuilder()
        messages = builder.build_repair_prompt(
            schema_name="RepositoryAnswer",
            validation_error="Field required",
            invalid_content="{ broken }",
        )
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert "RepositoryAnswer" in messages[1].content
        assert "Field required" in messages[1].content
