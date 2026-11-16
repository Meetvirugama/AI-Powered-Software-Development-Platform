# Development Guide

## Architectural rules

1. **One LLM entry point.** Call `LLMGateway`; never a provider SDK directly. Only Gemini and Groq are approved providers.
2. **Repository content is data.** Build prompts with `PromptBuilder`/context renderers; never put repository or issue text in a system prompt.
3. **Ground and redact.** Validate citations with `GroundingValidator`; pass outward-facing payloads through `secret_redaction`.
4. **Ownership first.** Every repository/task route resolves ownership via the dependencies in `app/api/v1/dependencies.py`.
5. **Workspace access goes through the sandbox.** Use `WorkspaceManager`, `path_guard` and the tool router; do not touch workspace paths directly.
6. **Schema changes via Alembic only.** One linear chain; add a revision for every model change.
7. **No test-aware branches in production code.** Use settings flags or dependency overrides instead of detecting the test runner.

## Adding an API endpoint

1. Add request/response models in `app/schemas`.
2. Add the route in the relevant router under `app/api/v1` with `Depends(require_min_role(...))` and an ownership check.
3. Put logic in a service (`app/services`) and persistence in a repository (`app/repositories`).
4. Regenerate the OpenAPI file and frontend types:
   ```bash
   python backend/scripts/generate_openapi_types.py
   ```
5. Add the frontend service function in `frontend/src/services` and a TanStack Query hook if needed.
6. Tests: route behaviour, RBAC/ownership denial, contract (the API contract test compares frontend calls with OpenAPI routes).

## Adding a database change

```bash
cd backend
alembic revision -m "describe change"      # write upgrade() and downgrade()
alembic upgrade head && alembic check
```

Keep downgrades working; the Postgres CI job runs the migration lifecycle.

## Adding an analysis capability

Follow the shared pipeline in [Developer intelligence](../03-engineering/DEVELOPER_INTELLIGENCE.md): context builder with a budget → deterministic analysis → schema-constrained LLM call → validation → persistence via the analysis repository (record prompt version and model).

## Adding a prompt

Add a `.txt` template under `backend/ai/prompts`, register it as required if the feature cannot run without it, and add a regression test for prompt-injection fixtures in `backend/tests/fixtures/security/prompt_injection`.

## Code style

| Area | Tooling |
|---|---|
| Python | ruff (CI gate on syntax/error rules), bandit; type hints throughout |
| TypeScript | oxlint, `tsc -b` strict build |
| Commits | `type(scope): summary` (e.g. `feat(scanner): …`, `fix(auth): …`) with a body explaining why |
