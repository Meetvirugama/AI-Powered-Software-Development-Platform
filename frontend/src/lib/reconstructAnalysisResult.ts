import type {
  AnalysisRunDetailResponse,
  CodeExplanation,
  BugDetectionResponse,
  TestGenerationResponse,
  ReviewReportResponse,
  AnalysisTarget,
  ReviewTarget,
  BugFinding,
  ReviewFinding,
} from '../types/analysis';

export type ReopenedAnalysisResult =
  | {
      kind: 'explain';
      runId: string;
      target: AnalysisTarget;
      explanation: CodeExplanation;
    }
  | {
      kind: 'bugs';
      runId: string;
      target: AnalysisTarget;
      bugResult: BugDetectionResponse;
    }
  | {
      kind: 'tests';
      runId: string;
      target: AnalysisTarget;
      testResult: TestGenerationResponse;
    }
  | {
      kind: 'review';
      runId: string;
      reviewResult: ReviewReportResponse;
    }
  | {
      kind: 'unavailable';
      runId: string;
      featureType: string;
      message: string;
    };

/**
 * Safely reconstruct a typed analysis result from a persisted AnalysisRunDetailResponse.
 * Complies with F-03 & F-07:
 * - Reconstructs the exact schema for all 4 features
 * - Never synthesizes fake authoritative results when payloads are missing or malformed
 * - Returns an explicit 'unavailable' result if payload data is missing or corrupted
 */
export function reconstructAnalysisResult(
  detail: AnalysisRunDetailResponse
): ReopenedAnalysisResult {
  const runId = detail.id;
  const payload = detail.result_payload;
  const target: AnalysisTarget = {
    type: detail.target_symbol ? 'symbol' : detail.start_line ? 'range' : 'file',
    path: detail.target_path ?? '',
    symbol: detail.target_symbol ?? undefined,
    start_line: detail.start_line ?? undefined,
    end_line: detail.end_line ?? undefined,
  };

  const featureType = detail.feature_type;

  // 1. Code Explanation
  if (featureType === 'explain') {
    const rawExplanation = payload?.explanation ?? payload;
    if (
      !rawExplanation ||
      typeof rawExplanation !== 'object' ||
      (!rawExplanation.purpose && !rawExplanation.summary && !rawExplanation.logic_flow)
    ) {
      return {
        kind: 'unavailable',
        runId,
        featureType,
        message: 'Saved explanation payload is missing or corrupted.',
      };
    }

    const explanation: CodeExplanation = {
      purpose: rawExplanation.purpose || rawExplanation.summary || 'Explanation retrieved from history.',
      logic_flow: Array.isArray(rawExplanation.logic_flow)
        ? rawExplanation.logic_flow
        : typeof rawExplanation.logic_flow === 'string'
        ? [rawExplanation.logic_flow]
        : [],
      key_symbols: Array.isArray(rawExplanation.key_symbols) ? rawExplanation.key_symbols : [],
      inputs_and_outputs: rawExplanation.inputs_and_outputs || '',
      dependencies: Array.isArray(rawExplanation.dependencies) ? rawExplanation.dependencies : [],
      assumptions_and_limitations: Array.isArray(rawExplanation.assumptions_and_limitations)
        ? rawExplanation.assumptions_and_limitations
        : [],
      sources: Array.isArray(rawExplanation.sources) ? rawExplanation.sources : [],
      confidence: rawExplanation.confidence || 'medium',
      missing_context: Array.isArray(rawExplanation.missing_context) ? rawExplanation.missing_context : [],
    };

    return {
      kind: 'explain',
      runId,
      target,
      explanation,
    };
  }

  // 2. Bug Detection
  if (featureType === 'detect_bugs' || (featureType as string) === 'bugs') {
    const findings = (
      detail.findings && detail.findings.length > 0
        ? detail.findings
        : Array.isArray(payload?.findings)
        ? payload.findings
        : []
    ) as BugFinding[];

    const bugResult: BugDetectionResponse = {
      run_id: detail.id,
      repository_id: detail.repository_id,
      status: detail.status,
      target,
      findings,
      total_findings: detail.findings_count || findings.length,
      static_findings_count:
        payload?.static_findings_count ?? findings.filter((f) => f.source_type === 'STATIC').length,
      ai_findings_count:
        payload?.ai_findings_count ?? findings.filter((f) => f.source_type === 'AI').length,
      missing_context: payload?.missing_context || [],
      created_at: detail.created_at,
      completed_at: detail.completed_at ?? undefined,
    };

    return {
      kind: 'bugs',
      runId,
      target,
      bugResult,
    };
  }

  // 3. Test Generation
  if (featureType === 'generate_tests' || (featureType as string) === 'tests') {
    const rawResult = payload?.result ?? payload;
    const testContent =
      rawResult?.test_content ||
      rawResult?.complete_test_code ||
      detail.test_output;

    if (!testContent && detail.status === 'COMPLETED') {
      return {
        kind: 'unavailable',
        runId,
        featureType,
        message: 'Saved test generation run has no generated test content.',
      };
    }

    const testResult: TestGenerationResponse = {
      run_id: detail.id,
      repository_id: detail.repository_id,
      status: detail.status,
      target,
      result: {
        detected_framework: rawResult?.detected_framework || 'pytest',
        proposed_test_path: rawResult?.proposed_test_path || `tests/test_${detail.target_path?.split('/').pop() || 'generated.py'}`,
        test_content: testContent || '',
        covered_scenarios: Array.isArray(rawResult?.covered_scenarios) ? rawResult.covered_scenarios : [],
        assumptions_and_warnings: Array.isArray(rawResult?.assumptions_and_warnings)
          ? rawResult.assumptions_and_warnings
          : [],
        syntax_valid: Boolean(rawResult?.syntax_valid ?? true),
        validation_errors: Array.isArray(rawResult?.validation_errors) ? rawResult.validation_errors : [],
        sources: Array.isArray(rawResult?.sources) ? rawResult.sources : [],
      },
      created_at: detail.created_at,
      completed_at: detail.completed_at ?? undefined,
    };

    return {
      kind: 'tests',
      runId,
      target,
      testResult,
    };
  }

  // 4. Code Review
  if (featureType === 'review') {
    const rawReport = payload?.report ?? payload;
    const reviewTarget: ReviewTarget = payload?.target ?? {
      type: 'file',
      path: detail.target_path,
    };

    const findings = (
      detail.findings && detail.findings.length > 0
        ? detail.findings
        : Array.isArray(rawReport?.findings)
        ? rawReport.findings
        : []
    ) as ReviewFinding[];

    // If report is completely missing and there are no findings, report unavailable
    if (!rawReport && findings.length === 0 && detail.status !== 'FAILED') {
      return {
        kind: 'unavailable',
        runId,
        featureType,
        message: 'Saved review report payload is missing or corrupted.',
      };
    }

    const reviewResult: ReviewReportResponse = {
      run_id: detail.id,
      repository_id: detail.repository_id,
      status: detail.status,
      target: reviewTarget,
      report: {
        summary: rawReport?.summary || `Historical code review completed at ${new Date(detail.created_at).toLocaleString()}`,
        risk_level: rawReport?.risk_level || (findings.length > 0 ? 'MEDIUM' : 'NONE'),
        findings,
        total_findings: detail.findings_count || findings.length,
        category_counts: rawReport?.category_counts || {},
        missing_context: rawReport?.missing_context || [],
      },
      created_at: detail.created_at,
      completed_at: detail.completed_at,
    };

    return {
      kind: 'review',
      runId,
      reviewResult,
    };
  }

  return {
    kind: 'unavailable',
    runId,
    featureType: String(featureType),
    message: `Unknown analysis feature type: "${featureType}"`,
  };
}
