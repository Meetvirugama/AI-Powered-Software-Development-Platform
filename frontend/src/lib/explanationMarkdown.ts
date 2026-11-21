/**
 * explanationMarkdown — turns a single CodeExplanation into a portable Markdown
 * report (Module 7 "Analysis Export").
 *
 * Why this exists: the history drawer can export *datasets* of many runs
 * (jsonl/json/langfuse) for evaluation, but a developer who just read one
 * explanation had no way to save or share it. Markdown is the natural format:
 * it renders in GitHub/PRs/wikis and keeps code blocks and source citations.
 *
 * The builder is pure (no DOM) so it can be unit-tested and reused.
 */
import type { CodeExplanation, SourceReference } from '../types/analysis';

export interface ExplanationMarkdownOptions {
  targetFilePath?: string;
  /** ISO timestamp; defaults to now. Injected for deterministic tests. */
  generatedAt?: string;
}

function list(items: readonly string[] | undefined): string {
  return (items ?? [])
    .filter((item) => typeof item === 'string' && item.trim())
    .map((item) => `- ${item.trim()}`)
    .join('\n');
}

function numbered(items: readonly string[] | undefined): string {
  return (items ?? [])
    .filter((item) => typeof item === 'string' && item.trim())
    .map((item, index) => `${index + 1}. ${item.trim()}`)
    .join('\n');
}

function formatSource(source: SourceReference): string {
  const range =
    source.start_line != null
      ? source.end_line != null && source.end_line !== source.start_line
        ? `:L${source.start_line}-L${source.end_line}`
        : `:L${source.start_line}`
      : '';
  const symbol = source.symbol_name ? ` (\`${source.symbol_name}\`)` : '';
  const revision = source.revision ? ` @ ${source.revision.slice(0, 12)}` : '';
  return `- \`${source.file_path}${range}\`${symbol}${revision}`;
}

/** Picks a fence long enough that code containing ``` cannot break out of it. */
function fenceFor(code: string): string {
  const longest = Math.max(2, ...Array.from(code.matchAll(/`+/g), (m) => m[0].length));
  return '`'.repeat(longest + 1);
}

function languageFor(path?: string): string {
  const ext = path?.split('.').pop()?.toLowerCase() ?? '';
  const map: Record<string, string> = {
    py: 'python', ts: 'typescript', tsx: 'tsx', js: 'javascript', jsx: 'jsx',
    go: 'go', rs: 'rust', java: 'java', rb: 'ruby', c: 'c', h: 'c', cpp: 'cpp',
    cs: 'csharp', kt: 'kotlin', php: 'php', sh: 'bash', sql: 'sql',
  };
  return map[ext] ?? '';
}

export function buildExplanationMarkdown(
  explanation: CodeExplanation,
  options: ExplanationMarkdownOptions = {},
): string {
  const { targetFilePath } = options;
  const generatedAt = options.generatedAt ?? new Date().toISOString();
  const sections: string[] = [];
  const push = (title: string, body: string | undefined | null) => {
    if (body && body.trim()) sections.push(`## ${title}\n\n${body.trim()}`);
  };

  sections.push(
    `# Code Explanation${targetFilePath ? `: \`${targetFilePath}\`` : ''}\n\n` +
      `- **Confidence:** ${explanation.confidence}\n` +
      `- **Generated:** ${generatedAt}`,
  );

  if (explanation.has_redacted_content) {
    push(
      'Security Notice',
      explanation.redaction_notice ||
        `Source contained ${explanation.redacted_occurrences ?? 'some'} redacted secret value(s).`,
    );
  }

  push('Purpose', explanation.purpose);
  push('Detailed Explanation', explanation.detailed_explanation);
  push('Logic Flow', numbered(explanation.logic_flow));
  push('Execution Flow', numbered(explanation.execution_flow));
  push('Inputs and Outputs', explanation.inputs_and_outputs);
  push('Output Explanation', explanation.code_output_explanation);

  const symbols = (explanation.key_symbols ?? [])
    .map((s) => {
      const lines = s.start_line != null ? ` (L${s.start_line}${s.end_line != null ? `-L${s.end_line}` : ''})` : '';
      return `- \`${s.name}\` *${s.kind}*${lines} — ${s.role}`;
    })
    .join('\n');
  push('Key Symbols', symbols);
  push('Dependencies', list(explanation.dependencies));
  push('Related Files', list(explanation.related_files?.map((f) => `\`${f}\``)));

  if (explanation.call_graph_depth_expanded) {
    push(
      'Expanded Call Graph',
      [
        explanation.expanded_callers?.length ? `**Callers**\n${list(explanation.expanded_callers)}` : '',
        explanation.expanded_callees?.length ? `**Callees**\n${list(explanation.expanded_callees)}` : '',
      ]
        .filter(Boolean)
        .join('\n\n'),
    );
  }

  push('Issues and Solutions', list(explanation.code_issues_and_solutions));

  if (explanation.corrected_code && explanation.corrected_code.trim()) {
    const fence = fenceFor(explanation.corrected_code);
    push(
      'Corrected Code',
      `${fence}${languageFor(targetFilePath)}\n${explanation.corrected_code.replace(/\n+$/, '')}\n${fence}`,
    );
  }

  push('Assumptions and Limitations', list(explanation.assumptions_and_limitations));
  push('Missing Context', list(explanation.missing_context));
  push('Sources', (explanation.sources ?? []).map(formatSource).join('\n'));

  return `${sections.join('\n\n')}\n`;
}

/** Safe file name for the download: `explanation-src-app-main-py.md`. */
export function explanationExportFileName(targetFilePath?: string): string {
  const base = (targetFilePath ?? 'code')
    .replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(-80);
  return `explanation-${base || 'code'}.md`;
}

/** Triggers a browser download of the Markdown report. */
export function downloadExplanationMarkdown(
  explanation: CodeExplanation,
  targetFilePath?: string,
): void {
  const markdown = buildExplanationMarkdown(explanation, { targetFilePath });
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = explanationExportFileName(targetFilePath);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoke on the next tick so the download has started in every browser.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
