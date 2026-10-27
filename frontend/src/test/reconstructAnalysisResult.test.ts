import { describe, it, expect } from 'vitest';
import { reconstructAnalysisResult } from '../lib/reconstructAnalysisResult';
import type { AnalysisRunDetailResponse } from '../types/analysis';

describe('reconstructAnalysisResult (F-03 / F-07)', () => {
  it('correctly reconstructs an explain run', () => {
    const detail: AnalysisRunDetailResponse = {
      id: 'run-exp-1',
      repository_id: 'repo-1',
      feature_type: 'explain',
      status: 'COMPLETED',
      target_path: 'src/auth.py',
      target_symbol: 'login_user',
      start_line: 10,
      end_line: 30,
      findings_count: 0,
      result_payload: {
        purpose: 'Authenticates user credentials and issues token.',
        logic_flow: ['Validates email format', 'Verifies hash', 'Issues JWT'],
        sources: [{ file_path: 'src/auth.py', start_line: 10, end_line: 30 }],
      },
      created_at: '2026-10-27T10:00:00Z',
    };

    const res = reconstructAnalysisResult(detail);
    expect(res.kind).toBe('explain');
    if (res.kind === 'explain') {
      expect(res.runId).toBe('run-exp-1');
      expect(res.target.path).toBe('src/auth.py');
      expect(res.target.symbol).toBe('login_user');
      expect(res.explanation.purpose).toBe('Authenticates user credentials and issues token.');
      expect(res.explanation.logic_flow).toHaveLength(3);
    }
  });

  it('correctly reconstructs a detect_bugs run', () => {
    const detail: AnalysisRunDetailResponse = {
      id: 'run-bugs-1',
      repository_id: 'repo-1',
      feature_type: 'detect_bugs',
      status: 'COMPLETED',
      target_path: 'src/parser.py',
      findings_count: 1,
      findings: [
        {
          id: 'find-1',
          category: 'off_by_one',
          severity: 'HIGH',
          title: 'Index error',
          description: 'Loop bounds exceeded',
          source_reference: { file_path: 'src/parser.py', start_line: 12, end_line: 14 },
          evidence: 'i <= len',
          source_type: 'STATIC',
        },
      ],
      result_payload: {
        category_counts: { off_by_one: 1 },
      },
      created_at: '2026-10-27T10:00:00Z',
    };

    const res = reconstructAnalysisResult(detail);
    expect(res.kind).toBe('bugs');
    if (res.kind === 'bugs') {
      expect(res.runId).toBe('run-bugs-1');
      expect(res.bugResult.findings).toHaveLength(1);
      expect(res.bugResult.total_findings).toBe(1);
      expect(res.bugResult.findings[0].title).toBe('Index error');
    }
  });

  it('correctly reconstructs a generate_tests run', () => {
    const detail: AnalysisRunDetailResponse = {
      id: 'run-tests-1',
      repository_id: 'repo-1',
      feature_type: 'generate_tests',
      status: 'COMPLETED',
      target_path: 'src/calculator.py',
      findings_count: 0,
      result_payload: {
        detected_framework: 'pytest',
        proposed_test_path: 'tests/test_calculator.py',
        test_content: 'def test_add(): assert 1 + 1 == 2',
        syntax_valid: true,
      },
      created_at: '2026-10-27T10:00:00Z',
    };

    const res = reconstructAnalysisResult(detail);
    expect(res.kind).toBe('tests');
    if (res.kind === 'tests') {
      expect(res.runId).toBe('run-tests-1');
      expect(res.testResult.result.test_content).toContain('test_add');
      expect(res.testResult.result.detected_framework).toBe('pytest');
      expect(res.testResult.result.proposed_test_path).toBe('tests/test_calculator.py');
    }
  });

  it('correctly reconstructs a review run', () => {
    const detail: AnalysisRunDetailResponse = {
      id: 'run-rev-1',
      repository_id: 'repo-1',
      feature_type: 'review',
      status: 'COMPLETED',
      target_path: 'src/api.py',
      findings_count: 1,
      result_payload: {
        report: {
          summary: 'Review found 1 security issue.',
          risk_level: 'HIGH',
          findings: [
            {
              id: 'rev-find-1',
              category: 'security',
              severity: 'HIGH',
              title: 'CORS wildcard with credentials',
              description: 'Insecure configuration',
              source_reference: { file_path: 'src/api.py', start_line: 5, end_line: 10 },
              evidence: 'allow_origins=["*"]',
              source_type: 'AI',
            },
          ],
        },
      },
      created_at: '2026-10-27T10:00:00Z',
    };

    const res = reconstructAnalysisResult(detail);
    expect(res.kind).toBe('review');
    if (res.kind === 'review') {
      expect(res.runId).toBe('run-rev-1');
      expect(res.reviewResult.report.summary).toContain('security issue');
      expect(res.reviewResult.report.risk_level).toBe('HIGH');
      expect(res.reviewResult.report.findings).toHaveLength(1);
    }
  });

  it('returns unavailable when payload is corrupted or missing without inventing fake data (F-07)', () => {
    const brokenDetail: AnalysisRunDetailResponse = {
      id: 'run-broken-1',
      repository_id: 'repo-1',
      feature_type: 'explain',
      status: 'COMPLETED',
      target_path: 'src/broken.py',
      findings_count: 0,
      result_payload: null,
      created_at: '2026-10-27T10:00:00Z',
    };

    const res = reconstructAnalysisResult(brokenDetail);
    expect(res.kind).toBe('unavailable');
    if (res.kind === 'unavailable') {
      expect(res.runId).toBe('run-broken-1');
      expect(res.message).toContain('missing or corrupted');
    }
  });

  it('returns unavailable on unknown feature type', () => {
    const unknownDetail = {
      id: 'run-unknown-1',
      repository_id: 'repo-1',
      feature_type: 'unknown_feature' as any,
      status: 'COMPLETED',
      findings_count: 0,
      created_at: '2026-10-27T10:00:00Z',
    } as AnalysisRunDetailResponse;

    const res = reconstructAnalysisResult(unknownDetail);
    expect(res.kind).toBe('unavailable');
  });
});
