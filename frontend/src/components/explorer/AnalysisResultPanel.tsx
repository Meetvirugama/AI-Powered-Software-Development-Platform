import {
  BookOpen,
  Bug,
  FlaskConical,
  FileCheck,
  RefreshCw,
  AlertCircle,
  X,
  Target,
  Info,
  CheckCircle2,
} from 'lucide-react';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { cn } from '../../lib/utils';
import type {
  AnalysisFeatureType,
  AnalysisTarget,
  AnalysisStatus,
  SourceReference,
} from '../../types/analysis';

export interface AnalysisResultPanelProps {
  feature: AnalysisFeatureType | null;
  target: AnalysisTarget;
  status: AnalysisStatus;
  error?: string | null;
  onRetry?: () => void;
  onRunAnalysis?: (feature: AnalysisFeatureType, target: AnalysisTarget) => void;
  onClose?: () => void;
  sources?: SourceReference[];
  className?: string;
  children?: React.ReactNode;
}

const FEATURE_META: Record<
  AnalysisFeatureType,
  {
    title: string;
    description: string;
    icon: typeof BookOpen;
    color: string;
    badgeBg: string;
    runLabel: string;
  }
> = {
  explain: {
    title: 'Code Explanation',
    description: 'Deconstruct purpose, logic flow, parameters, and dependencies using repository context.',
    icon: BookOpen,
    color: 'text-blue-400',
    badgeBg: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    runLabel: 'Run Explanation',
  },
  bugs: {
    title: 'Bug Detection',
    description: 'Inspect for logic defects, null safety, boundary errors, and edge cases using static rules & AI.',
    icon: Bug,
    color: 'text-amber-400',
    badgeBg: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    runLabel: 'Scan for Bugs',
  },
  tests: {
    title: 'Test Generation',
    description: 'Generate framework-aware unit tests and assertions following repository conventions.',
    icon: FlaskConical,
    color: 'text-emerald-400',
    badgeBg: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    runLabel: 'Generate Tests',
  },
  review: {
    title: 'AI Code Review',
    description: 'Standalone review evaluating correctness, security, performance, and maintainability.',
    icon: FileCheck,
    color: 'text-purple-400',
    badgeBg: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
    runLabel: 'Run Code Review',
  },
};

export function AnalysisResultPanel({
  feature,
  target,
  status,
  error,
  onRetry,
  onRunAnalysis,
  onClose,
  sources = [],
  className,
  children,
}: AnalysisResultPanelProps) {
  const currentMeta = feature ? FEATURE_META[feature] : null;

  const targetDescription =
    target.type === 'symbol' && target.symbol
      ? `Symbol "${target.symbol}" (L${target.start_line}–L${target.end_line})`
      : target.type === 'range' && target.start_line
      ? `Lines ${target.start_line}–${target.end_line} in ${target.path}`
      : `File ${target.path}`;

  return (
    <div
      className={cn(
        'flex flex-col min-h-0 h-full border-l border-border bg-card/40 backdrop-blur-xs overflow-hidden',
        className
      )}
    >
      {/* -------------------------------------------------------------- */}
      {/* Panel Header                                                   */}
      {/* -------------------------------------------------------------- */}
      <div className="shrink-0 h-11 px-3.5 border-b border-border/80 bg-muted/20 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {currentMeta ? (
            <>
              <currentMeta.icon className={cn('h-4 w-4 shrink-0', currentMeta.color)} />
              <h2 className="text-xs font-semibold text-foreground truncate">
                {currentMeta.title}
              </h2>
              <span className={cn('text-[10px] font-mono px-1.5 py-0.5 rounded border shrink-0', currentMeta.badgeBg)}>
                {target.type}
              </span>
            </>
          ) : (
            <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
              <Info className="h-4 w-4 text-primary" />
              <span>Developer Intelligence</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              aria-label="Close result panel"
              title="Close panel"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {/* Target Sub-header */}
      <div className="shrink-0 px-3 py-1.5 bg-muted/10 border-b border-border/50 flex items-center justify-between text-[11px] font-mono text-muted-foreground">
        <div className="flex items-center gap-1.5 truncate">
          <Target className="h-3 w-3 text-primary shrink-0" />
          <span className="truncate" title={targetDescription}>
            Target: <span className="text-foreground">{targetDescription}</span>
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0 text-[10px]">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          <span className="capitalize">{status.toLowerCase()}</span>
        </div>
      </div>

      {/* -------------------------------------------------------------- */}
      {/* Panel Body: State Handler                                       */}
      {/* -------------------------------------------------------------- */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
        {/* State 1: No feature selected */}
        {!feature && (
          <div className="h-full flex flex-col items-center justify-center text-center p-6 space-y-4">
            <div className="h-12 w-12 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
              <BookOpen className="h-6 w-6" />
            </div>
            <div className="max-w-xs space-y-1">
              <h3 className="text-sm font-semibold text-foreground">Select an Intelligence Action</h3>
              <p className="text-xs text-muted-foreground">
                Choose Explain Code, Find Bugs, Generate Tests, or AI Code Review to inspect {targetDescription}.
              </p>
            </div>
          </div>
        )}

        {/* State 2: IDLE (Feature selected, ready to run) */}
        {feature && status === 'IDLE' && currentMeta && (
          <div className="space-y-4 py-2">
            <div className="rounded-xl border border-border/80 bg-background/60 p-4 space-y-3">
              <div className="flex items-start gap-3">
                <div className={cn('p-2 rounded-lg border shrink-0', currentMeta.badgeBg)}>
                  <currentMeta.icon className={cn('h-5 w-5', currentMeta.color)} />
                </div>
                <div className="space-y-1">
                  <h3 className="text-sm font-semibold text-foreground">{currentMeta.title}</h3>
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {currentMeta.description}
                  </p>
                </div>
              </div>

              <div className="pt-2 border-t border-border/50 text-xs space-y-1 font-mono">
                <div className="flex justify-between text-muted-foreground text-[11px]">
                  <span>Scope:</span>
                  <span className="text-foreground">{target.type}</span>
                </div>
                <div className="flex justify-between text-muted-foreground text-[11px]">
                  <span>File:</span>
                  <span className="text-foreground truncate max-w-[200px]">{target.path}</span>
                </div>
                {target.symbol && (
                  <div className="flex justify-between text-muted-foreground text-[11px]">
                    <span>Symbol:</span>
                    <span className="text-primary">{target.symbol}</span>
                  </div>
                )}
                {target.start_line && (
                  <div className="flex justify-between text-muted-foreground text-[11px]">
                    <span>Lines:</span>
                    <span className="text-foreground">
                      L{target.start_line}–{target.end_line}
                    </span>
                  </div>
                )}
              </div>

              <div className="pt-2">
                <button
                  type="button"
                  onClick={() => onRunAnalysis?.(feature, target)}
                  className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 transition-all shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <currentMeta.icon className="h-4 w-4" />
                  <span>{currentMeta.runLabel}</span>
                </button>
              </div>
            </div>

            <div className="rounded-lg bg-muted/20 border border-border/60 p-3 flex items-start gap-2.5 text-xs text-muted-foreground">
              <Info className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <p className="text-[11px] leading-relaxed">
                Analysis requests are scoped strictly to authorized repository context. Week 2 Day 1
                establishes the explorer foundation and result UX ahead of Day 2 AI service deployment.
              </p>
            </div>
          </div>
        )}

        {/* State 3: RUNNING / PENDING */}
        {(status === 'RUNNING' || status === 'PENDING') && (
          <div className="h-[240px] flex flex-col items-center justify-center text-center p-6 space-y-3">
            <LoadingSpinner size="md" label={`Running ${currentMeta?.title ?? 'analysis'}…`} />
            <div className="space-y-1">
              <p className="text-xs font-medium text-foreground">
                Analyzing {targetDescription}
              </p>
              <p className="text-[11px] text-muted-foreground font-mono">
                Extracting symbols, AST context, and static evidence…
              </p>
            </div>
          </div>
        )}

        {/* State 4: FAILED (with working retry callback) */}
        {status === 'FAILED' && (
          <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 space-y-3 animate-in fade-in duration-200">
            <div className="flex items-start gap-2.5">
              <AlertCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
              <div className="space-y-1 min-w-0 flex-1">
                <h4 className="text-xs font-semibold text-destructive">
                  Analysis Failed
                </h4>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {error ||
                    'Unable to complete analysis. The backend service endpoint may still be in development or the provider call timed out.'}
                </p>
              </div>
            </div>

            {onRetry && (
              <div className="flex justify-end pt-2 border-t border-destructive/20">
                <button
                  type="button"
                  onClick={onRetry}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-background text-xs font-medium text-foreground hover:bg-accent transition-colors shadow-xs"
                >
                  <RefreshCw className="h-3.5 w-3.5 text-primary" />
                  <span>Retry Analysis</span>
                </button>
              </div>
            )}
          </div>
        )}

        {/* State 5: COMPLETED (Content slot for structured findings/explanation) */}
        {status === 'COMPLETED' && (
          <div className="space-y-4">
            {children ? (
              children
            ) : (
              <div className="rounded-xl border border-border/80 bg-background/50 p-4 space-y-2 text-center">
                <CheckCircle2 className="h-6 w-6 text-emerald-400 mx-auto" />
                <h4 className="text-xs font-semibold text-foreground">Analysis Completed</h4>
                <p className="text-xs text-muted-foreground">
                  Analysis completed for {targetDescription}.
                </p>
              </div>
            )}

            {/* Evidence & Sources Section */}
            {sources && sources.length > 0 && (
              <div className="pt-3 border-t border-border/60 space-y-2">
                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider font-mono">
                  Cited Evidence ({sources.length}):
                </h4>
                <div className="space-y-1.5">
                  {sources.map((src, idx) => (
                    <div
                      key={idx}
                      className="p-2 rounded-lg border border-border/50 bg-muted/20 text-xs font-mono flex items-center justify-between gap-2"
                    >
                      <span className="text-foreground truncate" title={src.file_path}>
                        {src.file_path}
                      </span>
                      <span className="text-muted-foreground text-[10px] shrink-0">
                        L{src.start_line}–{src.end_line}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
