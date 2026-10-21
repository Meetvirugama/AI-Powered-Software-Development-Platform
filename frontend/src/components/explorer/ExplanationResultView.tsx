/**
 * ExplanationResultView — Renders the 6 required Week 2 Day 2 explanation sections:
 *   1. Purpose
 *   2. Logic flow
 *   3. Key symbols
 *   4. Inputs and outputs
 *   5. Dependencies
 *   6. Assumptions and limitations
 * Plus Missing-Context warnings, Confidence badge, and navigable Source References.
 */

import {
  BookOpen,
  Layers,
  ArrowRightLeft,
  Box,
  AlertTriangle,
  HelpCircle,
  FileCode,
  CheckCircle2,
  Info,
  ExternalLink,
  ListOrdered,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { CodeExplanation, SourceReference, SymbolSummary } from '../../types/analysis';

export interface ExplanationResultViewProps {
  explanation: CodeExplanation;
  onSelectSourceReference?: (source: SourceReference) => void;
  activeSourceReference?: SourceReference | null;
  onSelectSymbol?: (symbol: SymbolSummary) => void;
  className?: string;
}

export function ExplanationResultView({
  explanation,
  onSelectSourceReference,
  activeSourceReference,
  onSelectSymbol,
  className,
}: ExplanationResultViewProps) {
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
  } = explanation;

  const hasMissingContext = missing_context && missing_context.length > 0;
  const isLowConfidence = confidence === 'low';

  return (
    <div className={cn('space-y-4 text-xs', className)}>
      {/* -------------------------------------------------------------- */}
      {/* Confidence Header & Status Strip                               */}
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
      {/* Section 1: Purpose                                             */}
      {/* -------------------------------------------------------------- */}
      <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-1.5 shadow-xs">
        <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
          <BookOpen className="h-3.5 w-3.5" />
          <span>1. Purpose</span>
        </div>
        <p className="text-foreground leading-relaxed font-sans text-xs pt-0.5">
          {purpose || <span className="text-muted-foreground italic">No purpose summary provided.</span>}
        </p>
      </section>

      {/* -------------------------------------------------------------- */}
      {/* Section 2: Logic Flow                                          */}
      {/* -------------------------------------------------------------- */}
      <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-2 shadow-xs">
        <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
          <ListOrdered className="h-3.5 w-3.5" />
          <span>2. Logic Flow</span>
        </div>

        {logic_flow && logic_flow.length > 0 ? (
          <ol className="space-y-2 pt-1">
            {logic_flow.map((step, idx) => (
              <li key={idx} className="flex items-start gap-2.5">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 border border-primary/25 text-[10px] font-mono font-bold text-primary">
                  {idx + 1}
                </span>
                <span className="text-foreground leading-relaxed pt-0.5 flex-1">
                  {step}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-muted-foreground italic text-xs">
            No sequential logic flow steps specified.
          </p>
        )}
      </section>

      {/* -------------------------------------------------------------- */}
      {/* Section 3: Key Symbols                                         */}
      {/* -------------------------------------------------------------- */}
      <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-2 shadow-xs">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
            <Layers className="h-3.5 w-3.5" />
            <span>3. Key Symbols</span>
          </div>
          <span className="text-[10px] font-mono text-muted-foreground">
            {key_symbols ? key_symbols.length : 0} identified
          </span>
        </div>

        {key_symbols && key_symbols.length > 0 ? (
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
                      className="inline-flex items-center gap-1 text-[10px] text-primary hover:underline font-mono pt-0.5"
                    >
                      <ExternalLink className="h-2.5 w-2.5" />
                      <span>Target symbol in viewer</span>
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-muted-foreground italic text-xs">
            No specific key symbols extracted.
          </p>
        )}
      </section>

      {/* -------------------------------------------------------------- */}
      {/* Section 4: Inputs and Outputs                                  */}
      {/* -------------------------------------------------------------- */}
      <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-1.5 shadow-xs">
        <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
          <ArrowRightLeft className="h-3.5 w-3.5" />
          <span>4. Inputs and Outputs</span>
        </div>
        <p className="text-foreground leading-relaxed font-sans text-xs pt-0.5">
          {inputs_and_outputs || (
            <span className="text-muted-foreground italic">
              No input/output parameters documented.
            </span>
          )}
        </p>
      </section>

      {/* -------------------------------------------------------------- */}
      {/* Section 5: Dependencies                                        */}
      {/* -------------------------------------------------------------- */}
      <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-2 shadow-xs">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
            <Box className="h-3.5 w-3.5" />
            <span>5. Dependencies</span>
          </div>
          <span className="text-[10px] font-mono text-muted-foreground">
            {dependencies ? dependencies.length : 0} items
          </span>
        </div>

        {dependencies && dependencies.length > 0 ? (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {dependencies.map((dep, idx) => (
              <span
                key={idx}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-muted/40 border border-border/60 text-[11px] font-mono text-foreground"
              >
                <span>{dep}</span>
              </span>
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground italic text-xs">
            No external module imports or dependencies identified.
          </p>
        )}
      </section>

      {/* -------------------------------------------------------------- */}
      {/* Section 6: Assumptions and Limitations                         */}
      {/* -------------------------------------------------------------- */}
      <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-2 shadow-xs">
        <div className="flex items-center gap-1.5 text-primary font-semibold text-xs uppercase tracking-wide">
          <HelpCircle className="h-3.5 w-3.5" />
          <span>6. Assumptions and Limitations</span>
        </div>

        {assumptions_and_limitations && assumptions_and_limitations.length > 0 ? (
          <ul className="list-disc list-inside space-y-1.5 pt-1 text-xs text-foreground font-sans">
            {assumptions_and_limitations.map((item, idx) => (
              <li key={idx} className="leading-relaxed">
                {item}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground italic text-xs">
            No specific runtime assumptions or context limitations declared.
          </p>
        )}
      </section>

      {/* -------------------------------------------------------------- */}
      {/* Navigable Source References                                    */}
      {/* -------------------------------------------------------------- */}
      {sources && sources.length > 0 && (
        <section className="rounded-xl border border-border/80 bg-background/50 p-3.5 space-y-2 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-muted-foreground font-semibold text-xs uppercase tracking-wider font-mono">
              <FileCode className="h-3.5 w-3.5 text-primary" />
              <span>Cited Source Evidence ({sources.length})</span>
            </div>
            <span className="text-[10px] text-muted-foreground">Click to navigate</span>
          </div>

          <div className="space-y-1.5 pt-1">
            {sources.map((src, idx) => {
              const isSelected =
                activeSourceReference?.file_path === src.file_path &&
                activeSourceReference?.start_line === src.start_line &&
                activeSourceReference?.end_line === src.end_line;

              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectSourceReference?.(src)}
                  className={cn(
                    'w-full text-left p-2 rounded-lg border text-xs font-mono flex items-center justify-between gap-2 transition-all cursor-pointer',
                    isSelected
                      ? 'bg-primary/20 border-primary text-primary font-semibold shadow-xs'
                      : 'bg-muted/20 border-border/50 text-foreground hover:bg-accent hover:border-border'
                  )}
                  title={`Navigate to ${src.file_path}:L${src.start_line}-L${src.end_line}`}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <ExternalLink className="h-3 w-3 text-primary shrink-0" />
                    <span className="truncate">{src.file_path}</span>
                    {src.symbol_name && (
                      <span className="text-[10px] text-muted-foreground shrink-0">
                        ({src.symbol_name})
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground shrink-0 bg-background/70 px-1.5 py-0.5 rounded border border-border/40">
                    L{src.start_line}–{src.end_line}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
