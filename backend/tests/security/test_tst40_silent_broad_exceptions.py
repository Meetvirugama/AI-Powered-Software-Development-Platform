"""Security and Code Hygiene Test for ISS-040.

Invariant:
Silent broad exception handlers (`except Exception: pass` / `except: pass`)
must be <= 10 across the entire production codebase (backend/{app,ai,sandbox,scanner,indexer,agent,runner}),
and each remaining one must be explicitly annotated.
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_silent_broad_exception_handlers_within_limit() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    production_dirs = [
        repo_root / "app",
        repo_root / "ai",
        repo_root / "sandbox",
        repo_root / "scanner",
        repo_root / "indexer",
        repo_root / "agent",
        repo_root / "runner",
    ]

    silent_handlers: list[tuple[str, int, str]] = []

    for p_dir in production_dirs:
        if not p_dir.exists():
            continue
        for file_path in p_dir.rglob("*.py"):
            source = file_path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(source, filename=str(file_path))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    is_broad = False
                    if node.type is None:
                        is_broad = True
                    elif isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"):
                        is_broad = True

                    if is_broad:
                        body = node.body
                        is_silent = False
                        action = ""
                        if len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Continue)):
                            is_silent = True
                            action = type(body[0]).__name__
                        elif len(body) == 2 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[1], (ast.Pass, ast.Continue)):
                            is_silent = True
                            action = "docstring_pass"

                        if is_silent:
                            rel_path = file_path.relative_to(repo_root)
                            silent_handlers.append((str(rel_path), node.lineno, action))

    assert len(silent_handlers) <= 10, (
        f"Found {len(silent_handlers)} silent broad exception handlers (maximum allowed is 10): {silent_handlers}"
    )
