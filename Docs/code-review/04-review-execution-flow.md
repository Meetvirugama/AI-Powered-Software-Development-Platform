# Review Execution Flow — AI-Powered Code Review Intelligence (F14)

## 1. End-to-End Sequence Diagram

The review workflow handles both webhook triggers (`pull_request.opened` / `pull_request.synchronize`) and manual API triggers.

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Developer
    participant GH as GitHub Webhook / REST API
    participant WH as WebhookWorker
    participant Handler as PullRequestEventHandler
    participant Incr as IncrementalReviewService
    participant Engine as CodeReviewService
    participant Static as StaticReviewEngine
    participant AI as Gemini LLM Gateway
    participant Gate as ReviewValidationService
    participant Dedup as ReviewDeduplicationService
    participant Pub as ReviewPublicationService
    participant DB as Platform DB (AnalysisRun/Findings)

    Dev->>GH: Pushes commit to PR branch
    GH->>WH: POST /api/v1/github/webhook (pull_request.synchronize)
    WH->>Handler: handle_pull_request_event()
    Handler->>Incr: review_pull_request_synchronize()

    Incr->>GH: get_pull_request_detail() & get_pull_request_files()
    GH-->>Incr: PR Head Commit SHA, Diff Patch, Changed Files

    Incr->>Engine: review(target=ReviewTarget(type="pr", ...))
    
    par Static Analysis
        Engine->>Static: run_static_review_on_changes()
        Static-->>Engine: Static Findings (Ruff, Bandit, ESLint, Biome)
    and AI Code Review
        Engine->>AI: generate_review_reasoning()
        AI-->>Engine: AI Findings
    end

    Engine->>Dedup: deduplicate_intra_run()
    Note over Dedup: Merges spatial overlaps into COMBINED findings
    Dedup-->>Engine: Deduplicated Findings

    Engine->>Gate: evaluate_quality_gate()
    Note over Gate: Partitions into Platform Findings and Publishable Findings
    Gate-->>Engine: QualityGateResult

    Engine->>DB: Persist AnalysisRun & AnalysisFinding records
    Engine-->>Incr: ReviewReport

    Incr->>Pub: publish_review_for_pull_request()
    Pub->>GH: list_pull_request_reviews() (Dedup existing comments)
    Pub->>GH: create_pull_request_review(commit_id, comments, body)
    GH-->>Pub: 200 OK (Review ID)

    Pub->>DB: Update run result_payload with review_publication metadata
    Pub-->>Incr: ReviewPublicationResult(status="PUBLISHED")
    Incr-->>Handler: Complete
```

## 2. Review States & Lifecycle Transitions

Findings transition through a well-defined state machine across commit synchronizations:

```mermaid
stateDiagram-v2
    [*] --> NEW: First detected on commit C1
    NEW --> ACTIVE: Persists unresolved on commit C2
    ACTIVE --> FIXED: Line/hunk modified, finding absent on commit C3
    FIXED --> REOPENED: Code reverted or reintroduced on commit C4
    NEW --> DISMISSED: Developer dismisses finding in Studio UI
    ACTIVE --> DISMISSED: Developer dismisses finding in Studio UI
    NEW --> SUPPRESSED: Config/inline rule suppress comment added
    ACTIVE --> SUPPRESSED: Config/inline rule suppress comment added
    DISMISSED --> [*]
    FIXED --> [*]
```

### Transition Validation Rules:
- **`NEW` $\to$ `ACTIVE`**: Allowed when unchanged on consecutive commit.
- **`NEW` / `ACTIVE` $\to$ `FIXED`**: Allowed when the diff rectifies the line or symbol.
- **`FIXED` $\to$ `REOPENED`**: Allowed if fingerprint reappears in a subsequent commit.
- **`DISMISSED` / `SUPPRESSED`**: Terminal or muted states; do not re-alert on PR sync.
