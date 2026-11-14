"""Unit and integration tests for F39: Amortized static scanner subprocess execution and parallel analysis."""

import json
import subprocess
import unittest
from unittest.mock import AsyncMock, patch

from review.static_reviewer import StaticReviewer
from scanner.static_bug_scanner import StaticBugScanner


class TestAmortizedStaticReviewer(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reviewer = StaticReviewer()

    def test_run_scanner_single_target_backward_compatibility(self):
        with patch("review.static_reviewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps([
                    {"code": "E501", "message": "Line too long", "filename": "app.py", "location": {"row": 10}}
                ]),
                stderr="",
            )
            res = self.reviewer.run_scanner("ruff", "app.py")
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["rule_id"], "E501")
            self.assertEqual(res[0]["file_path"], "app.py")
            self.assertEqual(res[0]["scanner"], "ruff")

            # Check that command placed '--' before app.py
            cmd = mock_run.call_args[0][0]
            self.assertIn("--", cmd)
            self.assertEqual(cmd[-1], "app.py")

    def test_run_scanner_batch_targets_ruff(self):
        with patch("review.static_reviewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps([
                    {"code": "F401", "message": "Unused import", "filename": "a.py", "location": {"row": 1}},
                    {"code": "E302", "message": "Expected 2 blank lines", "filename": "b.py", "location": {"row": 5}},
                ]),
                stderr="",
            )
            res = self.reviewer.run_scanner("ruff", ["a.py", "b.py"])
            self.assertEqual(len(res), 2)
            self.assertEqual(res[0]["file_path"], "a.py")
            self.assertEqual(res[1]["file_path"], "b.py")

            cmd = mock_run.call_args[0][0]
            self.assertIn("--", cmd)
            dash_idx = cmd.index("--")
            self.assertEqual(cmd[dash_idx + 1:], ["a.py", "b.py"])

    def test_run_scanner_batch_targets_bandit(self):
        with patch("review.static_reviewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({
                    "results": [
                        {
                            "test_id": "B101",
                            "issue_severity": "HIGH",
                            "issue_text": "Use of assert",
                            "filename": "f1.py",
                            "line_number": 12,
                        },
                        {
                            "test_id": "B301",
                            "issue_severity": "MEDIUM",
                            "issue_text": "Pickle usage",
                            "filename": "f2.py",
                            "line_number": 42,
                        },
                    ]
                }),
                stderr="",
            )
            res = self.reviewer.run_scanner("bandit", ["f1.py", "f2.py"])
            self.assertEqual(len(res), 2)
            self.assertEqual(res[0]["rule_id"], "B101")
            self.assertEqual(res[0]["file_path"], "f1.py")
            self.assertEqual(res[0]["severity"], "high")
            self.assertEqual(res[1]["rule_id"], "B301")
            self.assertEqual(res[1]["file_path"], "f2.py")
            self.assertEqual(res[1]["severity"], "medium")

    def test_run_scanner_batch_targets_eslint(self):
        with patch("review.static_reviewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps([
                    {
                        "filePath": "src/App.tsx",
                        "messages": [
                            {"ruleId": "no-unused-vars", "severity": 2, "message": "x is unused", "line": 4}
                        ],
                    },
                    {
                        "filePath": "src/index.ts",
                        "messages": [
                            {"ruleId": "semi", "severity": 1, "message": "Missing semicolon", "line": 8}
                        ],
                    },
                ]),
                stderr="",
            )
            res = self.reviewer.run_scanner("eslint", ["src/App.tsx", "src/index.ts"])
            self.assertEqual(len(res), 2)
            self.assertEqual(res[0]["file_path"], "src/App.tsx")
            self.assertEqual(res[0]["severity"], "high")
            self.assertEqual(res[1]["file_path"], "src/index.ts")
            self.assertEqual(res[1]["severity"], "low")

    def test_run_scanner_batch_targets_biome(self):
        with patch("review.static_reviewer.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({
                    "diagnostics": [
                        {
                            "category": "lint/correctness/noUnusedVariables",
                            "severity": "error",
                            "description": "Unused var",
                            "location": {
                                "path": {"file": "src/a.ts"},
                                "lines": {"start": 10},
                            },
                        },
                        {
                            "category": "lint/style/useConst",
                            "severity": "warning",
                            "description": "Use const",
                            "location": {
                                "path": {"file": "src/b.ts"},
                                "lines": {"start": 20},
                            },
                        },
                    ]
                }),
                stderr="",
            )
            res = self.reviewer.run_scanner("biome", ["src/a.ts", "src/b.ts"])
            self.assertEqual(len(res), 2)
            self.assertEqual(res[0]["file_path"], "src/a.ts")
            self.assertEqual(res[0]["severity"], "high")
            self.assertEqual(res[1]["file_path"], "src/b.ts")
            self.assertEqual(res[1]["severity"], "low")

    def test_unsafe_targets_rejected_in_batch(self):
        # Empty sequence
        with self.assertRaises(ValueError):
            self.reviewer.run_scanner("ruff", [])

        # Option flag injection in batch
        with self.assertRaises(ValueError):
            self.reviewer.run_scanner("ruff", ["safe.py", "--config", "evil.toml"])

        # Leading dash
        with self.assertRaises(ValueError):
            self.reviewer.run_scanner("bandit", ["safe.py", "-s"])

        # Null byte in batch
        with self.assertRaises(ValueError):
            self.reviewer.run_scanner("eslint", ["safe.js", "evil\x00.js"])

        # Non string sequence
        with self.assertRaises((ValueError, TypeError)):
            self.reviewer.run_scanner("ruff", 123)  # type: ignore

    def test_group_files_by_scanner_partitioning(self):
        grouped = self.reviewer._group_files_by_scanner(
            ["app/main.py", "app/utils.py", "frontend/App.tsx", "frontend/style.css"]
        )
        self.assertIn("ruff", grouped)
        self.assertIn("bandit", grouped)
        self.assertIn("eslint", grouped)
        self.assertIn("biome", grouped)

        self.assertEqual(grouped["ruff"], ["app/main.py", "app/utils.py"])
        self.assertEqual(grouped["bandit"], ["app/main.py", "app/utils.py"])
        self.assertEqual(grouped["eslint"], ["frontend/App.tsx"])
        self.assertEqual(grouped["biome"], ["frontend/App.tsx"])

    def test_group_files_by_scanner_with_explicit_override(self):
        grouped = self.reviewer._group_files_by_scanner(
            ["a.py", "b.py", "c.ts"], scanners=("ruff",)
        )
        self.assertEqual(list(grouped.keys()), ["ruff"])
        self.assertEqual(grouped["ruff"], ["a.py", "b.py", "c.ts"])

    def test_review_modified_files_amortizes_subprocesses(self):
        with patch.object(self.reviewer, "run_scanner") as mock_run_scanner:
            mock_run_scanner.side_effect = lambda sc, targets, **kwargs: [
                {"rule_id": f"{sc}-1", "file_path": t, "severity": "low", "message": "msg", "scanner": sc}
                for t in (targets if isinstance(targets, list) else [targets])
            ]

            # 4 python files with default python scanners (ruff, bandit)
            files = [f"file_{i}.py" for i in range(4)]
            result = self.reviewer.review_modified_files(files)

            # Exactly 2 invocations (1 for ruff, 1 for bandit) instead of 8 (4 files * 2 scanners)
            self.assertEqual(mock_run_scanner.call_count, 2)
            called_scanners = {call[0][0] for call in mock_run_scanner.call_args_list}
            self.assertEqual(called_scanners, {"ruff", "bandit"})

            # Verify arguments passed to run_scanner were batched lists
            for call in mock_run_scanner.call_args_list:
                _scanner_name, targets = call[0][0], call[0][1]
                self.assertEqual(targets, files)

            self.assertEqual(result["static_findings_count"], 8)
            self.assertEqual(result["total_findings"], 8)

    def test_review_modified_files_empty_list(self):
        result = self.reviewer.review_modified_files([])
        self.assertEqual(result["static_findings_count"], 0)
        self.assertEqual(result["total_findings"], 0)
        self.assertEqual(result["findings"], [])

    async def test_run_scanner_async_successful_execution(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (
            b'[{"code": "F401", "message": "Unused import", "filename": "app.py", "location": {"row": 1}}]',
            b"",
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            res = await self.reviewer.run_scanner_async("ruff", ["app.py"])
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["rule_id"], "F401")
            self.assertEqual(res[0]["scanner"], "ruff")
            mock_exec.assert_called_once()
            cmd_args = mock_exec.call_args[0]
            self.assertIn("--", cmd_args)
            self.assertEqual(cmd_args[-1], "app.py")

    async def test_run_scanner_async_timeout_handling(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.communicate.side_effect = TimeoutError()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with self.assertRaisesRegex(RuntimeError, "could not complete"):
                await self.reviewer.run_scanner_async("ruff", ["slow.py"], timeout=0.01)
            mock_proc.kill.assert_called_once()

    async def test_review_modified_files_async_concurrent_execution(self):
        with patch.object(self.reviewer, "run_scanner_async") as mock_async_scan:
            mock_async_scan.side_effect = lambda sc, targets, **kwargs: [
                {"rule_id": f"{sc}-finding", "file_path": t, "severity": "low", "message": "test", "scanner": sc}
                for t in (targets if isinstance(targets, list) else [targets])
            ]

            files = ["app/main.py", "app/service.py", "src/App.tsx"]
            ai_findings = [{"rule_id": "AI-1", "message": "AI finding", "severity": "medium"}]

            res = await self.reviewer.review_modified_files_async(files, ai_findings=ai_findings)

            # Scanners: ruff and bandit for .py, eslint and biome for .tsx -> 4 scanner tasks total
            self.assertEqual(mock_async_scan.call_count, 4)
            self.assertEqual(res["ai_findings_count"], 1)
            # 2 py files * 2 scanners = 4 + 1 tsx file * 2 scanners = 2 => 6 static findings
            self.assertEqual(res["static_findings_count"], 6)
            self.assertEqual(res["total_findings"], 7)

    async def test_review_modified_files_async_resilient_to_scanner_error(self):
        with patch.object(self.reviewer, "run_scanner_async") as mock_async_scan:
            def side_effect(sc, targets, **kwargs):
                if sc == "ruff":
                    raise RuntimeError("Ruff crashed")
                return [
                    {"rule_id": f"{sc}-1", "file_path": targets[0], "severity": "low", "message": "ok", "scanner": sc}
                ]

            mock_async_scan.side_effect = side_effect

            res = await self.reviewer.review_modified_files_async(["test.py"])
            # Ruff failed, but bandit succeeded
            self.assertEqual(res["static_findings_count"], 1)
            self.assertEqual(res["findings"][0]["scanner"], "bandit")

    async def test_review_modified_files_async_empty_files(self):
        res = await self.reviewer.review_modified_files_async([])
        self.assertEqual(res["static_findings_count"], 0)
        self.assertEqual(res["total_findings"], 0)
        self.assertEqual(res["findings"], [])


class TestStaticBugScannerMultiFile(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scanner = StaticBugScanner()

    def test_scan_files_empty_list(self):
        res = self.scanner.scan_files([], repo_root="/tmp")
        self.assertTrue(res["success"])
        self.assertEqual(res["files_scanned"], 0)
        self.assertEqual(res["findings"], [])

    def test_scan_files_aggregates_findings_parallel(self):
        with patch.object(self.scanner, "scan_file") as mock_scan_file:
            def fake_scan_file(fp, repo_root):
                return {
                    "success": True,
                    "file_path": fp,
                    "parse_status": "ok",
                    "has_syntax_errors": False,
                    "error_message": None,
                    "findings": [{"rule_id": "AST001", "file_path": fp, "line_number": 5}],
                    "rules_evaluated": 10,
                }
            mock_scan_file.side_effect = fake_scan_file

            files = ["a.py", "b.py", "c.py"]
            res = self.scanner.scan_files(files, repo_root="/tmp", parallel=True)

            self.assertTrue(res["success"])
            self.assertEqual(res["files_scanned"], 3)
            self.assertEqual(res["total_findings"], 3)
            self.assertEqual(res["rules_evaluated"], 30)
            self.assertEqual(len(res["file_results"]), 3)
            self.assertEqual(mock_scan_file.call_count, 3)

    async def test_scan_files_async_executes_successfully(self):
        with patch.object(self.scanner, "scan_files") as mock_scan_files:
            mock_scan_files.return_value = {
                "success": True,
                "findings": [],
                "file_results": [],
                "files_scanned": 2,
                "total_findings": 0,
                "rules_evaluated": 20,
            }

            res = await self.scanner.scan_files_async(["x.py", "y.py"], repo_root="/mock")
            self.assertTrue(res["success"])
            self.assertEqual(res["files_scanned"], 2)
            mock_scan_files.assert_called_once_with(["x.py", "y.py"], repo_root="/mock", parallel=True)

    def test_review_endpoint_resolution_prefers_async_reviewer(self):
        import inspect

        class MockAppState:
            def __init__(self, reviewer):
                self.static_reviewer = reviewer

        class MockReviewer:
            async def review_modified_files_async(self, paths):
                return {"findings": [{"rule_id": "ASYNC_TEST"}]}

            def review_modified_files(self, paths):
                return {"findings": [{"rule_id": "SYNC_TEST"}]}

        mock_rev = MockReviewer()
        app_state = MockAppState(mock_rev)

        ext_reviewer = getattr(app_state, "static_reviewer", None)
        rev_fn = getattr(
            ext_reviewer,
            "review_modified_files_async",
            getattr(ext_reviewer, "review_modified_files", getattr(ext_reviewer, "review", ext_reviewer)),
        )
        self.assertEqual(rev_fn, mock_rev.review_modified_files_async)
        self.assertTrue(inspect.iscoroutinefunction(rev_fn))


if __name__ == "__main__":
    unittest.main()
