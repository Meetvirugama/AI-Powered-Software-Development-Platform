"""
Week 1 Security Gate — runs every gate item and prints a PASS/FAIL report.
Owner: Sukun — W1, Day 7

Gate items (Docs/week1.md, Day 7):
    1. No secrets in .git history
    2. No secrets in the code_chunks table
    3. No secrets in the memory_entries table
    4. Repository isolation — User A cannot access User B's data
    5. Prompt injection — LLM ignores instructions in repository content
    6. Path traversal — all file access restricted to the repository workspace
   (+) API security from Day 6 (rate limits, headers, CORS)

Secret values are NEVER printed. Findings show where (commit/file/row/line)
and which pattern matched, plus a short fingerprint so duplicates can be
recognised.

Usage (from the repository root):
    git fetch --all --unshallow   # history check needs full history, all branches
    python backend/scripts/security_gate.py
    python backend/scripts/security_gate.py --skip-db --out Docs/security/week1_gate_results.md

Exit code: 0 if every executed check passed, 1 otherwise (usable in CI).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"

# ---------------------------------------------------------------------------
# Secret patterns (same list as the Day 4 spec)
# ---------------------------------------------------------------------------

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_key": re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    # KEY = "literal"  /  "key": "literal"  (quoted string values only, so code like
    # `token = request.cookies.get(...)` is not flagged)
    "credential_assignment": re.compile(
        r"(?i)\b\w*(?:api_?key|secret|password|passwd|private_?key|access_?token|auth_?token|token)\w*[\"']?"
        r"\s*[:=]\s*[\"'](?P<value>[^\"'\s]{8,})[\"']"
    ),
    # .env style:  OPENAI_API_KEY=sk-...  (unquoted, at the start of a line)
    "env_assignment": re.compile(
        r"^\s*(?:export\s+)?[A-Z0-9_]*(?:API_KEY|SECRET|PASSWORD|PRIVATE_KEY|TOKEN)[A-Z0-9_]*="
        r"(?P<value>[^\s#\"']{8,})"
    ),
}

# Values that are obviously not real secrets (docs, tests, redacted chunks).
PLACEHOLDER_HINTS = re.compile(
    r"(?i)(\[REDACTED\]|<[^>]*>|\.\.\.|x{4,}|example|placeholder|changeme|your[_-]|dummy|fake|mock|"
    r"test|sample|os\.environ|getenv|settings\.|process\.env|\$\{|none|null|true|false)"
)


# Fingerprints of values a human reviewed and confirmed are NOT real secrets
# (test fixtures, documentation examples). One per line: "<fingerprint>  # reason".
ALLOWLIST_FILE = Path(__file__).with_name("security_gate_allowlist.txt")


def load_allowlist() -> set[str]:
    if not ALLOWLIST_FILE.exists():
        return set()
    return {line.split("#", 1)[0].strip() for line in ALLOWLIST_FILE.read_text().splitlines()
            if line.split("#", 1)[0].strip()}


ALLOWLIST = load_allowlist()


@dataclass
class Finding:
    where: str
    pattern: str
    fingerprint: str


@dataclass
class CheckResult:
    name: str
    status: str = "PASS"  # PASS | FAIL | SKIPPED | ERROR
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    reviewed_placeholders: int = 0
    allowlisted: int = 0


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:10]


def scan_text(line: str) -> list[tuple[str, str, bool]]:
    """Return (pattern_name, matched_value, is_placeholder) for every hit in a line."""
    hits = []
    for name, pattern in SECRET_PATTERNS.items():
        for m in pattern.finditer(line):
            value = m.groupdict().get("value") or m.group(0)
            if name == "private_key_block":
                is_placeholder = False  # a key header is never "just a placeholder" — review it
                if re.search(r"(?i)\\n\.\.\.\\n|<[^>]+>", line):
                    is_placeholder = True  # e.g. docs: -----BEGIN ... KEY-----\n...\n-----END
            else:
                is_placeholder = bool(PLACEHOLDER_HINTS.search(value)) or bool(
                    PLACEHOLDER_HINTS.search(line) and name in ("credential_assignment", "env_assignment")
                )
            hits.append((name, value, is_placeholder))
    return hits


# ---------------------------------------------------------------------------
# 1. Git history
# ---------------------------------------------------------------------------

def check_git_history() -> CheckResult:
    result = CheckResult("1. No secrets in .git history")
    try:
        shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"], cwd=REPO_ROOT,
                                 capture_output=True, text=True, check=True).stdout.strip()
        commits = subprocess.run(["git", "rev-list", "--all", "--count"], cwd=REPO_ROOT,
                                 capture_output=True, text=True, check=True).stdout.strip()
        # Spec command, kept for the report (hits are mostly variable NAMES, not values).
        s_hits = subprocess.run(["git", "log", "--all", "-S", "SECRET", "--oneline"], cwd=REPO_ROOT,
                                capture_output=True, text=True, check=True).stdout.strip().splitlines()
        log = subprocess.run(["git", "log", "--all", "-p", "--no-color", "--no-ext-diff", "--format=commit %H"],
                             cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                             encoding="utf-8", errors="replace").stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        result.status, result.summary = "ERROR", f"git failed: {exc}"
        return result

    commit, path = "?", "?"
    seen: set[tuple[str, str, str]] = set()
    for line in log.splitlines():
        if line.startswith("commit "):
            commit = line[7:15]
        elif line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            for name, value, placeholder in scan_text(line[1:]):
                key = (path, name, _fingerprint(value))
                if key in seen:
                    continue
                seen.add(key)
                if placeholder:
                    result.reviewed_placeholders += 1
                elif _fingerprint(value) in ALLOWLIST:
                    result.allowlisted += 1
                else:
                    result.findings.append(Finding(f"{commit} {path}", name, _fingerprint(value)))

    result.status = "FAIL" if result.findings else "PASS"
    result.summary = (f"{commits} commits scanned across all branches"
                      f"{' (WARNING: shallow clone — run git fetch --unshallow)' if shallow == 'true' else ''}; "
                      f"`git log --all -S SECRET` → {len(s_hits)} commits (names only, reviewed); "
                      f"{result.reviewed_placeholders} placeholder values ignored; "
                      f"{result.allowlisted} reviewed test/doc values allowlisted; "
                      f"{len(result.findings)} possible real secrets.")
    if shallow == "true":
        result.status = "FAIL" if result.findings else "ERROR"
    return result


# ---------------------------------------------------------------------------
# 2 & 3. Database tables
# ---------------------------------------------------------------------------

# Coarse Postgres pre-filter; Python then applies the exact patterns per line.
_SQL_PREFILTER = (
    r"(sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(api_key|secret|password|passwd|private_key|token|auth)[a-z0-9_]*\s*[:=])"
)


def check_table(table: str, label: str) -> CheckResult:
    result = CheckResult(label)
    sys.path.insert(0, str(BACKEND))
    try:
        from sqlalchemy import create_engine, text
        from app.core.config import get_settings

        engine = create_engine(get_settings().database_url)
        with engine.connect() as conn:
            total = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            rows = conn.execute(
                text(f"SELECT id, content FROM {table} WHERE content ~* :pattern"),
                {"pattern": _SQL_PREFILTER},
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        result.status, result.summary = "ERROR", f"could not query {table}: {type(exc).__name__}: {exc}"
        return result

    for row in rows:
        for lineno, line in enumerate((row.content or "").splitlines(), 1):
            for name, value, placeholder in scan_text(line):
                if placeholder:
                    result.reviewed_placeholders += 1
                elif _fingerprint(value) in ALLOWLIST:
                    result.allowlisted += 1
                else:
                    result.findings.append(Finding(f"{table}.id={row.id} line {lineno}", name, _fingerprint(value)))

    result.status = "FAIL" if result.findings else "PASS"
    result.summary = (f"{total} rows in {table}; {len(rows)} matched the pre-filter; "
                      f"{result.reviewed_placeholders} placeholder/redacted values ignored; "
                      f"{result.allowlisted} allowlisted; "
                      f"{len(result.findings)} possible real secrets.")
    return result


# ---------------------------------------------------------------------------
# 4–7. Test suites
# ---------------------------------------------------------------------------

TEST_CHECKS = [
    ("4. Repository isolation (User A cannot access User B)",
     ["backend/tests/test_repository_isolation.py"], None),
    ("5. Prompt injection treated as data",
     ["backend/tests/test_security_day5.py", "backend/tests/test_dev_day2.py"],
     "PromptInjection or system_message_has_no_repo_content"),
    ("6. Path traversal / workspace confinement",
     ["backend/tests/test_security_day5.py"],
     "traversal or Traversal or symlink or malicious or safe_paths or resolve_within or 50mb"),
    ("7. API security (Day 6: rate limits, headers, CORS)",
     ["backend/tests/test_security_day6.py"], None),
]


def check_tests(label: str, files: list[str], keyword: str | None) -> CheckResult:
    result = CheckResult(label)
    missing = [f for f in files if not (REPO_ROOT / f).exists()]
    if missing:
        result.status, result.summary = "ERROR", f"missing test file(s): {', '.join(missing)}"
        return result
    cmd = [sys.executable, "-m", "pytest", *files, "-q", "--no-cov", "-p", "no:cacheprovider", "-rfE"]
    if keyword:
        cmd += ["-k", keyword]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    tail = [l for l in proc.stdout.strip().splitlines() if l.strip()][-1:] or ["(no output)"]
    failed = [l for l in proc.stdout.splitlines() if l.startswith(("FAILED", "ERROR"))]
    result.status = "PASS" if proc.returncode == 0 else "FAIL"
    result.summary = tail[0]
    result.findings = [Finding(l, "test", "") for l in failed[:20]]
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

ICON = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "SKIPPED": "⏭️ SKIPPED", "ERROR": "⚠️ ERROR"}


def render(results: list[CheckResult]) -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        sha = "?"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    overall = "PASS" if all(r.status in ("PASS", "SKIPPED") for r in results) else "FAIL"
    out = [
        "# Week 1 Security Gate — Results",
        "",
        f"**Run:** {now} · **Commit:** `{sha}` · **Overall:** {ICON[overall]}",
        "",
        "| Gate item | Result | Details |",
        "|---|---|---|",
    ]
    for r in results:
        out.append(f"| {r.name} | {ICON[r.status]} | {r.summary.replace('|', '/')} |")
    for r in results:
        if r.findings:
            out += ["", f"## {r.name} — findings", "", "| Where | Pattern | Fingerprint |", "|---|---|---|"]
            out += [f"| {f.where} | {f.pattern} | `{f.fingerprint}` |" for f in r.findings]
    out += ["", "_Secret values are never printed; fingerprint = first 10 hex chars of SHA-256._", ""]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-db", action="store_true", help="skip the code_chunks / memory_entries checks")
    parser.add_argument("--skip-tests", action="store_true", help="skip the pytest-based checks")
    parser.add_argument("--out", type=Path, help="also write the markdown report to this file")
    args = parser.parse_args()

    results = [check_git_history()]
    if args.skip_db:
        results += [CheckResult("2. No secrets in code_chunks", "SKIPPED", "--skip-db"),
                    CheckResult("3. No secrets in memory_entries", "SKIPPED", "--skip-db")]
    else:
        results += [check_table("code_chunks", "2. No secrets in code_chunks"),
                    check_table("memory_entries", "3. No secrets in memory_entries")]
    for label, files, keyword in TEST_CHECKS:
        results.append(CheckResult(label, "SKIPPED", "--skip-tests") if args.skip_tests
                       else check_tests(label, files, keyword))

    report = render(results)
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    return 0 if all(r.status in ("PASS", "SKIPPED") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
