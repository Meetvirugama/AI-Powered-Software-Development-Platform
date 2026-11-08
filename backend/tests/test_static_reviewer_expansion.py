"""Unit tests for expanded StaticReviewer supporting ESLint and Biome (Phase 3)."""

import json
import subprocess
import unittest
from unittest.mock import patch, MagicMock
from review.static_reviewer import StaticReviewer


class TestStaticReviewerExpansion(unittest.TestCase):
    def setUp(self):
        self.reviewer = StaticReviewer()

    def test_detect_scanners_for_python(self):
        scanners = self.reviewer.detect_scanners_for_file("backend/app/main.py")
        self.assertEqual(scanners, ["ruff", "bandit"])

    def test_detect_scanners_for_typescript_default(self):
        scanners = self.reviewer.detect_scanners_for_file("frontend/src/index.tsx")
        self.assertEqual(scanners, ["eslint", "biome"])

    @patch("os.path.exists")
    def test_detect_scanners_prefers_biome_when_config_present(self, mock_exists):
        mock_exists.side_effect = lambda p: p.endswith("biome.json")
        scanners = self.reviewer.detect_scanners_for_file("src/app.ts", repo_root="/mock/repo")
        self.assertEqual(scanners, ["biome"])

    @patch("os.path.exists")
    def test_detect_scanners_prefers_eslint_when_config_present(self, mock_exists):
        mock_exists.side_effect = lambda p: p.endswith(".eslintrc.json")
        scanners = self.reviewer.detect_scanners_for_file("src/app.ts", repo_root="/mock/repo")
        self.assertEqual(scanners, ["eslint"])

    @patch("review.static_reviewer.subprocess.run")
    def test_eslint_json_output_normalized(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["npx", "eslint"],
            returncode=1,
            stdout=json.dumps([
                {
                    "filePath": "src/App.tsx",
                    "messages": [
                        {
                            "ruleId": "react/jsx-no-target-blank",
                            "severity": 2,
                            "message": 'Using target="_blank" without rel="noreferrer" is a security risk.',
                            "line": 15,
                            "column": 9,
                        }
                    ],
                }
            ]),
            stderr="",
        )

        results = self.reviewer.run_scanner("eslint", "src/App.tsx")
        self.assertEqual(len(results), 1)
        finding = results[0]
        self.assertEqual(finding["rule_id"], "react/jsx-no-target-blank")
        self.assertEqual(finding["severity"], "high")
        self.assertEqual(finding["file_path"], "src/App.tsx")
        self.assertEqual(finding["line_number"], 15)
        self.assertEqual(finding["scanner"], "eslint")

    @patch("review.static_reviewer.subprocess.run")
    def test_biome_json_output_normalized(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["npx", "@biomejs/biome"],
            returncode=1,
            stdout=json.dumps({
                "diagnostics": [
                    {
                        "category": "lint/correctness/noUnusedVariables",
                        "severity": "error",
                        "description": "This variable is unused.",
                        "location": {
                            "path": {"file": "src/math.ts"},
                            "lines": {"start": 8},
                        },
                    }
                ]
            }),
            stderr="",
        )

        results = self.reviewer.run_scanner("biome", "src/math.ts")
        self.assertEqual(len(results), 1)
        finding = results[0]
        self.assertEqual(finding["rule_id"], "lint/correctness/noUnusedVariables")
        self.assertEqual(finding["severity"], "high")
        self.assertEqual(finding["file_path"], "src/math.ts")
        self.assertEqual(finding["line_number"], 8)
        self.assertEqual(finding["scanner"], "biome")

    def test_unsafe_target_path_rejected(self):
        with self.assertRaises(ValueError):
            self.reviewer.run_scanner("eslint", "--fix")

        with self.assertRaises(ValueError):
            self.reviewer.run_scanner("biome", "src/file\x00.ts")

    @patch("review.static_reviewer.subprocess.run")
    def test_biome_derives_line_from_span_byte_offset(self, mock_run):
        # Biome JSON reporting span without lines.start
        source_text = "const a = 1;\nconst b = 2;\nconst c = 3;\n"
        # offset 26 is line 3
        mock_run.return_value = subprocess.CompletedProcess(
            args=["npx", "--no-install", "@biomejs/biome"],
            returncode=1,
            stdout=json.dumps({
                "diagnostics": [
                    {
                        "category": "lint/correctness/noUnusedVariables",
                        "severity": "error",
                        "description": "Variable c is unused",
                        "location": {
                            "path": {"file": "src/math.ts"},
                            "span": [26, 35],
                            "sourceCode": source_text,
                        },
                    }
                ]
            }),
            stderr="",
        )

        results = self.reviewer.run_scanner("biome", "src/math.ts")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["line_number"], 3)

    @patch("review.static_reviewer.subprocess.run")
    def test_run_scanner_passes_no_install_and_cwd(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
        self.reviewer.run_scanner("eslint", "src/App.tsx", cwd="/custom/root")

        mock_run.assert_called_once()
        call_args, call_kwargs = mock_run.call_args
        cmd = call_args[0]
        self.assertIn("--no-install", cmd)
        self.assertEqual(call_kwargs["cwd"], "/custom/root")

    @patch.object(StaticReviewer, "run_scanner")
    def test_review_modified_files_explicit_scanners_not_overridden(self, mock_run_scanner):
        mock_run_scanner.return_value = []
        self.reviewer.review_modified_files(["src/App.tsx"], scanners=("biome",))

        # Should only call biome, not ruff or bandit
        mock_run_scanner.assert_called_once_with("biome", "src/App.tsx")


if __name__ == "__main__":
    unittest.main()
