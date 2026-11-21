/**
 * findingsExport — export Code Review and Bug Detection results (Module 10
 * "Review Export"; also used by the Bug Studio).
 *
 * Two formats:
 *  - Markdown: for people — paste into a PR description, wiki or ticket.
 *  - SARIF 2.1.0: the standard static-analysis interchange format, so results
 *    can be uploaded to GitHub Code Scanning or opened in IDE SARIF viewers.
 *
 * Pure builders (no DOM) plus one small download helper.
 */

export interface ExportableFinding {
  id: string;
  title: string;
  description: string;
  severity: string;
  category: string;
  evidence?: string | null;
  suggested_fix?: string | null;
  rule_id?: string | null;
  confidence?: string | null;
  source_type?: string | null;
  source_reference?: {
    file_path: string;
    start_line?: number | null;
    end_line?: number | null;
    revision?: string | null;
  } | null;
}

export interface FindingsExportInput {
  kind: 'Code Review' | 'Bug Detection';
  targetLabel: string;
  runId?: string;
  summary?: string | null;
  riskLevel?: string | null;
  findings: ExportableFinding[];
  missingContext?: string[];
  generatedAt?: string;
}

const SEVERITY_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'];

function location(f: ExportableFinding): string {
  const ref = f.source_reference;
  if (!ref?.file_path) return 'unknown location';
  if (ref.start_line == null) return ref.file_path;
  const end = ref.end_line != null && ref.end_line !== ref.start_line ? `-L${ref.end_line}` : '';
  return `${ref.file_path}:L${ref.start_line}${end}`;
}

function fenceFor(text: string): string {
  const longest = Math.max(2, ...Array.from(text.matchAll(/`+/g), (m) => m[0].length));
  return '`'.repeat(longest + 1);
}

function sortBySeverity(findings: ExportableFinding[]): ExportableFinding[] {
  const rank = (s: string) => {
    const i = SEVERITY_ORDER.indexOf(String(s).toUpperCase());
    return i === -1 ? SEVERITY_ORDER.length : i;
  };
  return [...findings].sort((a, b) => rank(a.severity) - rank(b.severity));
}

export function buildFindingsMarkdown(input: FindingsExportInput): string {
  const generatedAt = input.generatedAt ?? new Date().toISOString();
  const findings = sortBySeverity(input.findings);
  const counts = SEVERITY_ORDER.map((s) => [s, findings.filter((f) => String(f.severity).toUpperCase() === s).length] as const)
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${s}: ${n}`)
    .join(' · ');

  const lines: string[] = [
    `# ${input.kind} Report: ${input.targetLabel}`,
    '',
    `- **Generated:** ${generatedAt}`,
  ];
  if (input.runId) lines.push(`- **Run:** \`${input.runId}\``);
  if (input.riskLevel) lines.push(`- **Overall risk:** ${input.riskLevel}`);
  lines.push(`- **Findings:** ${findings.length}${counts ? ` (${counts})` : ''}`);
  if (input.summary?.trim()) lines.push('', '## Summary', '', input.summary.trim());

  if (findings.length) {
    lines.push('', '## Findings');
    findings.forEach((f, i) => {
      const meta = [f.category, f.rule_id ? `rule \`${f.rule_id}\`` : null, f.confidence ? `confidence ${f.confidence}` : null, f.source_type]
        .filter(Boolean)
        .join(' · ');
      lines.push('', `### ${i + 1}. [${String(f.severity).toUpperCase()}] ${f.title}`, '', `\`${location(f)}\` — ${meta}`, '', f.description.trim());
      if (f.evidence?.trim()) {
        const fence = fenceFor(f.evidence);
        lines.push('', '**Evidence**', '', fence, f.evidence.replace(/\n+$/, ''), fence);
      }
      if (f.suggested_fix?.trim()) lines.push('', `**Suggested fix:** ${f.suggested_fix.trim()}`);
    });
  } else {
    lines.push('', 'No findings.');
  }

  if (input.missingContext?.length) {
    lines.push('', '## Analysis Limitations', '', ...input.missingContext.map((m) => `- ${m}`));
  }
  return `${lines.join('\n')}\n`;
}

function sarifLevel(severity: string): 'error' | 'warning' | 'note' {
  const s = String(severity).toUpperCase();
  if (s === 'CRITICAL' || s === 'HIGH') return 'error';
  if (s === 'MEDIUM') return 'warning';
  return 'note';
}

/** SARIF 2.1.0 log with one run. Rules are derived from rule_id (or category). */
export function buildFindingsSarif(input: FindingsExportInput): string {
  const ruleIds = new Map<string, ExportableFinding>();
  const ruleIdOf = (f: ExportableFinding) => f.rule_id || `${input.kind === 'Code Review' ? 'review' : 'bug'}/${f.category}`;
  input.findings.forEach((f) => {
    if (!ruleIds.has(ruleIdOf(f))) ruleIds.set(ruleIdOf(f), f);
  });

  const log = {
    $schema: 'https://json.schemastore.org/sarif-2.1.0.json',
    version: '2.1.0',
    runs: [
      {
        tool: {
          driver: {
            name: `AI Dev Platform ${input.kind}`,
            informationUri: 'https://github.com/Meetvirugama/AI-Powered-Software-Development-Platform',
            rules: Array.from(ruleIds.entries()).map(([id, f]) => ({
              id,
              shortDescription: { text: f.title.slice(0, 200) },
              properties: { category: f.category },
            })),
          },
        },
        automationDetails: input.runId ? { id: input.runId } : undefined,
        results: input.findings.map((f) => {
          const ref = f.source_reference;
          const region =
            ref?.start_line != null
              ? { startLine: ref.start_line, endLine: ref.end_line ?? ref.start_line }
              : undefined;
          return {
            ruleId: ruleIdOf(f),
            level: sarifLevel(f.severity),
            message: { text: `${f.title}\n\n${f.description}${f.suggested_fix ? `\n\nSuggested fix: ${f.suggested_fix}` : ''}` },
            locations: ref?.file_path
              ? [{ physicalLocation: { artifactLocation: { uri: ref.file_path }, ...(region ? { region } : {}) } }]
              : [],
            partialFingerprints: { findingId: f.id },
            properties: {
              severity: f.severity,
              category: f.category,
              confidence: f.confidence ?? undefined,
              sourceType: f.source_type ?? undefined,
              revision: ref?.revision ?? undefined,
            },
          };
        }),
      },
    ],
  };
  return `${JSON.stringify(log, null, 2)}\n`;
}

export function exportFileStem(kind: FindingsExportInput['kind'], targetLabel: string): string {
  const base = targetLabel.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(-60) || 'target';
  return `${kind === 'Code Review' ? 'review' : 'bugs'}-${base}`;
}

export function downloadTextFile(content: string, filename: string, mime: string): void {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
