# Deployment & Configuration Guide

---

## 1. Environment Variables & Runtime Dependencies

The upgraded test generation system operates within the existing backend environment without requiring external microservices.

| Environment Variable | Description | Default | Mandatory |
| :--- | :--- | :--- | :--- |
| `ACTIVE_CHAT_MODEL` | Active LLM model identifier | `gemini-2.5-flash` | Yes |
| `DEFAULT_WORKSPACE_SUBDIR` | Directory under project root for sandboxes | `.workspaces` | No |
| `DEFAULT_COMMAND_TIMEOUT_SECONDS` | Maximum timeout for sandbox subprocesses | `45` | No |
| `MAX_COMMAND_OUTPUT_BYTES` | Maximum bytes retained from test output logs | `102400` (100 KB) | No |

---

## 2. System Prerequisites

- **Python Runtime**: Python 3.11+ (tested on Python 3.14).
- **Python Packages**: `coverage >= 7.0`, `pytest >= 8.0`, `pydantic >= 2.0`.
- **Node Runtime**: Node.js 18+ and npm for JavaScript/TypeScript repositories.
- **Node Packages**: Vitest and Jest support available when installed in the repository's `node_modules`.

---

## 3. Directory Layout
Disposable task sandboxes are provisioned under:
```
<PROJECT_ROOT>/.workspaces/task-<task_id_slug>-<sha256>/
```
Directories are cleaned up automatically upon test execution completion.
