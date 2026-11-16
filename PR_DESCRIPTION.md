## Summary

Adds official documentation verified against the code at `5d0b3ff`, and rewrites the root README so its claims match the code.

- New `documentation/` folder with 24 pages: overview and feature status, architecture (system, frontend, backend, AI/RAG, database, agent execution), engineering (API reference generated from `openapi.json`, developer intelligence, tool registry, data flows), security, testing, development, deployment (including corrected runbooks) and reference (decisions, known limitations, glossary).
- The folder is named `documentation/` rather than `docs/` so it can't collide with the existing `Docs/` folder on macOS or Windows.
- `README.md` rewritten: feature status labels, correct deployment description, and links to the new docs.
- No code, tests, config or existing `Docs/` files are changed. Removing the old docs is left for a separate PR after review.

## Corrections compared with the old docs

- Runbooks: task statuses and recovery steps, the webhook replay URL and columns, the effect of rotating JWT_SECRET (it signs out all users), and the webhook worker entry point.
- Known limitations are documented: thread-based task workflows, no chat streaming or stored chat history, MCP registry held in memory, two PR tables, and a runner host needed for isolated execution in production.
- Benchmark conditions are stated: the retrieval benchmark uses in-memory test retrievers, not pgvector.

## How to review

Read `documentation/README.md`, then `documentation/08-reference/KNOWN_LIMITATIONS.md`. All relative links were checked (0 broken).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_016MG8HYJVB4HLG8GswMkoG4
