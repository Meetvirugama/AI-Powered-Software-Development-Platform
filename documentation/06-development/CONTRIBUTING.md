# Contributing

## Workflow

1. Create a branch from `main`: `{owner}/{short-description}` (for example `om/task-indexes`) or `feature/issue-<number>-<slug>` for issue work.
2. Keep changes within your module; discuss changes to another owner's module or a published interface first.
3. Open a pull request into `main` — direct pushes are not allowed.
4. The PR description must state what changed, why, how to test it and any interface/API changes. Reference the issue (`Fixes #123`).
5. CI must pass: lint, type checks, backend and frontend tests, migrations, security scans.
6. Obtain review from the module owner and a backend or frontend lead.

## Commit messages

```
feat(scanner): extract class and function symbols using tree-sitter

- What changed and why
- Notable edge cases

Refs: #185
```

Types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `chore`, `ci`.

## Definition of done

- Behaviour covered by tests (including a negative/security test where relevant).
- No secrets, tokens or real credentials in code, fixtures or docs.
- OpenAPI and generated frontend types updated when contracts change.
- Documentation in `documentation/` updated when behaviour, configuration or architecture changes.
- No new test files named by person or sprint day; name tests by feature.

## Module ownership

| Area | Owner |
|---|---|
| Repository intelligence, retrieval, task lifecycle | Meet |
| AI engines, output schemas, verification | Dev |
| Frontend | Dharmraj |
| API and orchestration | Yug |
| Database and migrations | Om |
| GitHub integration, OAuth, publication | Parth |
| AST parsing, workspace isolation | Prit |
| Static analysis, chunking, tool policy | Devu |
| Security architecture | Sukun |
| QA and fixtures | Keval |
