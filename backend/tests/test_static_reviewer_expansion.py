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


if __name__ == "__main__":
    unittest.main()
