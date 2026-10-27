"""Frontend Acceptance Tests for Week 2 Day 7 (Dhramraj).

Verifies:
1. Analysis TypeScript types aligned with shared contracts (`frontend/src/types/analysis.ts`).
2. Analysis service layer implements all endpoints (`frontend/src/services/analysis.ts`).
3. RepositoryDetail page synchronizes review target when selecting a file (`frontend/src/pages/RepositoryDetail.tsx`).
4. RepositoryDetail page fetches up to 500 files when repository is synced.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_analysis_types_aligned_with_shared_contracts():
    types_ts = (REPO_ROOT / "frontend" / "src" / "types" / "analysis.ts").read_text(encoding="utf-8")
    assert "export type AnalysisFeatureType" in types_ts
    assert "export interface AnalysisTarget" in types_ts
    assert "export interface BugFinding" in types_ts
    assert "export interface CodeExplanation" in types_ts
    assert "export interface TestGenerationResult" in types_ts
    assert "export interface ReviewReport" in types_ts
    assert "export interface AnalysisRunMetricsSummaryResponse" in types_ts


def test_analysis_service_implements_all_endpoints():
    service_ts = (REPO_ROOT / "frontend" / "src" / "services" / "analysis.ts").read_text(encoding="utf-8")
    assert "export async function explainCode(" in service_ts
    assert "export async function detectBugs(" in service_ts
    assert "export async function generateTests(" in service_ts
    assert "export async function reviewCode(" in service_ts
    assert "export async function getAnalysisRuns(" in service_ts
    assert "export async function getAnalysisRunsSummary(" in service_ts


def test_repository_detail_synchronizes_review_target_on_file_select():
    detail_tsx = (REPO_ROOT / "frontend" / "src" / "pages" / "RepositoryDetail.tsx").read_text(encoding="utf-8")
    assert "setReviewTarget((prev) =>" in detail_tsx
    assert "prev.type === 'file' ? { type: 'file', path: file.path } : prev" in detail_tsx


def test_repository_detail_fetches_500_files_when_synced():
    detail_tsx = (REPO_ROOT / "frontend" / "src" / "pages" / "RepositoryDetail.tsx").read_text(encoding="utf-8")
    assert "useRepositoryFiles(id, 1, 500, { enabled: isReady })" in detail_tsx
