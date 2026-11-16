"""Security and Configuration Test: AST Audit of Settings getattr calls (TST-28 / ISS-007).

Asserts that every `getattr(settings, "x", ...)` call across production backend code
targets a valid, registered field or property in `app.core.config.Settings`.
Prevents silent typos, unregistered configuration flags, and dead settings.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.core.config import Settings


def test_tst28_every_getattr_settings_targets_valid_model_field() -> None:
    """Every getattr(settings, 'attr', ...) in production code must exist on Settings."""
    backend_dir = Path(__file__).resolve().parents[2]
    valid_fields = set(Settings.model_fields.keys()) | {
        p for p in dir(Settings) if isinstance(getattr(Settings, p, None), property)
    }

    unmatched: list[tuple[str, int, str]] = []

    for py_path in backend_dir.rglob("*.py"):
        if "tests" in py_path.parts:
            continue
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "settings"
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                attr_name = node.args[1].value
                if attr_name not in valid_fields:
                    rel_path = str(py_path.relative_to(backend_dir))
                    unmatched.append((rel_path, node.lineno, attr_name))

    assert (
        not unmatched
    ), f"Found {len(unmatched)} getattr(settings, ...) calls with unregistered attributes: {unmatched}"
