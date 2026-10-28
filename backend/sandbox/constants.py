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
