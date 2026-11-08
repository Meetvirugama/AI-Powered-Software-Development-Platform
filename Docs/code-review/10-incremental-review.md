# 10 — Incremental Pull Request Review Architecture

**Document**: `Docs/code-review/10-incremental-review.md`  
**Feature**: F14 — AI-Powered Code Review Intelligence  
**Author**: Antigravity Senior Architecture & QA Team  
**Status**: IMPLEMENTED & TESTED  

---

## 1. Incremental Review Workflow

Adopting the **PR-Agent (OSS-07)** incremental review design, the platform processes pull request updates (`synchronize` webhook event) by evaluating the code delta between consecutive pushes:

```mermaid
sequenceDiagram
    autonumber
    actor Author as PR Author
    participant Webhook as Webhook Worker
    participant Inc as IncrementalReviewService
    participant Life as ReviewLifecycleService
    participant Pub as ReviewPublicationService
    participant GH as GitHub REST API

    Author->>Webhook: git push new commit (synchronize)
    Webhook->>Inc: execute_incremental_review(prev_sha, new_sha)
    Inc->>Life: track_findings_across_commits(curr_findings, prev_findings)
    Note over Life: Match by stable SHA-256 fingerprint
    Life-->>Inc: (updated_current, resolved_findings)
    Note over Inc: Filter publishable: Only NEW or REOPENED findings
    Note over Inc: Compose incremental summary header (N new, M resolved)
    Inc->>Pub: publish_pull_request_review(commit_sha=new_sha, findings=NEW_only)
    Pub->>GH: POST /repos/{owner}/{repo}/pulls/{n}/reviews
    GH-->>Pub: review_id: 9999
    Pub-->>Inc: Status: PUBLISHED
```

---

## 2. Preventing Repetitive Noise on GitHub

On PR updates, contributors are annoyed when bots repeat comments on files that were already reviewed and unchanged.
The incremental engine strictly ensures:
1. Findings in subsequent commits whose fingerprint matches an existing issue are tagged `ACTIVE`.
2. Only findings tagged `NEW` or `REOPENED` are eligible for inline comments on incremental runs.
3. Issues resolved by the author's new commit are marked `FIXED` and celebrated in the executive overview (`"Previously Detected Issues Resolved: M"`).
4. Commits that accidentally re-introduce a previously resolved defect are tagged `REOPENED` and brought to the developer's attention.
