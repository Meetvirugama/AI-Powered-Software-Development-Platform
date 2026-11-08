# Database & API Changes — AI-Powered Code Review Intelligence (F14)

## 1. Database Schema & Data Models

### 1.1 `AnalysisFinding.finding_metadata` (JSONB)
To guarantee 100% backward compatibility and eliminate risky schema migrations, finding lifecycle and feedback tracking are persisted inside the existing `finding_metadata` JSONB column.

#### Structure of `finding_metadata`:
```json
{
  "lifecycle": {
    "status": "ACTIVE",
    "first_seen_commit": "c0ffee11",
    "last_seen_commit": "deadbeef",
    "resolved_commit": null,
    "history": [
      {
        "status": "NEW",
        "commit_sha": "c0ffee11",
        "timestamp": "2026-11-08T09:00:00Z"
      },
      {
        "status": "ACTIVE",
        "commit_sha": "deadbeef",
        "timestamp": "2026-11-08T10:15:00Z"
      }
    ]
  },
  "feedback": {
    "feedback_type": "useful",
    "comment": "Saved a production SQL injection breach!",
    "created_at": "2026-11-08T10:30:00Z"
  },
  "deduplication_key": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "evidence_level": "PROVEN",
  "is_changed_line": true
}
```

### 1.2 `Repository` Model Configuration
Existing columns utilized for code review automation:
- `pr_review_enabled` (`Boolean`, default `False`): Opt-in master gate for automated PR reviews.
- `pr_review_drafts` (`Boolean`, default `False`): Whether to review draft PRs.

---

## 2. API Endpoints

### 2.1 Trigger Review Publication
- **Route**: `POST /api/v1/repositories/{id}/review/publish`
- **Auth**: Bearer JWT (Repository Owner)
- **Request Body**:
  ```json
  {
    "run_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "pr_number": 42,
    "commit_sha": "a1b2c3d4",
    "force_publish": false,
    "max_comments": 15
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "status": "PUBLISHED",
    "review_id": 987654321,
    "pr_number": 42,
    "commit_sha": "a1b2c3d4",
    "published_comments_count": 3,
    "skipped_reason": null,
    "error_message": null,
    "published_at": "2026-11-08T10:45:00Z"
  }
  ```

### 2.2 Submit Finding Feedback
- **Route**: `POST /api/v1/analysis-runs/{run_id}/findings/{finding_id}/feedback`
- **Auth**: Bearer JWT
- **Request Body**:
  ```json
  {
    "feedback_type": "useful",
    "comment": "Accurate detection"
  }
  ```
- **Response**: `200 OK`
  ```json
  {
    "finding_id": "3c4d5e6f-...",
    "feedback_type": "useful",
    "comment": "Accurate detection",
    "repository_stats": {
      "useful_count": 14,
      "not_useful_count": 2,
      "false_positive_count": 1,
      "acceptance_rate": 0.875,
      "false_positive_rate": 0.059
    }
  }
  ```

### 2.3 Get Review Automation Settings
- **Route**: `GET /api/v1/repositories/{id}/review/settings`
- **Auth**: Bearer JWT
- **Response**: `200 OK`
  ```json
  {
    "repository_id": "...",
    "pr_review_enabled": true,
    "pr_review_drafts": false,
    "max_comments": 15,
    "min_confidence": "medium",
    "changed_lines_only": true
  }
  ```

### 2.4 Update Review Automation Settings
- **Route**: `PATCH /api/v1/repositories/{id}/review/settings`
- **Auth**: Bearer JWT
- **Request Body**:
  ```json
  {
    "pr_review_enabled": true,
    "pr_review_drafts": false,
    "max_comments": 20,
    "min_confidence": "high",
    "changed_lines_only": true
  }
  ```
- **Response**: `200 OK` (returns updated settings object)
