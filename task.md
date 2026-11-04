# Complete Repository Cleanup, Dead Code Elimination & Codebase Optimization

Act as a Senior Software Architect, Staff Engineer and Code Quality Specialist.

Perform a complete, evidence-based cleanup of this repository. Over time, we have added many features, modified existing implementations, introduced new architectures and replaced old code. As a result, the codebase may contain dead code, duplicate implementations, obsolete files, unnecessary abstractions, unused dependencies, redundant API endpoints, outdated documentation and leftover development code.

Your task is to identify and safely eliminate these problems while preserving all working functionality.

**Important: Do not start deleting files immediately. First understand the entire architecture and verify actual usage.**

## 1. Complete Repository Audit

Inspect the entire repository, including:

- Frontend source code
- Backend source code
- AI/ML modules and services
- API routes and controllers
- Database models, schemas and migrations
- Repository Intelligence and context system
- Task Planner and Executor
- Test Generation
- Bug Detection
- Code Review
- Authentication and authorization
- GitHub integration
- Background workers and scheduled jobs
- Configuration and environment files
- Scripts and utilities
- Documentation and Markdown files
- Tests, fixtures and test utilities
- Deployment and CI/CD configurations

Build a complete dependency and usage map before making changes.

## 2. Identify Dead and Unnecessary Code

Find and classify the following:

### A. Dead code
- Unused functions and methods.
- Unused classes and modules.
- Unreachable code branches.
- Unused variables and imports.
- Old implementations that are no longer called.
- Obsolete feature implementations.
- Unused event handlers and callbacks.
- Unused React components and hooks.
- Unused API routes and services.
- Unused background jobs.

### B. Duplicate code
- Functions implementing the same logic.
- Duplicate API endpoints.
- Repeated business logic across services.
- Multiple implementations of the same feature.
- Duplicate validation and error-handling logic.
- Repeated frontend components.
- Multiple context-building or repository-scanning implementations.
- Duplicate utility functions.

Identify the best canonical implementation and consolidate carefully.

### C. Unnecessary architecture
- Excessive abstraction layers.
- Classes that only forward calls without adding value.
- Unnecessary wrappers and adapters.
- Over-engineered service structures.
- Unnecessary managers, factories and providers.
- Circular dependencies.
- Unnecessary state management.
- Unnecessary intermediate data transformations.
- Redundant configuration layers.

Do not remove useful abstractions merely to reduce file count.

### D. Obsolete and leftover code
- Deprecated implementations.
- Old experimental features.
- Unused development components.
- Temporary debugging code.
- Commented-out implementations.
- TODOs and FIXMEs that are no longer relevant.
- Unused scripts.
- Old migration utilities.
- Obsolete environment variables.
- Outdated configuration files.

### E. Dependencies
- Unused Python packages.
- Unused npm packages.
- Duplicate libraries providing the same functionality.
- Packages used only by obsolete implementations.
- Outdated dependency references.
- Unnecessary development dependencies.

Verify package usage, dynamic imports, plugin loading and runtime requirements before removing anything.

## 3. Feature-Level Architecture Consolidation

Pay special attention to these existing platform capabilities:

- Repository Intelligence
- Task Planner
- Task Executor
- Test Generation
- Bug Detection
- Code Review
- Code Explanation
- AI Context Builder
- LLM Gateway
- GitHub integration

Check whether these features have duplicate implementations of:

- Repository scanning.
- Context construction.
- Symbol retrieval.
- Dependency analysis.
- Prompt construction.
- Model selection.
- Token budgeting.
- Test discovery.
- Execution orchestration.
- Error handling.
- Logging and monitoring.

Where appropriate, reuse shared services instead of maintaining multiple independent implementations.

**Example:** If Task Planner and Code Explanation both implement their own repository context retrieval, investigate whether they should use the shared Repository Intelligence ContextBuilder.

Do not blindly merge features with different requirements.

## 4. Frontend Cleanup

Inspect the entire frontend.

Find and improve:

- Unused React components.
- Duplicate components.
- Unused hooks and contexts.
- Unnecessary state.
- Redundant API calls.
- Duplicate API service functions.
- Unused CSS and stylesheets.
- Dead routes and pages.
- Unused icons and assets.
- Duplicate animation implementations.
- Unnecessary dependencies.
- Excessive re-rendering.
- Large components that should be split.
- Components with excessive responsibilities.
- Broken or outdated navigation references.

Ensure:
- Existing pages still work.
- All buttons and actions have valid functionality.
- No important functionality is removed.
- Loading, error and empty states remain correct.
- Responsive layouts are preserved.
- Existing design and animations are preserved unless explicitly unnecessary.

## 5. Backend Cleanup

Inspect all backend modules.

Find and improve:

- Duplicate service implementations.
- Unused endpoints.
- Unnecessary routers.
- Redundant schemas and models.
- Unused database queries.
- Duplicate repository/data-access logic.
- Unnecessary middleware.
- Duplicate exception handlers.
- Unused background workers.
- Unnecessary database connections.
- Circular service dependencies.
- Unused configuration variables.
- Redundant serialization/deserialization.
- Inefficient repeated queries.

Ensure that API contracts, authentication, authorization, database operations and integrations remain compatible.

## 6. AI/ML and Agent Architecture Cleanup

Audit the AI architecture carefully.

Check:

- Duplicate LLM clients.
- Multiple prompt templates for identical tasks.
- Unused agents.
- Obsolete model providers.
- Duplicate context retrieval.
- Unused embedding utilities.
- Duplicate vector search logic.
- Redundant token-counting implementations.
- Unused model configuration.
- Duplicate retry and fallback mechanisms.
- Obsolete planning/execution implementations.
- Unnecessary intermediate LLM calls.
- Unused memory/context objects.
- Redundant tool definitions.

Consolidate common functionality into appropriate shared services.

Preserve feature-specific prompts, behaviour and quality requirements.

Do not remove an agent, model provider or fallback merely because its usage is not obvious.

## 7. Documentation Cleanup

Inspect every Markdown and documentation file.

Identify:

- Duplicate documentation.
- Outdated architecture descriptions.
- Obsolete implementation plans.
- Completed task documents that are still presented as pending.
- Broken internal links.
- Outdated file paths.
- Old API descriptions.
- Duplicate diagrams.
- Contradictory documentation.
- Documentation describing removed functionality.

Update documentation to reflect the actual final architecture.

Do not delete useful historical decisions, test reports or project records without justification.

## 8. Safe Removal Rules

For every proposed deletion or consolidation:

1. Search for imports and references across the entire repository.
2. Check dynamic imports and runtime registration.
3. Check API routing and dependency injection.
4. Check frontend routing and lazy loading.
5. Check configuration-driven and plugin-driven loading.
6. Check tests and fixtures.
7. Check CI/CD, deployment scripts and Docker configurations.
8. Check external consumers and documented interfaces.
9. Confirm whether the code is truly obsolete.
10. Record the reason and evidence.

Classify findings as:

- SAFE TO REMOVE
- SAFE TO MERGE
- NEEDS REFACTORING
- KEEP — ACTIVE FUNCTIONALITY
- UNCERTAIN — REQUIRES MANUAL REVIEW

Never delete uncertain code automatically.

## 9. Implementation Strategy

Work in controlled phases.

### Phase 1 — Audit only
- Understand the architecture.
- Build dependency maps.
- Identify duplicate and dead code.
- Create a complete findings report.
- Do not modify source code yet.

### Phase 2 — Safe cleanup
- Remove unused imports and variables.
- Remove confirmed dead code.
- Remove obsolete debugging code.
- Remove verified unused dependencies.
- Remove redundant assets and styles.
- Consolidate safe duplicates.

### Phase 3 — Architecture consolidation
- Reuse shared services.
- Remove redundant abstractions.
- Consolidate duplicate context and utility implementations.
- Resolve unnecessary circular dependencies.
- Simplify feature orchestration.

### Phase 4 — Optimization
- Improve unnecessary computation.
- Reduce duplicate database queries.
- Reduce redundant API requests.
- Optimize imports and package size.
- Reduce unnecessary LLM calls and token consumption.
- Improve code readability and maintainability.

### Phase 5 — Full regression testing
Run all applicable tests, including:

- Unit tests.
- Integration tests.
- API tests.
- Frontend tests.
- AI/ML feature tests.
- Task Planner and Executor tests.
- Test Generation tests.
- Bug Detection tests.
- Code Review and Explanation tests.
- Database and migration tests.
- Authentication and authorization tests.
- Production frontend build.
- Backend linting and type checks.
- Dependency and security checks.

A missing test suite, skipped required test or test collection failure must never be reported as a pass.

### Phase 6 — Final verification
- Review the complete Git diff.
- Check for accidental feature removal.
- Verify all important routes and integrations.
- Verify no secrets or environment files were accidentally modified.
- Verify documentation matches the final code.
- Produce a cleanup report.

## 10. Required Documentation Deliverables

Create or update the following:

### `Docs/audits/CODEBASE_CLEANUP_AUDIT.md`

Include:
- Complete architecture findings.
- Dead code inventory.
- Duplicate implementation inventory.
- Unnecessary abstractions.
- Unused dependencies.
- Obsolete files and assets.
- Circular dependencies.
- Performance and maintainability problems.
- Evidence for every recommendation.
- Risk and priority.

### `Docs/audits/CODEBASE_CLEANUP_CHANGELOG.md`

Include:
- Every removed file.
- Every removed function/class.
- Every merged implementation.
- Every modified module.
- Every dependency removed.
- Reason for each change.
- Related commits or change references.

### `Docs/audits/CODEBASE_CLEANUP_TEST_RESULTS.md`

Include:
- Baseline test results.
- Tests executed after cleanup.
- Passed, failed, blocked, skipped and not-run counts.
- Build and type-check results.
- Regression findings.
- Remaining issues.
- Final release decision.

## 11. Final Acceptance Criteria

The cleanup is complete only when:

- Confirmed dead code is removed.
- Duplicate implementations are consolidated where appropriate.
- Unnecessary dependencies are removed safely.
- Shared architecture is reused consistently.
- No important feature or API contract is broken.
- No accidental data model or migration changes occur.
- All relevant mandatory tests are accounted for.
- Frontend production build succeeds.
- Backend validation succeeds.
- Documentation reflects the final architecture.
- Every removal is traceable.
- Remaining uncertain code is documented rather than blindly deleted.

## 12. Important Instructions

- Do not optimize only for fewer lines of code.
- Do not delete code based only on low search results or missing direct imports.
- Do not rewrite the entire architecture unnecessarily.
- Do not change product behaviour during a cleanup-only task.
- Do not remove useful comments, documentation or error handling.
- Do not weaken tests to achieve passing results.
- Do not claim tests passed without executing them.
- Preserve existing working functionality.
- Make small, reviewable changes.
- Run relevant tests after each cleanup batch.
- If a change causes regression, fix it or revert it before continuing.

**Final objective:** Make this repository leaner, cleaner, easier to maintain, less redundant and more efficient, while preserving the full functionality and reliability of the existing AI-powered software development platform.