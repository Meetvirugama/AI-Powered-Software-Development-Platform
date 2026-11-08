# Framework Adapters: pytest, unittest, Jest, and Vitest

This document outlines the detection heuristics, command construction, output parsers, and coverage tools across all four supported frameworks.

---

## 1. Supported Framework Matrix

| Framework | Detection Signatures | Test Runner Command | Coverage Command | Output Parser |
| :--- | :--- | :--- | :--- | :--- |
| **pytest** | `pytest.ini`, `pyproject.toml` (`[tool.pytest]`), `tests/test_*.py` | `pytest -v <path>` | `coverage run -m pytest <path>` $\to$ `coverage json` | Regex parser on summary line `(=+ \d+ passed in [\d.]+s =+)` |
| **unittest** | Explicit framework request or standard Python test modules | `python -m unittest -v <path>` | `coverage run -m unittest <path>` $\to$ `coverage json` | Regex parser on `Ran \d+ tests` & `OK` / `FAILED` |
| **Jest** | `jest.config.*`, `"jest"` in `package.json` | `npm test -- <path>` | `npm test -- --coverage --coverageReporters=json-summary` | Regex on `Tests: \d+ passed, \d+ total` & `● <failed>` |
| **Vitest** | `vitest.config.*`, `vite.config.*`, `"vitest"` in `package.json` | `npm test -- --run <path>` | `npm test -- --run --coverage` | Regex on `Tests \d+ passed (\d+)` & `FAIL <file>` |

---

## 2. Vitest Implementation Details

### Detection
`FrameworkDetector` scans for:
- `vitest.config.ts`, `vitest.config.js`, `vitest.config.mjs`.
- `vite.config.ts`, `vite.config.js`, `vite.config.mjs`.
- `package.json` dependencies containing `"vitest"` or scripts containing `"vitest"`.

### Path Convention
JS/TS files infer collocated or `__tests__` directories:
- Example: `src/components/Button.tsx` $\to$ `src/components/__tests__/Button.test.tsx` or `tests/Button.test.ts`.

### Mocking APIs
The system prompt explicitly instructs the LLM to generate native Vitest mock functions:
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../apiClient', () => ({
  fetchData: vi.fn().mockResolvedValue({ id: 1 }),
}));
```
