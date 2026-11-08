# Tools, Versions, and License Compatibility Matrix

This document audits the runtime libraries and external tools leveraged by the execution-verified test generation system.

---

## 1. Tool Matrix

| Tool | Ecosystem | Purpose in Architecture | License | Compatibility Assessment |
| :--- | :--- | :--- | :--- | :--- |
| **coverage.py** | Python | Core statement & branch coverage measurement (`coverage run`, `coverage json`) | Apache 2.0 | Fully compatible; installed in runtime virtualenv (`v7.16.1`). |
| **pytest** | Python | Standard test framework for modern Python repositories | MIT | Fully compatible; primary runner for test suites. |
| **unittest** | Python | Standard library test framework; zero-dependency fallback | PSF | Standard library (Python 3.14). |
| **pytest-cov** | Python | Pytest plugin for coverage integration | MIT | Permitted; parses output identical to `coverage.py`. |
| **mutmut** | Python | Mutation testing tool for Python | BSD 3-Clause | Evaluated; our custom `MutationTestingService` provides deterministic in-process AST mutation without external daemons. |
| **Vitest** | Node.js | Modern Vite-native test runner (`vitest run`) | MIT | Fully compatible; npm package in frontend (`v4.1.12`). |
| **Jest** | Node.js | Standard JavaScript unit test runner | MIT | Fully compatible; npm package in client setups. |
| **Istanbul / c8** | Node.js | JavaScript coverage instrumentation (`coverage-summary.json`) | BSD 3-Clause / ISC | Fully compatible; default coverage engine in Vitest and Jest. |

---

## 2. Licensing Compliance Statement
All adopted libraries and utilities operate under permissive open-source licenses (MIT, Apache 2.0, BSD-3, PSF). None impose copyleft restrictions (GPL/AGPL) on our proprietary backend codebase.
