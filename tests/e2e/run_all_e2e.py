#!/usr/bin/env python3
"""Dedicated End-to-End (E2E) Test Suite Runner.

Executes all 4 tiers of the comprehensive E2E test suite:
- Tier 1: Feature Coverage (all 31 features, happy-path, self-contained)
- Tier 2: Boundary & Corner Cases (timeouts, empty inputs, max sizes, state boundaries)
- Tier 3: Cross-Feature Combinations (pairwise interactions, invalidations, recovery)
- Tier 4: Real-World Application Scenarios (realistic end-to-end task lifecycles)

Usage:
    python tests/e2e/run_all_e2e.py
    python tests/e2e/run_all_e2e.py --tier 1
    python tests/e2e/run_all_e2e.py --verbose
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


TIERS = {
    1: {
        "name": "Tier 1: Feature Coverage",
        "file": "tests/e2e/test_tier1_features.py",
        "description": "All 31 canonical features cataloged in PROJECT.md Feature Inventory",
    },
    2: {
        "name": "Tier 2: Boundary & Corner Cases",
        "file": "tests/e2e/test_tier2_boundaries.py",
        "description": "Timeouts, empty inputs, max ceilings, invalid transitions, forbidden files",
    },
    3: {
        "name": "Tier 3: Cross-Feature Combinations",
        "file": "tests/e2e/test_tier3_combinations.py",
        "description": "Pairwise interactions, approval invalidations, anti-cycling, replay guards",
    },
    4: {
        "name": "Tier 4: Real-World Scenarios",
        "file": "tests/e2e/test_tier4_scenarios.py",
        "description": "Autonomous bug fix, frontend Vitest, repair exhaustion, SSE timeline lifecycles",
    },
}


def run_tier(tier_id: int, tier_meta: dict, repo_root: Path, verbose: bool = False) -> dict:
    test_file = repo_root / tier_meta["file"]
    if not test_file.exists():
        return {
            "tier": tier_id,
            "name": tier_meta["name"],
            "status": "MISSING",
            "passed": 0,
            "failed": 0,
            "duration": 0.0,
            "exit_code": 1,
        }

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-o",
        "addopts=",
    ]
    if verbose:
        cmd.append("-v")
    else:
        cmd.append("-q")

    env = dict(os.environ)
    env["PYTHONPATH"] = f"{repo_root / 'backend'}:{repo_root}:{env.get('PYTHONPATH', '')}"

    start_time = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
    )
    duration = time.perf_counter() - start_time

    # Parse pytest output
    stdout = proc.stdout + "\n" + proc.stderr
    passed = 0
    failed = 0

    import re
    # Match pattern: "XX passed"
    m_pass = re.search(r"(\d+)\s+passed", stdout)
    if m_pass:
        passed = int(m_pass.group(1))

    # Match pattern: "XX failed"
    m_fail = re.search(r"(\d+)\s+failed", stdout)
    if m_fail:
        failed = int(m_fail.group(1))

    status = "PASSED" if proc.returncode == 0 and failed == 0 else "FAILED"

    return {
        "tier": tier_id,
        "name": tier_meta["name"],
        "status": status,
        "passed": passed,
        "failed": failed,
        "duration": duration,
        "exit_code": proc.returncode,
        "output": stdout if proc.returncode != 0 and not verbose else None,
    }


def main():
    parser = argparse.ArgumentParser(description="AI Platform 4-Tier E2E Test Suite Runner")
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        default=None,
        help="Run only a specific tier (1, 2, 3, or 4)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Run pytest in verbose mode with detailed test output",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent.parent

    print("=" * 80)
    print(" AI-POWERED SOFTWARE DEVELOPMENT PLATFORM — E2E TEST SUITE RUNNER")
    print("=" * 80)
    print(f"Repository Root: {repo_root}")
    print(f"Python Binary:   {sys.executable}")
    print(f"Execution Mode:  {'Specific Tier: ' + str(args.tier) if args.tier else 'Full 4-Tier Suite'}")
    print("-" * 80)

    selected_tiers = [args.tier] if args.tier else [1, 2, 3, 4]
    results = []

    overall_start = time.perf_counter()

    for tid in selected_tiers:
        meta = TIERS[tid]
        print(f"\n▶ Executing {meta['name']}...")
        print(f"  Target: {meta['file']}")
        print(f"  Scope:  {meta['description']}")

        res = run_tier(tid, meta, repo_root, verbose=args.verbose)
        results.append(res)

        badge = "✓ PASS" if res["status"] == "PASSED" else "✗ FAIL"
        print(f"  Verdict: {badge} ({res['passed']} passed, {res['failed']} failed) in {res['duration']:.2f}s")
        if res.get("output"):
            print("  --- Failure Output ---")
            for line in res["output"].strip().splitlines()[-15:]:
                print(f"    {line}")

    overall_duration = time.perf_counter() - overall_start

    # Summary Table
    print("\n" + "=" * 80)
    print(" E2E TEST EXECUTION SUMMARY")
    print("=" * 80)
    print(f"{'Tier':<35} | {'Passed':<8} | {'Failed':<8} | {'Duration':<10} | {'Status':<8}")
    print("-" * 80)

    total_passed = 0
    total_failed = 0
    all_clean = True

    for r in results:
        total_passed += r["passed"]
        total_failed += r["failed"]
        if r["status"] != "PASSED":
            all_clean = False
        print(
            f"{r['name']:<35} | {r['passed']:<8} | {r['failed']:<8} | {r['duration']:<9.2f}s | {r['status']:<8}"
        )

    print("-" * 80)
    print(
        f"{'TOTAL':<35} | {total_passed:<8} | {total_failed:<8} | {overall_duration:<9.2f}s | {'PASSED' if all_clean else 'FAILED'}"
    )
    print("=" * 80)

    if all_clean:
        print("\n🎉 ALL E2E TEST TIERS PASSED PERFECTLY!\n")
        sys.exit(0)
    else:
        print("\n❌ SOME E2E TESTS FAILED. See details above.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
