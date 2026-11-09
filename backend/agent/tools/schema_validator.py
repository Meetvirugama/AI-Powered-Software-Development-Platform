"""JSON Schema Draft 2020-12 Validator for Unified Tool Registry.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Provides standardized JSON Schema validation with security protections:
- Draft 2020-12 compliance with FormatChecker
- Pre-compiled validator caching to prevent recompilation overhead
- Schema recursion/nesting depth bounding (prevents stack overflow / DoS)
- Remote reference rejection (blocks SSRF and external network requests)
- Deterministic, sanitized validation error messages
"""

from __future__ import annotations

import json
import re
from typing import Any
import jsonschema
from jsonschema.validators import Draft202012Validator

from agent.tools.models import compute_schema_fingerprint

MAX_SCHEMA_DEPTH = 10
MAX_SCHEMA_PROPERTIES = 200


class SchemaValidationError(Exception):
    """Raised when JSON schema compilation or validation fails."""
    pass


def _check_nesting_depth_and_refs(node: Any, current_depth: int = 1) -> None:
    """Recursively enforce maximum schema nesting depth and reject remote $ref references."""
    if current_depth > MAX_SCHEMA_DEPTH:
        raise SchemaValidationError(f"Schema exceeds maximum allowed nesting depth of {MAX_SCHEMA_DEPTH}")

    if isinstance(node, dict):
        if len(node) > MAX_SCHEMA_PROPERTIES:
            raise SchemaValidationError(f"Schema object exceeds maximum property limit ({MAX_SCHEMA_PROPERTIES})")

        for key, val in node.items():
            if key == "$ref" and isinstance(val, str):
                val_clean = val.strip().lower()
                # Reject remote HTTP/HTTPS/FTP/file schemas
                if any(val_clean.startswith(prefix) for prefix in ("http://", "https://", "ftp://", "file://", "//")):
                    raise SchemaValidationError(f"Remote external $ref references are forbidden for security: '{val}'")
            if isinstance(val, (dict, list)):
                _check_nesting_depth_and_refs(val, current_depth + 1)

    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                _check_nesting_depth_and_refs(item, current_depth + 1)


class SchemaValidator:
    """Standardized Draft 2020-12 validator with compilation caching and security controls."""

    def __init__(self) -> None:
        self._format_checker = jsonschema.FormatChecker()
        self._validator_cache: dict[str, Draft202012Validator] = {}

    @property
    def cache_size(self) -> int:
        """Number of compiled schema validators currently cached in memory."""
        return len(self._validator_cache)

    def validate_schema_definition(self, schema: dict[str, Any], is_input: bool = True) -> None:
        """Validate that a schema is structurally valid Draft 2020-12 and adheres to security limits."""
        if not isinstance(schema, dict):
            raise SchemaValidationError("Schema must be a dictionary object")

        if is_input and schema.get("type") != "object":
            raise SchemaValidationError("Tool input schema must declare top-level type 'object'")

        # Enforce nesting depth and reject remote refs
        _check_nesting_depth_and_refs(schema)

        # Check Draft 2020-12 syntax
        try:
            Draft202012Validator.check_schema(schema)
        except jsonschema.exceptions.SchemaError as exc:
            raise SchemaValidationError(f"Invalid JSON Schema Draft 2020-12 definition: {exc.message}") from exc

    def get_or_compile_validator(self, schema: dict[str, Any]) -> Draft202012Validator:
        """Retrieve pre-compiled validator from cache or compile and cache a new instance."""
        fp = compute_schema_fingerprint(schema)
        if fp in self._validator_cache:
            return self._validator_cache[fp]

        self.validate_schema_definition(schema, is_input=False)
        try:
            validator = Draft202012Validator(schema, format_checker=self._format_checker)
            self._validator_cache[fp] = validator
            return validator
        except Exception as exc:
            raise SchemaValidationError(f"Failed to compile JSON Schema validator: {exc}") from exc

    def validate_arguments(self, arguments: dict[str, Any], schema: dict[str, Any]) -> str | None:
        """Validate request arguments against input schema. Returns None on success or sanitized error string."""
        if not isinstance(arguments, dict):
            return "Tool arguments must be an object"

        try:
            validator = self.get_or_compile_validator(schema)
        except SchemaValidationError as exc:
            return f"Schema definition error: {exc}"

        # Collect first validation error with sanitized path
        errors = sorted(validator.iter_errors(arguments), key=lambda e: e.path)
        if not errors:
            return None

        err = errors[0]
        path_str = ".".join(str(p) for p in err.path) if err.path else "arguments"

        if err.validator == "required":
            missing = err.validator_value[0] if isinstance(err.validator_value, list) and err.validator_value else ""
            for prop in getattr(err, "validator_value", []):
                if prop not in arguments:
                    missing = prop
                    break
            return f"Missing required argument: arguments.{missing}" if missing else f"Missing required argument in {path_str}"

        if err.validator == "additionalProperties":
            extra_match = re.search(r"'([^']+)' was unexpected", err.message)
            extra_key = extra_match.group(1) if extra_match else ""
            full_path = f"{path_str}.{extra_key}" if extra_key else path_str
            return f"Unexpected argument: {full_path}"

        if err.validator == "type":
            expected = err.validator_value
            return f"{path_str} must be of type {expected}"

        if err.validator == "enum":
            return f"{path_str} must be one of {err.validator_value}"

        return f"Validation error at {path_str}: {err.message}"

    def validate_output(self, output: Any, schema: dict[str, Any] | None) -> str | None:
        """Validate tool execution output against output schema if configured. Returns None on success."""
        if schema is None:
            return None

        try:
            validator = self.get_or_compile_validator(schema)
        except SchemaValidationError as exc:
            return f"Output schema error: {exc}"

        errors = sorted(validator.iter_errors(output), key=lambda e: e.path)
        if not errors:
            return None

        err = errors[0]
        path_str = ".".join(str(p) for p in err.path) if err.path else "output"
        return f"Tool output violates output schema at {path_str}: {err.message}"


# Global shared validator instance
default_schema_validator = SchemaValidator()
