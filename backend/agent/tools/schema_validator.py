"""JSON Schema Draft 2020-12 Validator for Unified Tool Registry.

Part of F21 — Tool router and tool policy bridge (Issue #201).
Provides standardized JSON Schema validation with security protections:
- Draft 2020-12 compliance with FormatChecker (with built-in pure-Python fallback when jsonschema is unavailable)
- Pre-compiled validator caching to prevent recompilation overhead
- Schema recursion/nesting depth bounding (prevents stack overflow / DoS)
- Remote reference rejection (blocks SSRF and external network requests)
- Deterministic, sanitized validation error messages
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import re
from typing import Any

from agent.tools.models import compute_schema_fingerprint

try:
    import jsonschema  # type: ignore[import-untyped]
    from jsonschema.validators import Draft202012Validator as _JsonSchemaDraft202012Validator  # type: ignore[import-untyped]

    _HAS_JSONSCHEMA = True
except ImportError:
    jsonschema = None  # type: ignore[assignment]
    _JsonSchemaDraft202012Validator = None  # type: ignore[assignment]
    _HAS_JSONSCHEMA = False

MAX_SCHEMA_DEPTH = 10
MAX_SCHEMA_PROPERTIES = 200

_VALID_JSON_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


class SchemaValidationError(Exception):
    """Raised when JSON schema compilation or validation fails."""

    pass


@dataclass
class _FallbackError:
    """Lightweight validation error compatible with jsonschema.ValidationError attributes."""

    validator: str
    message: str
    path: deque[str | int] = field(default_factory=deque)
    validator_value: Any = None


def _matches_json_type(instance: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(instance, dict)
    if expected_type == "array":
        return isinstance(instance, list)
    if expected_type == "string":
        return isinstance(instance, str)
    if expected_type == "boolean":
        return isinstance(instance, bool)
    if expected_type == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected_type == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if expected_type == "null":
        return instance is None
    return True


class _FallbackDraft202012Validator:
    """Pure-Python Draft 2020-12 validator fallback when jsonschema package is not installed."""

    def __init__(self, schema: dict[str, Any], format_checker: Any = None) -> None:
        self.schema = schema
        self.format_checker = format_checker

    @classmethod
    def check_schema(cls, schema: Any) -> None:
        if not isinstance(schema, dict):
            raise SchemaValidationError("Schema must be a dictionary object")
        cls._validate_schema_node(schema)

    @classmethod
    def _validate_schema_node(cls, node: dict[str, Any]) -> None:
        t = node.get("type")
        if t is not None:
            if isinstance(t, str):
                if t not in _VALID_JSON_TYPES:
                    raise SchemaValidationError(f"'{t}' is not valid under any of the given schemas")
            elif isinstance(t, list):
                if not t or not all(isinstance(x, str) and x in _VALID_JSON_TYPES for x in t):
                    raise SchemaValidationError(f"Invalid type array in schema: {t}")
            else:
                raise SchemaValidationError(f"Invalid 'type' specification in schema: {t!r}")

        req = node.get("required")
        if req is not None:
            if not isinstance(req, list) or not all(isinstance(x, str) for x in req):
                raise SchemaValidationError("'required' must be an array of strings")

        props = node.get("properties")
        if props is not None:
            if not isinstance(props, dict):
                raise SchemaValidationError("'properties' must be an object")
            for prop_schema in props.values():
                if not isinstance(prop_schema, dict):
                    raise SchemaValidationError("Property schema definition must be an object")
                cls._validate_schema_node(prop_schema)

        items = node.get("items")
        if isinstance(items, dict):
            cls._validate_schema_node(items)

    def iter_errors(self, instance: Any, _schema: dict[str, Any] | None = None, _path: tuple[str | int, ...] = ()) -> list[_FallbackError]:
        schema = self.schema if _schema is None else _schema
        errors: list[_FallbackError] = []
        if not isinstance(schema, dict):
            return errors

        expected_type = schema.get("type")
        if expected_type is not None:
            if isinstance(expected_type, str):
                if not _matches_json_type(instance, expected_type):
                    errors.append(
                        _FallbackError(
                            validator="type",
                            message=f"{instance!r} is not of type {expected_type!r}",
                            path=deque(_path),
                            validator_value=expected_type,
                        )
                    )
                    return errors
            elif isinstance(expected_type, list):
                if not any(_matches_json_type(instance, t) for t in expected_type):
                    errors.append(
                        _FallbackError(
                            validator="type",
                            message=f"{instance!r} is not of type {expected_type!r}",
                            path=deque(_path),
                            validator_value=expected_type,
                        )
                    )
                    return errors

        if "enum" in schema:
            allowed = schema["enum"]
            if isinstance(allowed, list) and instance not in allowed:
                errors.append(
                    _FallbackError(
                        validator="enum",
                        message=f"{instance!r} is not one of {allowed!r}",
                        path=deque(_path),
                        validator_value=allowed,
                    )
                )

        if "const" in schema and instance != schema["const"]:
            errors.append(
                _FallbackError(
                    validator="const",
                    message=f"{schema['const']!r} was expected",
                    path=deque(_path),
                    validator_value=schema["const"],
                )
            )

        if isinstance(instance, str):
            min_len = schema.get("minLength")
            if isinstance(min_len, int) and len(instance) < min_len:
                errors.append(
                    _FallbackError(
                        validator="minLength",
                        message=f"{instance!r} is too short (minimum length {min_len})",
                        path=deque(_path),
                        validator_value=min_len,
                    )
                )
            max_len = schema.get("maxLength")
            if isinstance(max_len, int) and len(instance) > max_len:
                errors.append(
                    _FallbackError(
                        validator="maxLength",
                        message=f"{instance!r} is too long (maximum length {max_len})",
                        path=deque(_path),
                        validator_value=max_len,
                    )
                )
            pattern = schema.get("pattern")
            if isinstance(pattern, str):
                if re.search(pattern, instance) is None:
                    errors.append(
                        _FallbackError(
                            validator="pattern",
                            message=f"{instance!r} does not match {pattern!r}",
                            path=deque(_path),
                            validator_value=pattern,
                        )
                    )

        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            minimum = schema.get("minimum")
            if isinstance(minimum, (int, float)) and instance < minimum:
                errors.append(
                    _FallbackError(
                        validator="minimum",
                        message=f"{instance} is less than the minimum of {minimum}",
                        path=deque(_path),
                        validator_value=minimum,
                    )
                )
            maximum = schema.get("maximum")
            if isinstance(maximum, (int, float)) and instance > maximum:
                errors.append(
                    _FallbackError(
                        validator="maximum",
                        message=f"{instance} is greater than the maximum of {maximum}",
                        path=deque(_path),
                        validator_value=maximum,
                    )
                )
            excl_min = schema.get("exclusiveMinimum")
            if isinstance(excl_min, (int, float)) and instance <= excl_min:
                errors.append(
                    _FallbackError(
                        validator="exclusiveMinimum",
                        message=f"{instance} is less than or equal to the minimum of {excl_min}",
                        path=deque(_path),
                        validator_value=excl_min,
                    )
                )
            excl_max = schema.get("exclusiveMaximum")
            if isinstance(excl_max, (int, float)) and instance >= excl_max:
                errors.append(
                    _FallbackError(
                        validator="exclusiveMaximum",
                        message=f"{instance} is greater than or equal to the maximum of {excl_max}",
                        path=deque(_path),
                        validator_value=excl_max,
                    )
                )

        any_of = schema.get("anyOf")
        if isinstance(any_of, list) and any_of:
            if not any(
                isinstance(sub, dict) and len(self.iter_errors(instance, sub, _path)) == 0
                for sub in any_of
            ):
                errors.append(
                    _FallbackError(
                        validator="anyOf",
                        message=f"{instance!r} is not valid under any of the given schemas",
                        path=deque(_path),
                        validator_value=any_of,
                    )
                )

        one_of = schema.get("oneOf")
        if isinstance(one_of, list) and one_of:
            valid_count = sum(
                1
                for sub in one_of
                if isinstance(sub, dict) and len(self.iter_errors(instance, sub, _path)) == 0
            )
            if valid_count != 1:
                errors.append(
                    _FallbackError(
                        validator="oneOf",
                        message=f"{instance!r} is not valid under exactly one of the given schemas",
                        path=deque(_path),
                        validator_value=one_of,
                    )
                )

        if isinstance(instance, dict):
            required = schema.get("required")
            if isinstance(required, list):
                for req_key in required:
                    if req_key not in instance:
                        errors.append(
                            _FallbackError(
                                validator="required",
                                message=f"'{req_key}' is a required property",
                                path=deque(_path),
                                validator_value=required,
                            )
                        )
            properties = schema.get("properties")
            defined_props = properties if isinstance(properties, dict) else {}
            additional = schema.get("additionalProperties", True)
            if additional is False:
                for key in instance:
                    if key not in defined_props:
                        errors.append(
                            _FallbackError(
                                validator="additionalProperties",
                                message=f"Additional properties are not allowed ('{key}' was unexpected)",
                                path=deque(_path),
                                validator_value=False,
                            )
                        )
            for key, subschema in defined_props.items():
                if key in instance and isinstance(subschema, dict):
                    errors.extend(self.iter_errors(instance[key], subschema, (*_path, key)))

        if isinstance(instance, list):
            min_items = schema.get("minItems")
            if isinstance(min_items, int) and len(instance) < min_items:
                errors.append(
                    _FallbackError(
                        validator="minItems",
                        message=f"{instance!r} is too short (minimum {min_items} items)",
                        path=deque(_path),
                        validator_value=min_items,
                    )
                )
            max_items = schema.get("maxItems")
            if isinstance(max_items, int) and len(instance) > max_items:
                errors.append(
                    _FallbackError(
                        validator="maxItems",
                        message=f"{instance!r} is too long (maximum {max_items} items)",
                        path=deque(_path),
                        validator_value=max_items,
                    )
                )
            items_schema = schema.get("items")
            if isinstance(items_schema, dict):
                for idx, item in enumerate(instance):
                    errors.extend(self.iter_errors(item, items_schema, (*_path, idx)))

        return errors


Draft202012Validator = _JsonSchemaDraft202012Validator if _HAS_JSONSCHEMA else _FallbackDraft202012Validator


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
        self._format_checker = jsonschema.FormatChecker() if _HAS_JSONSCHEMA else None
        self._validator_cache: dict[str, Any] = {}

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
        except SchemaValidationError:
            raise
        except Exception as exc:
            msg = getattr(exc, "message", str(exc))
            raise SchemaValidationError(f"Invalid JSON Schema Draft 2020-12 definition: {msg}") from exc

    def get_or_compile_validator(self, schema: dict[str, Any]) -> Any:
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
        errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
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

        errors = sorted(validator.iter_errors(output), key=lambda e: list(e.path))
        if not errors:
            return None

        err = errors[0]
        path_str = ".".join(str(p) for p in err.path) if err.path else "output"
        return f"Tool output violates output schema at {path_str}: {err.message}"


# Global shared validator instance
default_schema_validator = SchemaValidator()
