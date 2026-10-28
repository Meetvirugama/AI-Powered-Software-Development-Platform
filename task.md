# Final Implementation Plan: Antigravity-Style Developer Studios

Project: AI-Powered Software Development Platform\
Scope: Week 1 + Week 2 only\
Objective: Transform the existing application into a cohesive AI developer workspace inspired by Google Antigravity and Claude Code, while preserving existing backend APIs and reusing working code.

The strategy is to build one integrated developer environment, not six disconnected pages. Every studio should share repository context, source navigation, history, error handling, and a consistent design system.

## 1. Final product architecture

Repository Workspace

Repository identity · Global navigation · Search · Command palette · Index status

1\. Explorer

Files, symbols, source viewer

2\. Chat Studio

Repository-grounded RAG chat

3\. Explain Studio

Code walkthrough and architecture

4\. Bug Hunter

Findings, severity, evidence

5\. Test Studio

Test generation and validation

6\. Code Review

Review findings and diffs

Shared frontend infrastructure

Typed API client · Shared UI components · Repository state · History · Error handling

Existing backend and AI services

RAG · Explanation · Bug detection · Test generation · Code review

## 2. Final route structure

Use nested routes so all repository studios share the same workspace layout.

```
<Route path="repositories/:id" element={<RepositoryStudioLayout />}>
  <Route index element={<RepositoryDetail />} />
  <Route path="chat" element={<RepositoryChat />} />
  <Route path="explain" element={<RepositoryExplainStudio />} />
  <Route path="bugs" element={<RepositoryBugStudio />} />
  <Route path="tests" element={<RepositoryTestStudio />} />
  <Route path="review" element={<RepositoryReviewStudio />} />
</Route>
```

The actual route nesting must match the existing `App.tsx` structure and authentication layout. Preserve existing URLs and redirect legacy routes if necessary.

## 3. Week-by-week implementation plan

## Phase 0 — Baseline and contract verification

Prerequisite

- Inspect `App.tsx`, `RepositoryDetail.tsx`, API clients, hooks, schemas and existing tests.
- Verify each Week 2 endpoint and response model against the actual backend.
- Establish a working frontend dependency install, lint and production build.
- Record which existing features work, are partial, or are broken.
- Identify reusable components before creating replacements.

  Completion gate: reproducible baseline and documented API contracts.

## Week 1 — Workspace foundation

- Build `RepositoryStudioLayout` and `StudioSubNav`.
- Add nested routes and active navigation.
- Keep `RepositoryDetail` focused on Explorer and repository overview.
- Build reusable file/symbol picker, code viewer, loading/error states and source links.
- Integrate the existing Chat Studio without breaking its current behavior.
- Add responsive layout, lazy loading and navigation tests.

  Completion gate: all workspace routes load, refresh and navigate correctly.

## Week 2 — Explain Studio and shared analysis infrastructure

- Implement `RepositoryExplainStudio`.
- Reuse the existing explanation hook and backend endpoint after contract verification.
- Display source code, explanation sections and grounded source references.
- Add analysis history, reopen behavior, retries and useful error messages.
- Build shared finding cards, severity badges, result panels and analysis status components for later studios.
- Test repository switching, source navigation and stale-response handling.

  Completion gate: Explain Studio works end to end and shared components are reusable.

## Week 3 — Bug Hunter

- Build severity and status filters using statuses supported by the backend.
- Display findings with file, line range, evidence and provenance.
- Add source navigation and copy-patch functionality.
- Link a finding to Test Studio with the target prefilled.
- Add false-positive tracking only if persistence/API support exists.

  Completion gate: findings are correctly mapped to source and unsupported actions are not shown.

## Week 4 — Test Studio

- Add target and framework selectors based on actual supported values.
- Add test strategy controls only when supported by the request schema.
- Display generated code in an editable or read-only editor according to scope.
- Integrate `checkProposedTestPath()` and existing validation behavior.
- Add copy/download and safe path warnings.

  Completion gate: generation and syntax validation are clearly distinguished from execution.

## Week 5 — Code Review

- Implement supported review target selection.
- Display findings beside source or supported diff context.
- Add evidence, severity, source references and review history.
- Implement a scorecard only if meaningful, explainable metrics exist.

  Completion gate: review findings map to the correct source revision.

## Final phase — Cross-feature QA and optimization

- Run frontend tests, lint and production build.
- Verify every studio against its real backend endpoint.
- Test loading, timeout, empty results, provider failure and retry states.
- Validate deep links, browser refresh, authentication and repository isolation.
- Measure bundle size, render performance and large-repository responsiveness.

  Completion gate: no known critical regressions and all supported workflows pass acceptance tests.

The later phases are sequentially dependent on the shared infrastructure, but can be adjusted after Phase 0 confirms which features and hooks already work. The roadmap does not imply that the existing product needs five additional weeks of entirely new backend development.

## 4. Final frontend folder structure

```
frontend/src/
├── layouts/
│   └── RepositoryStudioLayout.tsx
├── pages/
│   ├── RepositoryDetail.tsx
│   ├── RepositoryChat.tsx
│   ├── RepositoryExplainStudio.tsx
│   ├── RepositoryBugStudio.tsx
│   ├── RepositoryTestStudio.tsx
│   └── RepositoryReviewStudio.tsx
├── components/
│   ├── studios/
│   │   ├── StudioSubNav.tsx
│   │   ├── CodeViewer.tsx
│   │   ├── TargetFilePicker.tsx
│   │   ├── AnalysisHistory.tsx
│   │   ├── AnalysisStatus.tsx
│   │   ├── FindingCard.tsx
│   │   ├── FindingSeverityBadge.tsx
│   │   ├── SourceReference.tsx
│   │   ├── DiffViewer.tsx
│   │   └── EmptyErrorStates.tsx
├── hooks/
│   └── [reuse existing feature hooks]
├── lib/
│   ├── api.ts
│   └── testPath.ts
└── types/
    └── [reuse existing API contracts]
```

This is a target structure, not a requirement to move every existing file. Keep the project's established naming and directory conventions where they are already effective.

## 5. Studio-specific requirements

| Studio   | Required behavior                                                                | Important constraint                                                |
| -------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Explorer | Browse files, select symbols, view code and metadata                             | Lazy-load large trees and file content.                             |
| Chat     | Ask repository questions and inspect citations                                   | Distinguish genuine no-match from retrieval failure.                |
| Explain  | Select code, request explanation, navigate evidence and history                  | Never present an ungrounded citation as verified.                   |
| Bugs     | Filter findings, inspect evidence, copy proposed patches                         | Do not claim CVE/CWE classifications without support.               |
| Tests    | Configure supported target/framework, inspect generated tests and validate paths | Do not report passing tests unless execution actually occurred.     |
| Review   | Inspect findings, source references and supported diff context                   | Do not fabricate commit/diff support or arbitrary readiness scores. |

## 6. Design and interaction standards

- Desktop-first workspace: optimize for laptop and desktop; preserve usability on narrower screens.
- Resizable panes: provide sensible defaults and prevent panes from shrinking until content becomes unusable.
- Independent scrolling: the overall workspace should fit the viewport; code and result panes should scroll internally where appropriate.
- Consistent states: every request needs loading, success, empty, error and retry behavior.
- Source-grounded navigation: clicking a file or line reference should open the correct source location.
- Keyboard support: implement `Cmd/Ctrl + K` only when the command palette is functional; support escape, focus handling and accessible labels.
- Performance: lazy-load expensive editors and diagrams; avoid repeatedly fetching unchanged repository metadata.
- Safe interactions: copying a patch is allowed, but actual repository mutation requires an explicit, reviewed workflow.

## 7. Final acceptance checklist

### Release checklist

0/12

Existing repository routes and authentication remain functional.

All six workspace destinations work with direct URLs and browser refresh.

Shared navigation correctly reflects the active studio and repository.

Explorer and Chat retain their existing supported behavior.

Explain returns validated results, source references and accessible history.

Bug findings display correct severity, evidence and source locations.

Test generation shows accurate validation and execution statuses.

Code Review displays only information supported by its actual API contract.

Loading, timeout, empty result and provider failure states are handled.

No cross-repository data leaks occur when switching repository IDs.

Frontend tests, lint and production build pass.

Desktop layout, responsive behavior and large-repository performance are verified.

Copy checklist

## Final decision

Start with Phase 0, then complete Week 1 workspace infrastructure and Week 2 Explain Studio. Keep the existing backend, reuse verified hooks and APIs, and build shared components before implementing Bugs, Tests and Review.

This approach minimizes unnecessary rewrites, makes the frontend consistent, and creates a solid foundation for the more advanced coding-agent workflows you may add after Week 2.