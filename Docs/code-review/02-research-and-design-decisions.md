# 02 — Research and Design Decisions: AI Code Review

**Document**: `Docs/code-review/02-research-and-design-decisions.md`  
**Feature**: F14 — AI-Powered Code Review Intelligence  
**Author**: Antigravity Senior Architecture & QA Team  
**Status**: APPROVED  

---

## 1. Research Decision Matrix

| Research / Project | Adopted Technique | Platform Implementation | Priority | Status | Source URL & Reference |
|---|---|---|---|---|---|
| **Google AutoCommenter** (P-14) | Separate deterministic static analysis from AI reasoning; precision over recall; developer feedback loop; conservative comment budget. | Built separate `StaticReviewer` & `ReviewValidationService`; thumbs up/down feedback API; max comments threshold (default 10); strict evidence gating. | P1 | **IMPLEMENTED** | [AutoCommenter Paper](https://research.google/pubs/ai-assisted-assessment-of-coding-practices-in-industrial-code-review/) |
| **CodeReviewer** (P-15) | Diff-aware context retrieval; actionable suggestions; concrete failure scenarios. | `ReviewContextBuilder` extracts enclosing symbols & blast radius; AI prompt enforces concrete failure reproduction and suggested fix diffs. | P1 | **IMPLEMENTED** | [CodeReviewer Paper](https://arxiv.org/abs/2203.09095) |
| **PR-Agent** (OSS-07) | Persistent finding fingerprints; multi-round incremental review; comment deduplication; concise executive summaries. | `ReviewDeduplicationService` computes stable SHA-256 fingerprints; `IncrementalReviewService` handles `synchronize` diffing; consolidated review summary block. | P1 | **IMPLEMENTED** | [PR-Agent Repository](https://github.com/qodo-ai/pr-agent), [Docs](https://docs.pr-agent.ai/) |
| **GitHub REST API** | Single atomic review submission containing multiple inline comments anchored to specific commit SHA. | `GitHubClient.create_pull_request_review()` enhanced with `commit_id`, `path`, `line`, `side`, and `body` validation; default `event="COMMENT"`. | P1 | **IMPLEMENTED** | [GitHub REST Pulls API](https://docs.github.com/en/rest/pulls/reviews) |
| **GitHub MCP Server** (MCP-01) | Architectural evaluation of Model Context Protocol for GitHub operations. | Assessed: platform already owns a battle-tested `GitHubClient` and token manager; introducing external MCP subprocess adds transport overhead without added value. Retained direct API client. | P3 | **ADAPTED / NOT USED DIRECTLY** | [GitHub MCP Server](https://github.com/github/github-mcp-server) |
| **ESLint & Biome** | Fast, configurable JS/TS static diagnostics with structured JSON output. | Created `StaticReviewer` adapters for ESLint and Biome with auto-detection of repository config files (`eslint.config.*`, `biome.json`) and sandboxed execution. | P2 | **IMPLEMENTED** | [ESLint Docs](https://eslint.org/docs/latest/), [Biome Docs](https://biomejs.dev/) |

---

## 2. In-Depth Adaptation Details

### 2.1 Google AutoCommenter: Precision Over Recall & Developer Feedback
- **Original Problem**: High-volume AI code reviews generate developer fatigue and resentment when comments are noisy or nitpicky.
- **AutoCommenter Finding**: Comments must be actionable, highly confident, and respect language conventions. Success was tracked using "usefulness" reactions from Google engineers.
- **Our Adaptation**:
  1. **Two-Tier Result Collections**: All valid findings remain available in the platform studio UI, but only `STRONG` and `PROVEN` findings on changed lines are eligible for GitHub PR comments.
  2. **Developer Feedback Loop**: Each finding in the platform UI and posted review includes feedback anchors (`useful`, `not_useful`, `false_positive`), stored in database records to compute model acceptance rates.
  3. **Conservative Cap**: Hard limit on inline comments per review (default 10) to prevent overwhelming PR authors.

### 2.2 CodeReviewer: Context-Aware Reasoning & Concrete Failure Scenarios
- **Original Problem**: LLM reviewers hallucinate syntax errors or misunderstand changes when only viewing raw isolated diff hunks.
- **CodeReviewer Principle**: Changes must be understood in the context of surrounding function signatures, caller hierarchy, and project types.
- **Our Adaptation**:
  1. `ReviewContextBuilder` calculates the dependency blast radius: if a modified function changes its signature, callers across other files are supplied in fenced context.
  2. The prompt specifically instructs the model to describe a *concrete execution trace* or input that triggers the bug, rather than generic code smell commentary.

### 2.3 PR-Agent: Persistent Finding Lifecycle & Incremental Review
- **Original Problem**: Consecutive commits to a PR trigger repeated identical comments, irritating contributors.
- **PR-Agent Principle**: Keep track of findings across review runs, fingerprint each finding, and on incremental pushes (`synchronize`), only review the delta between previous HEAD and new HEAD.
- **Our Adaptation**:
  1. `ReviewDeduplicationService` computes deterministic fingerprints:
     $$\text{Fingerprint} = \text{SHA256}(\text{repo\_id} + \text{path} + \text{category} + \text{rule\_id\_or\_title} + \text{symbol})$$
  2. `IncrementalReviewService` retrieves the previously reviewed commit SHA, diffs it with the new HEAD, re-checks touched files, and tracks lifecycle states (`NEW`, `ACTIVE`, `FIXED`, `REOPENED`).

### 2.4 GitHub MCP Server Evaluation
- **Evaluation**: The GitHub MCP server (`MCP-01`) provides tools such as `get_pull_request`, `create_pull_request_review`, and `list_pull_request_comments`.
- **Verdict**: The platform's existing `GitHubClient` and `GitHubService` already handle token resolution, multi-tenant installation tokens, secret redaction, and rate-limiting. Bypassing or wrapping these in an external MCP process would degrade performance, introduce unnecessary JSON-RPC serialization, and increase failure points. We directly utilize `GitHubClient` with verified REST endpoints.

### 2.5 ESLint & Biome Integration
- **Original Problem**: Python-only static analysis left JavaScript/TypeScript repositories without deterministic linting.
- **Our Adaptation**:
  1. Config-driven detection:
     - Biome preferred if `biome.json` is present (exceptional performance).
     - ESLint preferred if `.eslintrc.*` or `eslint.config.*` is present.
  2. Run inside sandboxed execution runner with 60-second timeouts and output size limits.
