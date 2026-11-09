"""Unit tests for SchemaValidator.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Tests:
- Standardized Draft 2020-12 compilation and validation
- Pre-compiled validator caching to prevent recompilation
- Recursion depth and properties limit enforcement (DoS prevention)
- Remote reference rejection (SSRF prevention)
- Input argument validation with accurate path reporting
- Output schema validation
- Deterministic schema fingerprinting
"""

import pytest

from agent.tools.models import compute_schema_fingerprint
from agent.tools.schema_validator import (
    MAX_SCHEMA_DEPTH,
    MAX_SCHEMA_PROPERTIES,
    SchemaValidationError,
    SchemaValidator,
)


@pytest.fixture
def validator() -> SchemaValidator:
    return SchemaValidator()


def test_valid_draft_202012_schema_compilation(validator: SchemaValidator) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "minLength": 1},
            "line_number": {"type": "integer", "minimum": 1},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["file_path"],
        "additionalProperties": False,
    }

    v = validator.get_or_compile_validator(schema)
    assert v is not None
    assert validator.cache_size == 1

    # Second call must reuse cached validator instance
    v2 = validator.get_or_compile_validator(schema)
    assert v2 is v
    assert validator.cache_size == 1


def test_reject_schema_exceeding_max_depth(validator: SchemaValidator) -> None:
    # Build deep schema of depth > 10
    deep_schema = {"type": "string"}
    for _ in range(MAX_SCHEMA_DEPTH + 2):
        deep_schema = {"type": "object", "properties": {"child": deep_schema}}

    with pytest.raises(SchemaValidationError) as exc_info:
        validator.validate_schema_definition(deep_schema, is_input=True)

    assert "maximum allowed nesting depth" in str(exc_info.value)


def test_reject_remote_schema_references(validator: SchemaValidator) -> None:
    schema_with_http_ref = {
        "type": "object",
        "properties": {
            "payload": {
                "$ref": "https://malicious-external-site.com/schema.json",
            }
        },
    }

    with pytest.raises(SchemaValidationError) as exc_info:
        validator.validate_schema_definition(schema_with_http_ref, is_input=True)

    assert "Remote external $ref references are forbidden" in str(exc_info.value)


def test_validate_arguments_missing_required(validator: SchemaValidator) -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["name", "count"],
    }

    err = validator.validate_arguments({"name": "alpha"}, schema)
    assert err is not None
    assert "Missing required argument" in err
    assert "count" in err


def test_validate_arguments_type_mismatch(validator: SchemaValidator) -> None:
    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
        },
        "required": ["count"],
    }

    err = validator.validate_arguments({"count": "ten"}, schema)
    assert err is not None
    assert "must be of type integer" in err


def test_validate_arguments_enum_constraint(validator: SchemaValidator) -> None:
    schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "stop", "restart"]},
        },
        "required": ["action"],
    }

    err_invalid = validator.validate_arguments({"action": "pause"}, schema)
    assert err_invalid is not None
    assert "must be one of ['start', 'stop', 'restart']" in err_invalid

    err_valid = validator.validate_arguments({"action": "restart"}, schema)
    assert err_valid is None


def test_validate_arguments_additional_properties_rejection(validator: SchemaValidator) -> None:
    schema = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
        },
        "additionalProperties": False,
    }

    err = validator.validate_arguments({"key": "val", "unexpected_field": True}, schema)
    assert err is not None
    assert "Unexpected argument" in err


def test_output_schema_validation(validator: SchemaValidator) -> None:
    out_schema = {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "bytes_written": {"type": "integer"},
        },
        "required": ["success", "bytes_written"],
    }

    # Valid output
    assert validator.validate_output({"success": True, "bytes_written": 128}, out_schema) is None

    # Invalid output (missing required bytes_written)
    err = validator.validate_output({"success": True}, out_schema)
    assert err is not None
    assert "violates output schema" in err and "bytes_written" in err


def test_deterministic_schema_fingerprint() -> None:
    schema_a = {"properties": {"a": {"type": "string"}, "b": {"type": "integer"}}, "type": "object"}
    schema_b = {"type": "object", "properties": {"b": {"type": "integer"}, "a": {"type": "string"}}}

    fp_a = compute_schema_fingerprint(schema_a)
    fp_b = compute_schema_fingerprint(schema_b)

    assert fp_a != ""
    assert fp_a == fp_b  # Keys sorted canonically produce identical fingerprints
