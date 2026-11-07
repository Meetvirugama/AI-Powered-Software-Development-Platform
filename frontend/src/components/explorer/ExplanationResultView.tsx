/**
 * ExplanationResultView — Renders the Intelligent Code Explainer Studio (task.md §7 & §9):
 *   1. Purpose & High-Level Summary
 *   2. Deep Technical Breakdown & Under-the-Hood Architecture
 *   3. Interactive Execution Walkthrough (Clickable steps with line highlighting)
 *   4. Code Output Explanation & Return Value Analysis (Formulas, Derivations, Examples)
 *   5. Code Quality, Flaws & Solved Solutions
 *   6. Corrected Production-Ready Code Refactoring (With Copy button)
 *   7. Explore Code Relationships: Tabbed Explorer [Call Graph | Data Flow | Related Files | Source Evidence]
 *   8. Key Symbols & Dependencies (conditionally shown, placeholders hidden)
 *   9. Ask About This Code (Interactive follow-up questions linked to Chat)
 */

import { useState, useMemo } from 'react';
import {
  BookOpen,
  Layers,
  ArrowRightLeft,
  AlertTriangle,
  HelpCircle,
  FileCode,
  CheckCircle2,
  Info,
  ExternalLink,
  ListOrdered,
  GitFork,
  Network,
  Cpu,
  Terminal,
  Wrench,
  Code2,
  Copy,
  Check,
  MessageSquare,
  ArrowRight,
  ArrowDown,
  Target,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { CodeExplanation, SourceReference, SymbolSummary } from '../../types/analysis';

export interface ExplanationResultViewProps {
  explanation: CodeExplanation;
  targetFilePath?: string;
  onSelectSourceReference?: (source: SourceReference) => void;
  activeSourceReference?: SourceReference | null;
  onSelectSymbol?: (symbol: SymbolSummary) => void;
  onAskFollowUp?: (question: string) => void;
  className?: string;
}

function escapeRegExp(string: string): string {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Extracts line range from a text string if present (e.g. "L13-L16", "L15", "lines 20 to 25").
 */
function extractLineRange(text: string): { start_line: number; end_line: number } | null {
  const rangeMatch = text.match(/\b(?:lines?|L)\s*(\d+)\s*(?:–|-|to)\s*L?(\d+)\b/i);
  if (rangeMatch) {
    const s = parseInt(rangeMatch[1], 10);
    const e = parseInt(rangeMatch[2], 10);
    return { start_line: Math.min(s, e), end_line: Math.max(s, e) };
  }
  const singleMatch = text.match(/\b(?:line|L)\s*(\d+)\b/i);
  if (singleMatch) {
    const s = parseInt(singleMatch[1], 10);
    return { start_line: s, end_line: s };
  }
  return null;
}

export function ExplanationResultView({
  explanation,
  targetFilePath,
  onSelectSourceReference,
  activeSourceReference,
  onSelectSymbol,
  onAskFollowUp,
  className,
}: ExplanationResultViewProps) {
  const [copied, setCopied] = useState(false);
  const [activeRelationshipTab, setActiveRelationshipTab] = useState<
    'call_graph' | 'data_flow' | 'related_files' | 'source_evidence'
  >('call_graph');

  const {
    purpose,
    logic_flow,
    key_symbols,
    inputs_and_outputs,
    dependencies,
    assumptions_and_limitations,
    sources,
    confidence,
    missing_context,
    execution_flow,
    related_files,
    detailed_explanation,
    code_output_explanation,
    code_issues_and_solutions,
    corrected_code,
  } = explanation;

  const hasMissingContext = missing_context && missing_context.length > 0;
  const isLowConfidence = confidence === 'low';
  const defaultFilePath = targetFilePath || sources?.[0]?.file_path || '';

  // Evidence-backed claims table items synthesized from sources, symbols, and logic
  const evidenceClaims = useMemo(() => {
    const list: Array<{
      claim: string;
      evidence: string;
      source: SourceReference;
    }> = [];

    // Map symbols with known lines as claims
    if (key_symbols) {
      key_symbols.forEach((sym) => {
        if (typeof sym.start_line === 'number' && typeof sym.end_line === 'number') {
          list.push({
            claim: `${sym.name}: ${sym.role}`,
            evidence: `${defaultFilePath ? defaultFilePath.split('/').pop() : 'source'}:L${sym.start_line}–L${sym.end_line}`,
            source: {
              file_path: defaultFilePath,
              start_line: sym.start_line,
              end_line: sym.end_line,
              symbol_name: sym.name,
            },
          });
        }
      });
    }

    // Map sources
    if (sources && list.length === 0) {
      sources.forEach((src) => {
        const fileName = src.file_path ? src.file_path.split('/').pop() : 'source';
        const lines =
          typeof src.start_line === 'number' && typeof src.end_line === 'number'
            ? `:L${src.start_line}–L${src.end_line}`
            : '';
        list.push({
          claim: src.symbol_name ? `Defined symbol: ${src.symbol_name}` : `Source code reference`,
          evidence: `${fileName}${lines}`,
          source: src,
        });
      });
    }

    return list;
  }, [key_symbols, sources, defaultFilePath]);

  // Handle clicking an execution step in the walkthrough
  const handleStepClick = (stepText: string) => {
    if (!onSelectSourceReference) return;

    // 1. Try explicit line range in step text
    const extracted = extractLineRange(stepText);
    if (extracted) {
      onSelectSourceReference({
        file_path: defaultFilePath,
        start_line: extracted.start_line,
        end_line: extracted.end_line,
      });
      return;
    }

    // 2. Try matching a symbol mentioned in the step
    if (key_symbols) {
      const matchedSym = key_symbols.find((s) => {
        if (!s.name || s.name.length < 3) return false;
        return new RegExp(`\\b${escapeRegExp(s.name)}\\b`, 'i').test(stepText);
      });
      if (
        matchedSym &&
        typeof matchedSym.start_line === 'number' &&
        typeof matchedSym.end_line === 'number'
      ) {
        onSelectSourceReference({
          file_path: defaultFilePath,
          start_line: matchedSym.start_line,
          end_line: matchedSym.end_line,
          symbol_name: matchedSym.name,
        });
        return;
      }
    }

    // 3. Fallback: navigate to primary target file
    if (defaultFilePath) {
      onSelectSourceReference({
        file_path: defaultFilePath,
      });
    }
  };

  // Tailored follow-up questions based on target context
  const suggestedQuestions = useMemo(() => {
    const fileName = defaultFilePath.split('/').pop() || 'this component';
    return [
      `Why is this implementation pattern or architecture used in ${fileName}?`,
      'What happens if input parameters are null, empty, or out of expected bounds?',
      'Trace runtime variable state and data transformations through this code',
      'Where is this code called or referenced across the repository?',
    ];
  }, [defaultFilePath]);

  return (
    <div className={cn('space-y-4 text-xs', className)}>
      {/* -------------------------------------------------------------- */}
      {/* Confidence Header & Grounding Status                           */}
      {/* -------------------------------------------------------------- */}
      <div className="flex items-center justify-between gap-2 p-2.5 rounded-lg border border-border/70 bg-background/60 shadow-xs">
        <span className="text-[11px] font-mono text-muted-foreground uppercase tracking-wider">
          Grounding Confidence:
        </span>
        <div
          className={cn(
            'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium border font-mono',
            confidence === 'high'
              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
              : confidence === 'medium'
              ? 'bg-blue-500/10 text-blue-400 border-blue-500/30'
              : 'bg-amber-500/10 text-amber-400 border-amber-500/30'
          )}
        >
          {confidence === 'high' ? (
            <CheckCircle2 className="h-3 w-3" />
          ) : confidence === 'medium' ? (
            <Info className="h-3 w-3" />
          ) : (
            <AlertTriangle className="h-3 w-3" />
          )}
          <span className="capitalize">{confidence} Confidence</span>
        </div>
      </div>

      {/* -------------------------------------------------------------- */}
      {/* Missing-Context & Uncertainty Warning Callout                  */}
      {/* -------------------------------------------------------------- */}
      {(hasMissingContext || isLowConfidence) && (
        <div
          role="alert"
          className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 space-y-2 animate-in fade-in duration-150"
        >
          <div className="flex items-center gap-2 text-amber-400 font-semibold text-xs">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>Missing Context & Uncertainty Warnings</span>
          </div>

          <p className="text-[11px] text-amber-300/90 leading-relaxed">
            The following aspects could not be fully confirmed from available repository context.
            Information is presented with bounds rather than assumed as fact:
          </p>

          {hasMissingContext && (
            <ul className="list-disc list-inside space-y-1 text-[11px] text-amber-200/90 pl-1 font-mono">
              {missing_context.map((msg, idx) => (
                <li key={idx} className="leading-relaxed">
                  {msg}
                </li>
              ))}
            </ul>
          )}

          {isLowConfidence && !hasMissingContext && (
            <p className="text-[11px] text-amber-200/90 italic font-mono">
              Confidence is low due to limited symbol resolution or unindexed external dependencies.
            </p>
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Section 1: Purpose & High-Level Summary                        */}
      {/* -------------------------------------------------------------- */}
      <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-1.5 shadow-xs">
        <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
          <BookOpen className="h-3.5 w-3.5" />
          <span>1. Purpose & Overview</span>
        </div>
        <p className="text-foreground leading-relaxed font-sans text-xs pt-0.5">
          {purpose || <span className="text-muted-foreground italic">No purpose summary provided.</span>}
        </p>
      </section>

      {/* -------------------------------------------------------------- */}
      {/* Deep Technical & Architecture Breakdown                        */}
      {/* -------------------------------------------------------------- */}
      {detailed_explanation && (
        <section className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-3.5 space-y-2 shadow-xs">
          <div className="flex items-center gap-1.5 text-indigo-400 font-semibold text-xs uppercase tracking-wide font-mono">
            <Cpu className="h-3.5 w-3.5" />
            <span>Deep Technical & Architecture Breakdown</span>
          </div>
          <div className="text-foreground leading-relaxed font-sans text-xs pt-0.5 whitespace-pre-line space-y-2">
            {detailed_explanation}
          </div>
        </section>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Section 2: Interactive Execution Walkthrough (task.md §7)       */}
      {/* -------------------------------------------------------------- */}
      {logic_flow && logic_flow.length > 0 && (
        <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-2 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
              <ListOrdered className="h-3.5 w-3.5" />
              <span>2. Execution Walkthrough</span>
            </div>
            <span className="text-[10px] font-mono text-muted-foreground">
              Click step to highlight code
            </span>
          </div>

          <ol className="space-y-2 pt-1">
            {logic_flow.map((step, idx) => {
              const range = extractLineRange(step);
              const isStepActive =
                Boolean(activeSourceReference) &&
                range !== null &&
                activeSourceReference?.start_line === range.start_line &&
                activeSourceReference?.end_line === range.end_line;

              return (
                <li
                  key={idx}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleStepClick(step)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleStepClick(step);
                    }
                  }}
                  className={cn(
                    'flex items-start gap-2.5 p-2 rounded-lg border transition-all cursor-pointer group',
                    isStepActive
                      ? 'bg-primary/15 border-primary shadow-xs'
                      : 'bg-background/40 border-border/50 hover:bg-muted/30 hover:border-border'
                  )}
                  title="Click to navigate and highlight corresponding lines in code viewer"
                >
                  <span
                    className={cn(
                      'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-mono font-bold mt-0.5 transition-colors',
                      isStepActive
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-primary/10 border border-primary/25 text-primary group-hover:bg-primary group-hover:text-primary-foreground'
                    )}
                  >
                    {idx + 1}
                  </span>

                  <div className="flex-1 min-w-0 pt-0.5">
                    <p className="text-foreground leading-relaxed text-xs">{step}</p>
                  </div>

                  {range ? (
                    <span className="shrink-0 inline-flex items-center gap-1 text-[10px] font-mono text-primary bg-primary/10 px-1.5 py-0.5 rounded border border-primary/20">
                      <Target className="h-2.5 w-2.5" />
                      <span>
                        L{range.start_line}
                        {range.end_line !== range.start_line ? `–${range.end_line}` : ''}
                      </span>
                    </span>
                  ) : (
                    <span className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-[10px] text-muted-foreground flex items-center gap-0.5">
                      <ExternalLink className="h-2.5 w-2.5" />
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Code Output Explanation & Return Values                        */}
      {/* -------------------------------------------------------------- */}
      {code_output_explanation && (
        <section className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3.5 space-y-2 shadow-xs">
          <div className="flex items-center gap-1.5 text-emerald-400 font-semibold text-xs uppercase tracking-wide font-mono">
            <Terminal className="h-3.5 w-3.5" />
            <span>Code Output Explanation & Return Values</span>
          </div>
          <div className="text-foreground leading-relaxed font-sans text-xs pt-0.5 whitespace-pre-line bg-background/50 p-3 rounded-lg border border-border/60">
            {code_output_explanation}
          </div>
        </section>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Code Issues & Solved Solutions                                 */}
      {/* -------------------------------------------------------------- */}
      {code_issues_and_solutions && code_issues_and_solutions.length > 0 && (
        <section className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3.5 space-y-2 shadow-xs">
          <div className="flex items-center gap-1.5 text-amber-400 font-semibold text-xs uppercase tracking-wide font-mono">
            <Wrench className="h-3.5 w-3.5" />
            <span>Code Quality, Flaws & Solved Solutions ({code_issues_and_solutions.length})</span>
          </div>
          <ul className="space-y-2 pt-1">
            {code_issues_and_solutions.map((item, idx) => (
              <li
                key={idx}
                className="flex items-start gap-2 bg-background/60 p-2.5 rounded-lg border border-border/60"
              >
                <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-mono font-bold mt-0.5">
                  !
                </span>
                <span className="text-foreground leading-relaxed text-xs">{item}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Corrected & Production-Ready Code                              */}
      {/* -------------------------------------------------------------- */}
      {corrected_code && (
        <section className="rounded-xl border border-primary/30 bg-primary/5 p-3.5 space-y-2 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide font-mono">
              <Code2 className="h-3.5 w-3.5" />
              <span>Corrected & Production-Ready Code Solution</span>
            </div>
            <button
              type="button"
              onClick={async () => {
                if (corrected_code) {
                  try {
                    await navigator.clipboard.writeText(corrected_code);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  } catch {
                    // Clipboard write failed
                  }
                }
              }}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-background/80 hover:bg-background border border-border/60 text-[11px] font-mono text-foreground transition-colors cursor-pointer"
            >
              {copied ? (
                <>
                  <Check className="h-3 w-3 text-emerald-400" />
                  <span className="text-emerald-400">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3 text-muted-foreground" />
                  <span>Copy Code</span>
                </>
              )}
            </button>
          </div>
          <pre className="p-3 rounded-lg bg-zinc-950 text-zinc-100 font-mono text-[11px] overflow-x-auto leading-relaxed border border-border/70 max-h-96">
            <code>{corrected_code}</code>
          </pre>
        </section>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Explore Code Relationships (Tabbed Explorer — task.md §9)      */}
      {/* -------------------------------------------------------------- */}
      <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-3 shadow-xs">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-1.5 text-foreground font-semibold text-xs uppercase tracking-wide font-mono">
            <Network className="h-3.5 w-3.5 text-primary" />
            <span>Explore Code Relationships</span>
          </div>

          {/* Relationship Tabs */}
          <div className="inline-flex items-center rounded-lg bg-muted/60 p-0.5 border border-border/70">
            <button
              type="button"
              onClick={() => setActiveRelationshipTab('call_graph')}
              className={cn(
                'px-2 py-1 text-[10px] font-mono rounded transition-all cursor-pointer',
                activeRelationshipTab === 'call_graph'
                  ? 'bg-background text-foreground shadow-xs font-semibold'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Call Graph
            </button>
            <button
              type="button"
              onClick={() => setActiveRelationshipTab('data_flow')}
              className={cn(
                'px-2 py-1 text-[10px] font-mono rounded transition-all cursor-pointer',
                activeRelationshipTab === 'data_flow'
                  ? 'bg-background text-foreground shadow-xs font-semibold'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Data Flow
            </button>
            <button
              type="button"
              onClick={() => setActiveRelationshipTab('related_files')}
              className={cn(
                'px-2 py-1 text-[10px] font-mono rounded transition-all cursor-pointer',
                activeRelationshipTab === 'related_files'
                  ? 'bg-background text-foreground shadow-xs font-semibold'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Related Files ({related_files?.length || 0})
            </button>
            <button
              type="button"
              onClick={() => setActiveRelationshipTab('source_evidence')}
              className={cn(
                'px-2 py-1 text-[10px] font-mono rounded transition-all cursor-pointer',
                activeRelationshipTab === 'source_evidence'
                  ? 'bg-background text-foreground shadow-xs font-semibold'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Evidence ({evidenceClaims.length || sources?.length || 0})
            </button>
          </div>
        </div>

        {/* Tab 1: Call Graph */}
        {activeRelationshipTab === 'call_graph' && (
          <div className="space-y-2 pt-1 animate-in fade-in duration-150">
            {execution_flow && execution_flow.length > 0 ? (
              <div className="space-y-1.5">
                <span className="text-[11px] text-muted-foreground font-mono">
                  Runtime Sequence & Cross-Component Calls:
                </span>
                <div className="space-y-2 pt-1">
                  {execution_flow.map((flowStep, idx) => (
                    <div key={idx} className="flex flex-col items-center">
                      <div className="w-full flex items-center gap-2 p-2 rounded-lg bg-muted/30 border border-border/60 font-mono text-[11px] text-foreground">
                        <span className="h-4 w-4 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-[10px] font-bold shrink-0">
                          {idx + 1}
                        </span>
                        <span className="truncate">{flowStep}</span>
                      </div>
                      {idx < execution_flow.length - 1 && (
                        <ArrowDown className="h-3 w-3 text-muted-foreground/60 my-0.5" />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ) : dependencies && dependencies.length > 0 ? (
              <div className="space-y-2">
                <span className="text-[11px] text-muted-foreground font-mono">
                  Connected Component Dependencies:
                </span>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {dependencies.map((dep, idx) => (
                    <span
                      key={idx}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-muted/40 border border-border/60 text-[11px] font-mono text-foreground"
                    >
                      <GitFork className="h-3 w-3 text-primary shrink-0" />
                      <span>{dep}</span>
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-muted-foreground text-xs italic">
                No external cross-file call sequence identified. Leaf function / standalone execution target.
              </p>
            )}
          </div>
        )}

        {/* Tab 2: Data Flow */}
        {activeRelationshipTab === 'data_flow' && (
          <div className="space-y-2.5 pt-1 animate-in fade-in duration-150">
            {inputs_and_outputs && inputs_and_outputs.trim().length > 0 && (
              <div className="space-y-1 p-2.5 rounded-lg bg-muted/20 border border-border/50">
                <div className="flex items-center gap-1.5 text-[11px] font-mono text-primary font-semibold">
                  <ArrowRightLeft className="h-3 w-3" />
                  <span>Input / Output Boundary</span>
                </div>
                <p className="text-foreground leading-relaxed text-xs">{inputs_and_outputs}</p>
              </div>
            )}
            {code_output_explanation && (
              <div className="space-y-1 p-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                <div className="flex items-center gap-1.5 text-[11px] font-mono text-emerald-400 font-semibold">
                  <Terminal className="h-3 w-3" />
                  <span>Return Value Derivation</span>
                </div>
                <p className="text-foreground leading-relaxed text-xs whitespace-pre-line">
                  {code_output_explanation}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Related Files */}
        {activeRelationshipTab === 'related_files' && (
          <div className="space-y-2 pt-1 animate-in fade-in duration-150">
            {related_files && related_files.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {related_files.map((rf, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => onSelectSourceReference?.({ file_path: rf })}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono bg-muted/40 hover:bg-muted/70 border border-border/60 hover:border-primary/40 text-foreground transition-all cursor-pointer"
                  >
                    <FileCode className="h-3 w-3 text-primary/70 shrink-0" />
                    <span className="truncate max-w-[240px]">{rf}</span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-muted-foreground text-xs italic">
                No additional connected files in this repository context scope.
              </p>
            )}
          </div>
        )}

        {/* Tab 4: Source Evidence & Claims Table (task.md §7) */}
        {activeRelationshipTab === 'source_evidence' && (
          <div className="space-y-2 pt-1 animate-in fade-in duration-150">
            {evidenceClaims.length > 0 ? (
              <div className="rounded-lg border border-border/60 overflow-hidden">
                <table className="w-full text-left text-[11px] font-mono">
                  <thead className="bg-muted/50 border-b border-border/60 text-muted-foreground">
                    <tr>
                      <th className="p-2 font-medium">Claim / Responsibility</th>
                      <th className="p-2 font-medium">Evidence Reference</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {evidenceClaims.map((item, idx) => (
                      <tr
                        key={idx}
                        role="button"
                        tabIndex={0}
                        onClick={() => onSelectSourceReference?.(item.source)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onSelectSourceReference?.(item.source);
                          }
                        }}
                        className="hover:bg-accent/50 cursor-pointer transition-colors"
                      >
                        <td className="p-2 text-foreground font-sans text-xs">{item.claim}</td>
                        <td className="p-2 text-primary whitespace-nowrap">
                          <span className="inline-flex items-center gap-1 bg-primary/10 px-1.5 py-0.5 rounded border border-primary/20">
                            <ExternalLink className="h-2.5 w-2.5" />
                            <span>{item.evidence}</span>
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : sources && sources.length > 0 ? (
              <div className="space-y-1.5">
                {sources.map((src, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => onSelectSourceReference?.(src)}
                    className="w-full text-left p-2 rounded-lg border text-xs font-mono flex items-center justify-between gap-2 bg-muted/20 border-border/50 text-foreground hover:bg-accent hover:border-border transition-all cursor-pointer"
                  >
                    <div className="flex items-center gap-1.5 min-w-0">
                      <ExternalLink className="h-3 w-3 text-primary shrink-0" />
                      <span className="truncate">{src.file_path}</span>
                    </div>
                    <span className="text-[10px] text-muted-foreground shrink-0 bg-background/70 px-1.5 py-0.5 rounded border border-border/40">
                      {src.start_line ? (src.end_line && src.end_line !== src.start_line ? `L${src.start_line}–${src.end_line}` : `L${src.start_line}`) : 'File'}
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-muted-foreground text-xs italic">
                No grounded source references attached.
              </p>
            )}
          </div>
        )}
      </section>

      {/* -------------------------------------------------------------- */}
      {/* Section 3: Key Symbols                                         */}
      {/* -------------------------------------------------------------- */}
      {key_symbols && key_symbols.length > 0 && (
        <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-2 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
              <Layers className="h-3.5 w-3.5" />
              <span>3. Key Symbols</span>
            </div>
            <span className="text-[10px] font-mono text-muted-foreground">
              {key_symbols.length} identified
            </span>
          </div>

          <div className="space-y-2 pt-1">
            {key_symbols.map((sym, idx) => {
              const hasLines = typeof sym.start_line === 'number' && typeof sym.end_line === 'number';
              return (
                <div
                  key={idx}
                  className="p-2.5 rounded-lg border border-border/60 bg-muted/20 space-y-1 hover:border-primary/40 transition-colors"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="text-[10px] font-mono uppercase px-1.5 py-0.2 rounded bg-primary/10 text-primary border border-primary/20 shrink-0 font-bold">
                        {sym.kind}
                      </span>
                      <span className="font-mono font-semibold text-foreground truncate">
                        {sym.name}
                      </span>
                    </div>

                    {hasLines && (
                      <span className="text-[10px] font-mono text-muted-foreground shrink-0 bg-background/80 px-1.5 py-0.5 rounded border border-border/50">
                        L{sym.start_line}–L{sym.end_line}
                      </span>
                    )}
                  </div>

                  <p className="text-[11px] text-muted-foreground leading-relaxed font-sans">
                    {sym.role}
                  </p>

                  {onSelectSymbol && (
                    <button
                      type="button"
                      onClick={() => onSelectSymbol(sym)}
                      className="inline-flex items-center gap-1 text-[10px] text-primary hover:underline font-mono pt-0.5 cursor-pointer"
                    >
                      <ExternalLink className="h-2.5 w-2.5" />
                      <span>Target symbol in viewer</span>
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Section 6: Assumptions and Limitations                         */}
      {/* -------------------------------------------------------------- */}
      {assumptions_and_limitations && assumptions_and_limitations.length > 0 && (
        <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-2 shadow-xs">
          <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
            <HelpCircle className="h-3.5 w-3.5" />
            <span>Assumptions and Limitations</span>
          </div>

          <ul className="list-disc list-inside space-y-1.5 pt-1 text-xs text-foreground font-sans">
            {assumptions_and_limitations.map((item, idx) => (
              <li key={idx} className="leading-relaxed">
                {item}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Ask About This Code (task.md §7 & §9)                          */}
      {/* -------------------------------------------------------------- */}
      <section className="rounded-xl border border-primary/25 bg-primary/5 p-3.5 space-y-2.5 shadow-xs">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wider font-mono">
            <MessageSquare className="h-3.5 w-3.5" />
            <span>Ask About This Code</span>
          </div>
          <span className="text-[10px] text-muted-foreground font-mono">Suggested follow-ups</span>
        </div>

        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Explore deeper architectural, operational, or edge-case questions reusing existing context:
        </p>

        <div className="space-y-1.5 pt-0.5">
          {suggestedQuestions.map((question, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => onAskFollowUp?.(question)}
              className="w-full text-left p-2 rounded-lg border border-border/50 bg-background/70 hover:bg-accent hover:border-primary/40 text-foreground text-xs flex items-center justify-between gap-2 transition-all cursor-pointer group"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-primary font-mono text-[10px] shrink-0 font-bold">?</span>
                <span className="truncate">{question}</span>
              </div>
              <span className="text-[10px] text-primary shrink-0 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-0.5 font-medium">
                <span>Ask in Chat</span>
                <ArrowRight className="h-2.5 w-2.5" />
              </span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
