"""Constants for Sandbox and Isolated Workspace Management.

Owner: Prit Zania — Week 3 Day 1 Deliverable (Docs/week3.md §6 F33, §8 Day 1)
"""

from __future__ import annotations

import re
from pathlib import Path

# Base directory for task sandboxes
DEFAULT_WORKSPACE_SUBDIR = ".workspaces"

# System and host paths that must never be targeted by an isolated workspace
PROTECTED_SYSTEM_PREFIXES: tuple[str, ...] = (
    "/etc",
    "/private/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/System",
    "/Library",
    "/var/run",
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
)

# Sensitive and secret file patterns that must never be read, written, or manipulated by agent tools
FORBIDDEN_FILE_PATTERNS: tuple[str, ...] = (
    ".git",
    ".git/*",
    ".gitmodules",
    ".git/config",
    ".git/hooks",
    ".git/HEAD",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "id_ecdsa",
    "id_ecdsa.*",
    "authorized_keys",
    "known_hosts",
    "*.p12",
    "*.pfx",
)

# Regular expression to reject dangerous file names or paths
DANGEROUS_PATH_SEGMENTS = re.compile(
    r"(^|/|\\)(\.git|\.env|id_rsa|id_ed25519|id_ecdsa)(\.|$|/|\\)",
    re.IGNORECASE,
)

# Resource limits defaults (ADR-007, Docs/week3.md §6 F33)
DEFAULT_TIMEOUT_SECONDS: int = 60
MAX_TIMEOUT_SECONDS: int = 300
DEFAULT_MAX_DISK_BYTES: int = 500 * 1024 * 1024  # 500 MB
DEFAULT_MAX_FILE_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB
DEFAULT_MAX_FILES_MODIFIED: int = 50

# Command execution policy constants (Week 3 Day 3 Deliverable - F34, F35)
ALLOWED_COMMAND_TEMPLATES: tuple[str, ...] = (
    "git",
    "python",
    "python3",
    "pytest",
    "npm",
    "npx",
    "node",
    "ls",
    "dir",
    "cat",
    "echo",
)

DISALLOWED_COMMAND_TOKENS: tuple[str, ...] = (
    ";",
    "&&",
    "||",
    "|",
    "`",
    "$",
    ">",
    "<",
    "\n",
    "\r",
)

SENSITIVE_ENV_VARS: frozenset[str] = frozenset(
    {
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_APP_PRIVATE_KEY",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "SECRET_KEY",
        "JWT_SECRET",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
    }
)

MAX_COMMAND_OUTPUT_BYTES: int = 100 * 1024  # 100 KB max stdout/stderr capture
DEFAULT_COMMAND_TIMEOUT_SECONDS: int = 60

# Week 3 Day 5 — Git publication and verification safety constants (ADR-010, Docs/week3.md §6 F36, F37)
PROTECTED_BRANCHES: frozenset[str] = frozenset(
    {
        "main",
        "master",
        "develop",
        "dev",
        "release",
        "production",
        "prod",
        "staging",
    }
)

# Critical project manifests whose deletion is rejected by default during diff validation
CRITICAL_PROJECT_FILES: frozenset[str] = frozenset(
    {
        "README.md",
        "package.json",
        "pyproject.toml",
        "setup.py",
        "requirements.txt",
        "tsconfig.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
    }
)

# High-confidence secret detection patterns for diff hunks and commit messages
SECRET_SCAN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OpenAI API Key", re.compile(r"sk-[a-zA-Z0-9]{20,}|sk-proj-[a-zA-Z0-9_-]{20,}")),
    ("GitHub Token", re.compile(r"ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{22,}")),
    ("AWS Access Key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Google API Key", re.compile(r"AIza[0-9A-Za-z-_]{35}")),
    ("RSA / EC Private Key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "Generic Secret Assignment",
        re.compile(
            r"""(?i)(?:api_key|apikey|secret|password|auth_token|token)\s*[:=]\s*['"][a-zA-Z0-9_\-.~+=/]{12,}['"]"""
        ),
    ),
)

