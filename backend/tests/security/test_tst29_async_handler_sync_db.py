"""TST-29 / ISS-009 — Async handler audit for event loop blocking by sync DB I/O.

Ensures that handlers doing synchronous database I/O are either:
1. Declared as standard `def` routes so FastAPI automatically dispatches them
   to worker threads via AnyIO threadpool (preventing main event loop stalls).
2. For `async def` routes, ensuring any synchronous DB calls are offloaded
   via `asyncio.to_thread` or `run_in_threadpool`.
"""

import ast
from pathlib import Path
import pytest


def test_tst29_no_pure_sync_routes_declared_async():
    """Verify that no route depending on get_db is declared async def if it has 0 awaits.

    In FastAPI, declaring a function that performs synchronous database operations
    as `async def` causes it to run directly on the single-threaded asyncio event loop,
    blocking all other concurrent requests, SSE streams, and health checks.
    """
    api_dir = Path("backend/app/api")
    assert api_dir.is_dir(), f"API directory not found: {api_dir}"

    violators = []
    for py_file in api_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                has_db_dep = any(
                    "get_db" in ast.dump(default)
                    for default in node.args.defaults
                )
                if has_db_dep:
                    awaits = [
                        n for n in ast.walk(node)
                        if isinstance(n, (ast.Await, ast.AsyncWith, ast.AsyncFor))
                    ]
                    if len(awaits) == 0:
                        violators.append(f"{py_file.name}:{node.lineno} async def {node.name}")

    assert not violators, (
        f"Found {len(violators)} pure synchronous route(s) declared as async def, "
        f"which blocks the asyncio event loop during sync DB I/O (ISS-009 / TST-29):\n"
        + "\n".join(f"  - {v}" for v in violators)
    )
