import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  buildFindingsMarkdown,
  buildFindingsSarif,
  exportFileStem,
  downloadTextFile,
  type FindingsExportInput,
} from '../lib/findingsExport';

describe('findingsExport', () => {
  const sampleInput: FindingsExportInput = {
    kind: 'Code Review',
    targetLabel: 'src/auth/service.py',
    runId: 'run-12345',
    summary: 'Overall code looks good with 2 security concerns.',
    riskLevel: 'HIGH',
    findings: [
      {
        id: 'f-1',
        title: 'Hardcoded secret detected',
        description: 'Secret token found in source code.',
        severity: 'CRITICAL',
        category: 'security',
        evidence: 'SECRET_KEY = "12345"',
        suggested_fix: 'Move to environment variable.',
        rule_id: 'SEC-001',
        confidence: 'high',
        source_type: 'STATIC',
        source_reference: {
          file_path: 'src/auth/service.py',
          start_line: 12,
          end_line: 14,
        },
      },
      {
        id: 'f-2',
        title: 'Unused import',
        description: 'os module is imported but never used.',
        severity: 'LOW',
        category: 'maintainability',
        rule_id: 'PY-W01',
        confidence: 'medium',
        source_type: 'STATIC',
        source_reference: {
          file_path: 'src/auth/service.py',
          start_line: 1,
        },
      },
    ],
    missingContext: ['Database migrations not inspected'],
    generatedAt: '2026-11-21T18:00:00Z',
  };

  it('builds Markdown report with severity ordering, citations, and summary', () => {
    const md = buildFindingsMarkdown(sampleInput);

    expect(md).toContain('# Code Review Report: src/auth/service.py');
    expect(md).toContain('- **Run:** `run-12345`');
    expect(md).toContain('- **Overall risk:** HIGH');
    expect(md).toContain('## Summary');
    expect(md).toContain('Overall code looks good with 2 security concerns.');
    expect(md).toContain('### 1. [CRITICAL] Hardcoded secret detected');
    expect(md).toContain('`src/auth/service.py:L12-L14`');
    expect(md).toContain('**Evidence**');
    expect(md).toContain('SECRET_KEY = "12345"');
    expect(md).toContain('**Suggested fix:** Move to environment variable.');
    expect(md).toContain('### 2. [LOW] Unused import');
    expect(md).toContain('`src/auth/service.py:L1`');
    expect(md).toContain('## Analysis Limitations');
    expect(md).toContain('- Database migrations not inspected');
  });

  it('builds Markdown report for zero findings', () => {
    const md = buildFindingsMarkdown({
      kind: 'Bug Detection',
      targetLabel: 'main.py',
      findings: [],
    });
    expect(md).toContain('# Bug Detection Report: main.py');
    expect(md).toContain('No findings.');
  });

  it('builds valid SARIF 2.1.0 output', () => {
    const sarifStr = buildFindingsSarif(sampleInput);
    const parsed = JSON.parse(sarifStr);

    expect(parsed.version).toBe('2.1.0');
    expect(parsed.$schema).toBe('https://json.schemastore.org/sarif-2.1.0.json');
    expect(parsed.runs).toHaveLength(1);

    const run = parsed.runs[0];
    expect(run.tool.driver.name).toBe('AI Dev Platform Code Review');
    expect(run.results).toHaveLength(2);

    const [critResult, lowResult] = run.results;
    expect(critResult.level).toBe('error');
    expect(critResult.ruleId).toBe('SEC-001');
    expect(critResult.locations[0].physicalLocation.artifactLocation.uri).toBe('src/auth/service.py');
    expect(critResult.locations[0].physicalLocation.region.startLine).toBe(12);
    expect(critResult.locations[0].physicalLocation.region.endLine).toBe(14);

    expect(lowResult.level).toBe('note');
    expect(lowResult.ruleId).toBe('PY-W01');
  });

  it('generates sanitized file stem', () => {
    expect(exportFileStem('Code Review', 'src/auth/service.py')).toBe('review-src-auth-service-py');
    expect(exportFileStem('Bug Detection', 'PR #42: Feature & Bugfixes')).toBe('bugs-PR-42-Feature-Bugfixes');
  });

  describe('downloadTextFile', () => {
    beforeEach(() => {
      vi.restoreAllMocks();
    });

    it('triggers anchor download and revokes object URL', () => {
      const mockUrl = 'blob:http://localhost/test-uuid';
      const createObjectURL = vi.spyOn(window.URL, 'createObjectURL').mockReturnValue(mockUrl);
      vi.spyOn(window.URL, 'revokeObjectURL').mockImplementation(() => {});

      const clickSpy = vi.fn();
      const appendSpy = vi.spyOn(document.body, 'appendChild');
      const removeSpy = vi.spyOn(HTMLAnchorElement.prototype, 'remove');
      vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(clickSpy);

      downloadTextFile('# Report', 'report.md', 'text/markdown');

      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(appendSpy).toHaveBeenCalledTimes(1);
      expect(clickSpy).toHaveBeenCalledTimes(1);
      expect(removeSpy).toHaveBeenCalledTimes(1);
    });
  });
});
