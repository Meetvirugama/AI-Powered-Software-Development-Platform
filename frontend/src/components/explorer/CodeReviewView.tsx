import { useState, useMemo, useEffect } from 'react';
import {
  FileCheck,
  ShieldAlert,
  AlertTriangle,
  AlertOctagon,
  Info,
  CheckCircle2,
  Filter,
  Search,
  Code2,
  Sparkles,
  Cpu,
  ChevronDown,
  ChevronUp,
  X,
  Copy,
  Check,
  GitCommit,
  GitPullRequest,
  FileText,
  FileDiff,
  HelpCircle,
  ExternalLink,
  History,
  Clock,
  RotateCcw,
  Loader2,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { getCodeReviewHistory, reopenCodeReview } from '../../services/analysis';
import type {
  ReviewReportResponse,
  ReviewFinding,
  ReviewCategory,
  FindingSeverity,
  FindingSourceType,
  SourceReference,
  ReviewTarget,
  ReviewTargetType,
  AnalysisRunSummary,
} from '../../types/analysis';

export interface CodeReviewViewProps {
  result: ReviewReportResponse;
  onSelectSourceReference?: (source: SourceReference) => void;
  activeSourceReference?: SourceReference | null;
  onRunReview?: (target: ReviewTarget) => void;
  isRunning?: boolean;
  activeFileTreePaths?: string[];
  repositoryId?: string;
  onReopenReview?: (result: ReviewReportResponse) => void;
  className?: string;
}

const SEVERITY_CONFIG: Record<
  FindingSeverity,
  {
    label: string;
    icon: typeof AlertTriangle;
    badgeClass: string;
    pillClass: string;
    textClass: string;
    borderClass: string;
  }
> = {
  CRITICAL: {
    label: 'Critical',
    icon: AlertOctagon,
    badgeClass: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
    pillClass:
      'hover:bg-rose-500/20 data-[active=true]:bg-rose-500/25 data-[active=true]:text-rose-300 data-[active=true]:border-rose-500/50',
    textClass: 'text-rose-400',
    borderClass: 'border-l-rose-500',
  },
  HIGH: {
    label: 'High',
    icon: ShieldAlert,
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    pillClass:
      'hover:bg-amber-500/20 data-[active=true]:bg-amber-500/25 data-[active=true]:text-amber-300 data-[active=true]:border-amber-500/50',
    textClass: 'text-amber-400',
    borderClass: 'border-l-amber-500',
  },
  MEDIUM: {
    label: 'Medium',
    icon: AlertTriangle,
    badgeClass: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
    pillClass:
      'hover:bg-yellow-500/20 data-[active=true]:bg-yellow-500/25 data-[active=true]:text-yellow-300 data-[active=true]:border-yellow-500/50',
    textClass: 'text-yellow-400',
    borderClass: 'border-l-yellow-500',
  },
  LOW: {
    label: 'Low',
    icon: Info,
    badgeClass: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    pillClass:
      'hover:bg-blue-500/20 data-[active=true]:bg-blue-500/25 data-[active=true]:text-blue-300 data-[active=true]:border-blue-500/50',
    textClass: 'text-blue-400',
    borderClass: 'border-l-blue-500',
  },
  INFO: {
    label: 'Info',
    icon: Info,
    badgeClass: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
    pillClass:
      'hover:bg-slate-500/20 data-[active=true]:bg-slate-500/25 data-[active=true]:text-slate-300 data-[active=true]:border-slate-500/50',
    textClass: 'text-slate-400',
    borderClass: 'border-l-slate-400',
  },
};

const RISK_LEVEL_CONFIG: Record<
  string,
  { label: string; badgeClass: string; textClass: string; bgClass: string }
> = {
  CRITICAL: {
    label: 'Critical Risk',
    badgeClass: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
    textClass: 'text-rose-400',
    bgClass: 'bg-rose-500/10 border-rose-500/20',
  },
  HIGH: {
    label: 'High Risk',
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    textClass: 'text-amber-400',
    bgClass: 'bg-amber-500/10 border-amber-500/20',
  },
  MEDIUM: {
    label: 'Moderate Risk',
    badgeClass: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
    textClass: 'text-yellow-400',
    bgClass: 'bg-yellow-500/10 border-yellow-500/20',
  },
  LOW: {
    label: 'Low Risk',
    badgeClass: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    textClass: 'text-blue-400',
    bgClass: 'bg-blue-500/10 border-blue-500/20',
  },
  NONE: {
    label: 'Clean Review (Zero Defects)',
    badgeClass: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    textClass: 'text-emerald-400',
    bgClass: 'bg-emerald-500/10 border-emerald-500/20',
  },
};

const SOURCE_TYPE_CONFIG: Record<
  FindingSourceType,
  { label: string; icon: typeof Cpu; className: string; description: string }
> = {
  STATIC: {
    label: 'Static Check',
    icon: Cpu,
    className: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
    description: 'Deterministic static rule or secret scanner',
  },
  AI: {
    label: 'AI Reasoning',
    icon: Sparkles,
    className: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
    description: 'AI-assisted code review engine',
  },
  COMBINED: {
    label: 'Static + AI',
    icon: ShieldAlert,
    className: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/40 font-semibold',
    description: 'Corroborated by both static rules and AI validation',
  },
};

const CATEGORY_NAMES: Record<ReviewCategory, string> = {
  correctness: 'Correctness',
  security: 'Security',
  performance: 'Performance',
  reliability: 'Reliability',
  maintainability: 'Maintainability',
};

const CATEGORY_COLORS: Record<ReviewCategory, string> = {
  correctness: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
  security: 'text-rose-400 bg-rose-500/10 border-rose-500/30',
  performance: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  reliability: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  maintainability: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
};

export function CodeReviewView({
  result,
  onSelectSourceReference,
  activeSourceReference,
  onRunReview: _onRunReview,
  isRunning: _isRunning = false,
  activeFileTreePaths = [],
  repositoryId,
  onReopenReview,
  className,
}: CodeReviewViewProps) {
  const { report, target } = result;
  const findings = useMemo(() => report.findings || [], [report.findings]);

  const [selectedSeverity, setSelectedSeverity] = useState<FindingSeverity | 'ALL'>('ALL');
  const [selectedCategory, setSelectedCategory] = useState<ReviewCategory | 'ALL'>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [navWarning, setNavWarning] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const [expandedFindings, setExpandedFindings] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    findings.slice(0, 4).forEach((f) => {
      initial[f.id] = true;
    });
    return initial;
  });

  const [showMissingContext, setShowMissingContext] = useState(false);

  // Severity counts
  const severityCounts = useMemo(() => {
    const counts: Record<FindingSeverity, number> = {
      CRITICAL: 0,
      HIGH: 0,
      MEDIUM: 0,
      LOW: 0,
      INFO: 0,
    };
    findings.forEach((f) => {
      if (counts[f.severity] !== undefined) {
        counts[f.severity]++;
      }
    });
    return counts;
  }, [findings]);

  // Filtered findings
  const filteredFindings = useMemo(() => {
    return findings.filter((f) => {
      if (selectedSeverity !== 'ALL' && f.severity !== selectedSeverity) {
        return false;
      }
      if (selectedCategory !== 'ALL' && f.category !== selectedCategory) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const inTitle = f.title?.toLowerCase().includes(q) ?? false;
        const inDesc = f.description?.toLowerCase().includes(q) ?? false;
        const inEvidence = f.evidence?.toLowerCase().includes(q) ?? false;
        const inPath = f.source_reference?.file_path?.toLowerCase().includes(q) ?? false;
        const inFix = f.suggested_fix?.toLowerCase().includes(q) ?? false;
        if (!inTitle && !inDesc && !inEvidence && !inPath && !inFix) {
          return false;
        }
      }
      return true;
    });
  }, [findings, selectedSeverity, selectedCategory, searchQuery]);

  function toggleFinding(id: string) {
    setExpandedFindings((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  }

  function expandAll() {
    const all: Record<string, boolean> = {};
    filteredFindings.forEach((f) => {
      all[f.id] = true;
    });
    setExpandedFindings(all);
  }

  function collapseAll() {
    setExpandedFindings({});
  }

  async function handleCopyFix(findingId: string, fixText: string) {
    if (!navigator?.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(fixText);
      setCopiedId(findingId);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      // Ignore clipboard write failure honestly without setting copiedId
    }
  }

  function handleSourceClick(source: SourceReference) {
    setNavWarning(null);
    if (!source.file_path) return;

    // Check if the file is in the currently loaded repository tree
    if (activeFileTreePaths.length > 0) {
      const normalize = (p: string) => p.replace(/\\/g, '/').replace(/^\.?\//, '').toLowerCase();
      const targetNorm = normalize(source.file_path);
      const isPresent = activeFileTreePaths.some((p) => normalize(p) === targetNorm);

      if (!isPresent) {
        setNavWarning(
          `Source file "${source.file_path}" is not present in the current repository file tree (it may belong to a separate commit, PR diff, or was deleted in the head revision).`
        );
      }
    }

    onSelectSourceReference?.(source);
  }

  const riskMeta = RISK_LEVEL_CONFIG[report.risk_level] || RISK_LEVEL_CONFIG.LOW;

  return (
    <div className={cn('space-y-4 text-foreground', className)}>
      {/* ------------------------------------------------------------------ */}
      {/* 1. Target Badge Banner                                              */}
      {/* ------------------------------------------------------------------ */}
      <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-2">
        <div className="flex items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-1.5 font-mono">
            {target.type === 'file' && <FileText className="h-3.5 w-3.5 text-primary" />}
            {target.type === 'commit' && <GitCommit className="h-3.5 w-3.5 text-primary" />}
            {target.type === 'pr' && <GitPullRequest className="h-3.5 w-3.5 text-primary" />}
            {target.type === 'diff' && <FileDiff className="h-3.5 w-3.5 text-primary" />}
            <span className="text-muted-foreground uppercase text-[10px] tracking-wider font-semibold">
              Review Target:
            </span>
            <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 text-[10px] uppercase font-bold">
              {target.type}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <div className="text-[10px] font-mono text-muted-foreground">
              Run ID: <span className="text-foreground">{result.run_id.slice(0, 8)}…</span>
            </div>
            {repositoryId && (
              <button
                type="button"
                onClick={() => setShowHistory(!showHistory)}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono border border-border/70 bg-card hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                title="View past code review runs"
              >
                <History className="h-3 w-3 text-primary" />
                <span>History</span>
              </button>
            )}
          </div>
        </div>

        <div className="text-xs font-mono bg-muted/20 rounded-lg p-2 border border-border/40 truncate text-foreground">
          {target.type === 'file' && (
            <span>Path: <strong className="text-primary">{target.path}</strong></span>
          )}
          {target.type === 'commit' && (
            <span>Commit SHA: <strong className="text-primary">{target.commit_sha}</strong></span>
          )}
          {target.type === 'pr' && (
            <span>Pull Request: <strong className="text-primary">#{target.pr_number}</strong></span>
          )}
          {target.type === 'diff' && (
            <span>Unified Diff ({target.diff?.length || 0} characters)</span>
          )}
        </div>
      </div>

      {/* History Drawer Modal / Popover */}
      {showHistory && (
        <ReviewHistoryDrawer
          isOpen={showHistory}
          onClose={() => setShowHistory(false)}
          repositoryId={repositoryId}
          onReopenReview={onReopenReview}
        />
      )}

      {/* ------------------------------------------------------------------ */}
      {/* 2. Review Summary & Overall Risk Header                            */}
      {/* ------------------------------------------------------------------ */}
      <div className={cn('rounded-xl border p-4 space-y-3', riskMeta.bgClass)}>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="space-y-1 min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <FileCheck className="h-4 w-4 text-primary shrink-0" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                Standalone AI Code Review
              </h3>
            </div>
            <p className="text-xs text-foreground leading-relaxed font-sans">
              {report.summary}
            </p>
          </div>

          <span
            className={cn(
              'px-2.5 py-1 rounded-full border text-xs font-semibold shrink-0 shadow-xs flex items-center gap-1.5',
              riskMeta.badgeClass
            )}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            <span>{riskMeta.label}</span>
          </span>
        </div>

        {/* Category count breakdown */}
        <div className="pt-2 border-t border-border/40 flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] text-muted-foreground uppercase font-mono mr-1">
            Category Breakdown:
          </span>
          {(['correctness', 'security', 'performance', 'reliability', 'maintainability'] as ReviewCategory[]).map(
            (cat) => {
              const count = report.category_counts[cat] ?? 0;
              const isActive = selectedCategory === cat;
              return (
                <button
                  key={cat}
                  type="button"
                  onClick={() => setSelectedCategory(isActive ? 'ALL' : cat)}
                  className={cn(
                    'inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[11px] font-mono transition-all',
                    isActive
                      ? 'bg-primary/25 border-primary text-primary font-bold shadow-xs'
                      : CATEGORY_COLORS[cat]
                  )}
                  title={`Filter by ${CATEGORY_NAMES[cat]}`}
                >
                  <span>{CATEGORY_NAMES[cat]}:</span>
                  <span className="font-bold">{count}</span>
                </button>
              );
            }
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* 3. Navigation Warning Banner (if file not in local tree)           */}
      {/* ------------------------------------------------------------------ */}
      {navWarning && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs flex items-start justify-between gap-2 animate-in fade-in">
          <div className="flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
            <p className="text-amber-300 text-[11px] leading-relaxed">{navWarning}</p>
          </div>
          <button
            type="button"
            onClick={() => setNavWarning(null)}
            className="text-amber-400 hover:text-foreground shrink-0 p-0.5"
            aria-label="Dismiss warning"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* 4. Clean Review vs Incomplete / Inconclusive Review State           */}
      {/* ------------------------------------------------------------------ */}
      {findings.length === 0 ? (
        report.risk_level === 'NONE' ? (
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-6 text-center space-y-3">
            <div className="h-12 w-12 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400 mx-auto">
              <CheckCircle2 className="h-6 w-6" />
            </div>
            <div className="space-y-1 max-w-sm mx-auto">
              <h4 className="text-sm font-bold text-foreground">Clean Code Review</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                No defects, regressions, or security vulnerabilities were detected across Correctness,
                Security, Performance, Reliability, and Maintainability.
              </p>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-6 text-center space-y-3">
            <div className="h-12 w-12 rounded-full bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-400 mx-auto">
              <AlertTriangle className="h-6 w-6" />
            </div>
            <div className="space-y-1 max-w-sm mx-auto">
              <h4 className="text-sm font-bold text-foreground">Incomplete or Inconclusive Review</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                The review completed with risk level <strong>{report.risk_level}</strong>, but no actionable findings could be confirmed from available context.
              </p>
            </div>
          </div>
        )
      ) : (
        <>
          {/* -------------------------------------------------------------- */}
          {/* 5. Filter Controls & Search Bar                                */}
          {/* -------------------------------------------------------------- */}
          <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-2.5">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                <Filter className="h-3.5 w-3.5 text-primary" />
                <span>Filters & Search</span>
                <span className="text-[10px] font-mono text-muted-foreground">
                  ({filteredFindings.length} of {findings.length})
                </span>
              </div>

              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={expandAll}
                  className="px-2 py-0.5 rounded text-[10px] font-mono border border-border/60 bg-muted/20 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                >
                  Expand All
                </button>
                <button
                  type="button"
                  onClick={collapseAll}
                  className="px-2 py-0.5 rounded text-[10px] font-mono border border-border/60 bg-muted/20 text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                >
                  Collapse All
                </button>
              </div>
            </div>

            {/* Severity Pill Selector */}
            <div className="flex items-center gap-1 flex-wrap text-xs">
              <span className="text-[10px] text-muted-foreground uppercase font-mono mr-1">
                Severity:
              </span>
              <button
                type="button"
                data-active={selectedSeverity === 'ALL'}
                onClick={() => setSelectedSeverity('ALL')}
                className="px-2 py-0.5 rounded-md border border-border/70 text-[11px] font-mono text-muted-foreground hover:text-foreground data-[active=true]:bg-primary/20 data-[active=true]:border-primary data-[active=true]:text-primary data-[active=true]:font-bold transition-all"
              >
                All ({findings.length})
              </button>
              {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] as FindingSeverity[]).map((sev) => {
                const count = severityCounts[sev];
                if (count === 0 && selectedSeverity !== sev) return null;
                const meta = SEVERITY_CONFIG[sev];
                return (
                  <button
                    key={sev}
                    type="button"
                    data-active={selectedSeverity === sev}
                    onClick={() => setSelectedSeverity(selectedSeverity === sev ? 'ALL' : sev)}
                    className={cn(
                      'px-2 py-0.5 rounded-md border text-[11px] font-mono transition-all',
                      meta.badgeClass,
                      meta.pillClass
                    )}
                  >
                    {meta.label} ({count})
                  </button>
                );
              })}
            </div>

            {/* Search Input */}
            <div className="relative">
              <Search className="h-3.5 w-3.5 text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search findings by title, evidence, remediation, or path…"
                className="w-full pl-8 pr-8 py-1.5 rounded-lg border border-border bg-card text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring font-sans"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>

          {/* -------------------------------------------------------------- */}
          {/* 6. Filtered Findings List                                      */}
          {/* -------------------------------------------------------------- */}
          {filteredFindings.length === 0 ? (
            <div className="rounded-xl border border-border/80 bg-background/50 p-6 text-center space-y-2">
              <Filter className="h-6 w-6 text-muted-foreground opacity-50 mx-auto" />
              <h4 className="text-xs font-semibold text-foreground">No Matching Findings</h4>
              <p className="text-xs text-muted-foreground">
                No findings match the current category, severity, or search query.
              </p>
              <button
                type="button"
                onClick={() => {
                  setSelectedSeverity('ALL');
                  setSelectedCategory('ALL');
                  setSearchQuery('');
                }}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 transition-colors mt-1"
              >
                Reset Filters
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {filteredFindings.map((finding) => {
                const isExpanded = expandedFindings[finding.id] ?? false;
                const sevMeta = SEVERITY_CONFIG[finding.severity] || SEVERITY_CONFIG.MEDIUM;
                const sourceMeta =
                  SOURCE_TYPE_CONFIG[finding.source_type] || SOURCE_TYPE_CONFIG.AI;
                const isCited =
                  activeSourceReference &&
                  activeSourceReference.file_path === finding.source_reference?.file_path &&
                  activeSourceReference.start_line === finding.source_reference?.start_line;

                const hasLineRange =
                  finding.source_reference &&
                  typeof finding.source_reference.start_line === 'number';

                return (
                  <div
                    key={finding.id}
                    className={cn(
                      'rounded-xl border bg-card/60 transition-all overflow-hidden border-l-4',
                      sevMeta.borderClass,
                      isCited
                        ? 'border-cyan-500/60 ring-2 ring-cyan-500/20 shadow-md'
                        : 'border-border/80 hover:border-border'
                    )}
                  >
                    {/* Finding Header (Click to expand/collapse) */}
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => toggleFinding(finding.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          toggleFinding(finding.id);
                        }
                      }}
                      className="p-3 cursor-pointer select-none space-y-2 hover:bg-muted/10 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          {/* Severity Badge */}
                          <span
                            className={cn(
                              'px-2 py-0.5 rounded text-[10px] font-bold uppercase border tracking-wider flex items-center gap-1',
                              sevMeta.badgeClass
                            )}
                          >
                            <sevMeta.icon className="h-3 w-3" />
                            <span>{sevMeta.label}</span>
                          </span>

                          {/* Category Badge */}
                          <span
                            className={cn(
                              'px-2 py-0.5 rounded text-[10px] font-mono border capitalize',
                              CATEGORY_COLORS[finding.category] ||
                                'bg-muted/40 border-border text-foreground'
                            )}
                          >
                            {CATEGORY_NAMES[finding.category] || finding.category}
                          </span>

                          {/* Source Type Badge */}
                          <span
                            className={cn(
                              'px-1.5 py-0.5 rounded text-[10px] font-mono border flex items-center gap-1',
                              sourceMeta.className
                            )}
                            title={sourceMeta.description}
                          >
                            <sourceMeta.icon className="h-3 w-3" />
                            <span>{sourceMeta.label}</span>
                          </span>

                          {/* New in change tag */}
                          {finding.is_new_in_change ? (
                            <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 text-[9px] font-mono font-medium">
                              New in Change
                            </span>
                          ) : (
                            <span className="px-1.5 py-0.5 rounded bg-muted/40 text-muted-foreground border border-border/50 text-[9px] font-mono">
                              Pre-existing
                            </span>
                          )}

                          {/* Uncertainty indicator */}
                          {finding.is_uncertain && (
                            <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30 text-[9px] font-mono flex items-center gap-0.5">
                              <HelpCircle className="h-2.5 w-2.5" />
                              <span>Uncertain</span>
                            </span>
                          )}
                        </div>

                        <div className="flex items-center gap-1 shrink-0 text-muted-foreground">
                          {isExpanded ? (
                            <ChevronUp className="h-4 w-4" />
                          ) : (
                            <ChevronDown className="h-4 w-4" />
                          )}
                        </div>
                      </div>

                      <h4 className="text-xs font-semibold text-foreground leading-snug">
                        {finding.title}
                      </h4>

                      {/* Source Reference Quick Button */}
                      {finding.source_reference && (
                        <div className="flex items-center gap-1 text-[11px] font-mono text-muted-foreground pt-0.5">
                          <Code2 className="h-3 w-3 text-primary shrink-0" />
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSourceClick(finding.source_reference);
                            }}
                            className="text-primary hover:underline font-medium truncate max-w-[280px] text-left inline-flex items-center gap-1"
                            title={`Navigate to ${finding.source_reference.file_path}`}
                          >
                            <span>{finding.source_reference.file_path}</span>
                            {hasLineRange && (
                              <span className="text-foreground">
                                :L{finding.source_reference.start_line}
                                {finding.source_reference.end_line &&
                                finding.source_reference.end_line !==
                                  finding.source_reference.start_line
                                  ? `–L${finding.source_reference.end_line}`
                                  : ''}
                              </span>
                            )}
                            <ExternalLink className="h-2.5 w-2.5 opacity-60 ml-0.5" />
                          </button>
                        </div>
                      )}
                    </div>

                    {/* Finding Body (Collapsible) */}
                    {isExpanded && (
                      <div className="p-3 pt-0 border-t border-border/50 space-y-3 bg-muted/5 text-xs">
                        {/* Description */}
                        <div className="space-y-1 pt-2">
                          <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider font-mono">
                            Description:
                          </span>
                          <p className="text-foreground/90 leading-relaxed font-sans text-xs">
                            {finding.description}
                          </p>
                        </div>

                        {/* Evidence Snippet */}
                        {finding.evidence && (
                          <div className="space-y-1">
                            <span className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider font-mono">
                              Supporting Evidence:
                            </span>
                            <pre className="p-2.5 rounded-lg bg-background/90 border border-border/70 font-mono text-[11px] text-foreground overflow-x-auto whitespace-pre leading-relaxed">
                              {finding.evidence}
                            </pre>
                          </div>
                        )}

                        {/* Suggested Fix / Remediation */}
                        {finding.suggested_fix && (
                          <div className="space-y-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-2.5">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[10px] uppercase font-bold text-emerald-400 tracking-wider font-mono flex items-center gap-1">
                                <Sparkles className="h-3 w-3" />
                                Suggested Remediation:
                              </span>
                              <button
                                type="button"
                                onClick={() => handleCopyFix(finding.id, finding.suggested_fix!)}
                                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/20 transition-colors shadow-2xs"
                              >
                                {copiedId === finding.id ? (
                                  <>
                                    <Check className="h-3 w-3" />
                                    <span>Copied</span>
                                  </>
                                ) : (
                                  <>
                                    <Copy className="h-3 w-3" />
                                    <span>Copy Fix</span>
                                  </>
                                )}
                              </button>
                            </div>
                            <pre className="p-2 rounded bg-background/80 border border-emerald-500/20 font-mono text-[11px] text-foreground overflow-x-auto whitespace-pre leading-relaxed">
                              {finding.suggested_fix}
                            </pre>
                          </div>
                        )}

                        {/* Meta footer: Confidence, Rule ID, Location Action */}
                        <div className="pt-1 flex items-center justify-between text-[10px] font-mono text-muted-foreground flex-wrap gap-2">
                          <div className="flex items-center gap-2">
                            <span>
                              Confidence:{' '}
                              <strong className="text-foreground capitalize">
                                {finding.confidence || 'Medium'}
                              </strong>
                            </span>
                            {finding.rule_id && (
                              <span>
                                Rule: <code className="text-foreground">{finding.rule_id}</code>
                              </span>
                            )}
                          </div>

                          {finding.source_reference && (
                            <button
                              type="button"
                              onClick={() => handleSourceClick(finding.source_reference)}
                              className="text-primary hover:underline inline-flex items-center gap-1 font-medium"
                            >
                              <span>Navigate to source</span>
                              <ExternalLink className="h-2.5 w-2.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* 7. Missing Context Warnings Accordion                              */}
      {/* ------------------------------------------------------------------ */}
      {report.missing_context && report.missing_context.length > 0 && (
        <div className="rounded-xl border border-border/70 bg-muted/15 p-3 space-y-2 text-xs">
          <button
            type="button"
            onClick={() => setShowMissingContext(!showMissingContext)}
            className="w-full flex items-center justify-between text-muted-foreground hover:text-foreground text-left"
          >
            <div className="flex items-center gap-1.5 font-mono text-[11px]">
              <Info className="h-3.5 w-3.5 text-primary" />
              <span>Review Diagnostic Warnings ({report.missing_context.length})</span>
            </div>
            {showMissingContext ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </button>

          {showMissingContext && (
            <ul className="list-disc list-inside space-y-1 text-[11px] text-muted-foreground font-sans pl-1">
              {report.missing_context.map((warn, i) => (
                <li key={i} className="leading-relaxed">
                  {warn}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Standalone Review Target Selector Component (Used in Idle / Configure Mode)
// ---------------------------------------------------------------------------

export interface ReviewTargetSelectorProps {
  initialTarget: ReviewTarget;
  currentFilePath?: string | null;
  onRunReview: (target: ReviewTarget) => void;
  isRunning?: boolean;
  repositoryId?: string;
  onReopenReview?: (result: ReviewReportResponse) => void;
  className?: string;
}

export function ReviewTargetSelector({
  initialTarget,
  currentFilePath,
  onRunReview,
  isRunning = false,
  repositoryId,
  onReopenReview,
  className,
}: ReviewTargetSelectorProps) {
  const [targetType, setTargetType] = useState<ReviewTargetType>(initialTarget.type || 'file');
  const [filePath, setFilePath] = useState<string>(initialTarget.path || currentFilePath || '');
  const [commitSha, setCommitSha] = useState<string>(initialTarget.commit_sha || '');
  const [prNumber, setPrNumber] = useState<string>(
    initialTarget.pr_number ? String(initialTarget.pr_number) : ''
  );
  const [diffText, setDiffText] = useState<string>(initialTarget.diff || '');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  function handleSubmit(e?: React.FormEvent) {
    if (e) e.preventDefault();
    setValidationError(null);

    if (targetType === 'file') {
      const p = filePath.trim();
      if (!p) {
        setValidationError('A valid repository file path is required to review a file.');
        return;
      }
      onRunReview({
        type: 'file',
        path: p,
      });
      return;
    }

    if (targetType === 'commit') {
      const sha = commitSha.trim();
      if (!sha || !/^[0-9a-fA-F]{7,64}$/.test(sha)) {
        setValidationError(
          'Commit SHA must be a valid 7-to-64 character hexadecimal hash (e.g. 7a3b4c1).'
        );
        return;
      }
      onRunReview({
        type: 'commit',
        commit_sha: sha,
      });
      return;
    }

    if (targetType === 'pr') {
      const num = parseInt(prNumber.trim(), 10);
      if (isNaN(num) || num < 1) {
        setValidationError('Pull Request number must be a positive integer (e.g. 12).');
        return;
      }
      onRunReview({
        type: 'pr',
        pr_number: num,
      });
      return;
    }

    if (targetType === 'diff') {
      const d = diffText.trim();
      if (!d) {
        setValidationError('Unified diff text is required to run a custom diff review.');
        return;
      }
      onRunReview({
        type: 'diff',
        diff: d,
      });
      return;
    }
  }

  return (
    <form onSubmit={handleSubmit} className={cn('space-y-4 py-2', className)}>
      <div className="rounded-xl border border-border/80 bg-background/60 p-4 space-y-3 shadow-xs">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg border bg-purple-500/10 text-purple-400 border-purple-500/30 shrink-0">
              <FileCheck className="h-5 w-5" />
            </div>
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-foreground">Standalone AI Code Review</h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Evaluate changed code against Correctness, Security, Performance, Reliability, and
                Maintainability dimensions without starting an autonomous task.
              </p>
            </div>
          </div>
          {repositoryId && (
            <button
              type="button"
              onClick={() => setShowHistory(!showHistory)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border/70 bg-card hover:bg-accent text-xs font-medium text-muted-foreground hover:text-foreground transition-colors shrink-0"
              title="Open review history"
            >
              <History className="h-3.5 w-3.5 text-primary" />
              <span>Past Reviews</span>
            </button>
          )}
        </div>

        {showHistory && (
          <ReviewHistoryDrawer
            isOpen={showHistory}
            onClose={() => setShowHistory(false)}
            repositoryId={repositoryId}
            onReopenReview={onReopenReview}
          />
        )}

        {/* Target Type Selector Tabs */}
        <div className="pt-2 border-t border-border/50 space-y-1.5">
          <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider font-mono">
            Select Review Target:
          </label>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
            <button
              type="button"
              onClick={() => {
                setTargetType('file');
                setValidationError(null);
              }}
              className={cn(
                'flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all',
                targetType === 'file'
                  ? 'bg-primary/20 border-primary text-primary font-bold shadow-xs'
                  : 'border-border/70 bg-card text-muted-foreground hover:text-foreground hover:bg-accent'
              )}
            >
              <FileText className="h-3.5 w-3.5" />
              <span>Active File</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setTargetType('commit');
                setValidationError(null);
              }}
              className={cn(
                'flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all',
                targetType === 'commit'
                  ? 'bg-primary/20 border-primary text-primary font-bold shadow-xs'
                  : 'border-border/70 bg-card text-muted-foreground hover:text-foreground hover:bg-accent'
              )}
            >
              <GitCommit className="h-3.5 w-3.5" />
              <span>Commit SHA</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setTargetType('pr');
                setValidationError(null);
              }}
              className={cn(
                'flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all',
                targetType === 'pr'
                  ? 'bg-primary/20 border-primary text-primary font-bold shadow-xs'
                  : 'border-border/70 bg-card text-muted-foreground hover:text-foreground hover:bg-accent'
              )}
            >
              <GitPullRequest className="h-3.5 w-3.5" />
              <span>GitHub PR #</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setTargetType('diff');
                setValidationError(null);
              }}
              className={cn(
                'flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all',
                targetType === 'diff'
                  ? 'bg-primary/20 border-primary text-primary font-bold shadow-xs'
                  : 'border-border/70 bg-card text-muted-foreground hover:text-foreground hover:bg-accent'
              )}
            >
              <FileDiff className="h-3.5 w-3.5" />
              <span>Unified Diff</span>
            </button>
          </div>
        </div>

        {/* Dynamic Target Input Field */}
        <div className="space-y-2 pt-1 font-sans">
          {targetType === 'file' && (
            <div className="space-y-1">
              <div className="flex justify-between text-xs font-mono">
                <span className="text-muted-foreground">Target File:</span>
                <span className="text-foreground font-medium truncate max-w-[220px]">
                  {filePath || currentFilePath || 'No file selected'}
                </span>
              </div>
              <input
                type="text"
                value={filePath}
                onChange={(e) => setFilePath(e.target.value)}
                placeholder="e.g. backend/app/main.py"
                className="w-full px-3 py-1.5 rounded-lg border border-border bg-card text-xs text-foreground placeholder:text-muted-foreground font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
          )}

          {targetType === 'commit' && (
            <div className="space-y-1">
              <label className="text-[11px] font-mono text-muted-foreground">
                Git Commit SHA (7–64 hex characters):
              </label>
              <input
                type="text"
                value={commitSha}
                onChange={(e) => setCommitSha(e.target.value)}
                placeholder="e.g. aadeed7 or 9ab6879e2c4b8..."
                className="w-full px-3 py-1.5 rounded-lg border border-border bg-card text-xs text-foreground placeholder:text-muted-foreground font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
          )}

          {targetType === 'pr' && (
            <div className="space-y-1">
              <label className="text-[11px] font-mono text-muted-foreground">
                GitHub Pull Request Number:
              </label>
              <input
                type="number"
                min="1"
                step="1"
                value={prNumber}
                onChange={(e) => setPrNumber(e.target.value)}
                placeholder="e.g. 104"
                className="w-full px-3 py-1.5 rounded-lg border border-border bg-card text-xs text-foreground placeholder:text-muted-foreground font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
          )}

          {targetType === 'diff' && (
            <div className="space-y-1">
              <label className="text-[11px] font-mono text-muted-foreground">
                Paste Unified Diff:
              </label>
              <textarea
                rows={4}
                value={diffText}
                onChange={(e) => setDiffText(e.target.value)}
                placeholder="diff --git a/app.py b/app.py&#10;--- a/app.py&#10;+++ b/app.py&#10;@@ -1,3 +1,3 @@"
                className="w-full px-3 py-1.5 rounded-lg border border-border bg-card text-xs text-foreground placeholder:text-muted-foreground font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring resize-y"
              />
            </div>
          )}
        </div>

        {/* Validation Error Banner */}
        {validationError && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs flex items-start gap-2">
            <AlertOctagon className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
            <span className="text-rose-300 text-[11px] leading-relaxed">{validationError}</span>
          </div>
        )}

        {/* Submit Action */}
        <div className="pt-2">
          <button
            type="submit"
            disabled={isRunning}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 transition-all shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 disabled:pointer-events-none"
          >
            <FileCheck className="h-4 w-4" />
            <span>{isRunning ? 'Submitting Review…' : 'Run Code Review'}</span>
          </button>
        </div>
      </div>

      <div className="rounded-lg bg-muted/20 border border-border/60 p-3 flex items-start gap-2.5 text-xs text-muted-foreground">
        <Info className="h-4 w-4 text-primary shrink-0 mt-0.5" />
        <p className="text-[11px] leading-relaxed">
          Standalone code reviews combine static linters, secret redaction, and AI reasoning. Results
          are categorized into Correctness, Security, Performance, Reliability, and Maintainability.
        </p>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Review History Drawer Component (Integrated Scenario D Step 7)
// ---------------------------------------------------------------------------

export interface ReviewHistoryDrawerProps {
  repositoryId?: string;
  onReopenReview?: (result: ReviewReportResponse) => void;
  isOpen: boolean;
  onClose: () => void;
}

export function ReviewHistoryDrawer({
  repositoryId,
  onReopenReview,
  isOpen,
  onClose,
}: ReviewHistoryDrawerProps) {
  const [loading, setLoading] = useState(false);
  const [runs, setRuns] = useState<AnalysisRunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reopeningId, setReopeningId] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    if (isOpen && repositoryId) {
      Promise.resolve().then(() => {
        if (!ignore) {
          setLoading(true);
          setError(null);
        }
      });
      getCodeReviewHistory(repositoryId, { page_size: 10 })
        .then((res) => {
          if (!ignore) {
            setRuns(res.items || []);
          }
        })
        .catch((err: any) => {
          if (!ignore) {
            setError(err?.message || 'Failed to load review history.');
          }
        })
        .finally(() => {
          if (!ignore) {
            setLoading(false);
          }
        });
    }
    return () => {
      ignore = true;
    };
  }, [isOpen, repositoryId]);

  if (!isOpen) return null;

  async function handleReopen(runId: string) {
    setReopeningId(runId);
    try {
      const detail = await reopenCodeReview(runId);
      const payloadReport = (detail.result_payload as any)?.report;
      const payloadTarget = (detail.result_payload as any)?.target;

      const reconstructed: ReviewReportResponse = {
        run_id: detail.id,
        repository_id: detail.repository_id,
        status: detail.status,
        target: payloadTarget || {
          type: 'file',
          path: detail.target_path,
        },
        report: payloadReport || {
          summary: `Reopened historical review from ${new Date(detail.created_at).toLocaleString()}`,
          risk_level: payloadReport?.risk_level || (detail.findings_count > 0 ? 'MEDIUM' : 'NONE'),
          findings: (detail.findings || []) as ReviewFinding[],
          total_findings: detail.findings_count,
          category_counts: payloadReport?.category_counts || {},
          missing_context: payloadReport?.missing_context || [],
        },
        created_at: detail.created_at,
      };

      onReopenReview?.(reconstructed);
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to reopen historical review run.');
    } finally {
      setReopeningId(null);
    }
  }

  return (
    <div className="rounded-xl border border-border/80 bg-background/95 p-4 space-y-3 shadow-md animate-in fade-in">
      <div className="flex items-center justify-between border-b border-border/50 pb-2">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-primary" />
          <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">
            Review History & Past Runs
          </h4>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground p-1 rounded-md"
          aria-label="Close review history"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading && (
        <div className="py-6 flex flex-col items-center justify-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin text-primary" />
          <span>Loading historical review runs…</span>
        </div>
      )}

      {error && (
        <div className="p-3 rounded-lg border border-rose-500/30 bg-rose-500/10 text-xs text-rose-300">
          {error}
        </div>
      )}

      {!loading && !error && runs.length === 0 && (
        <div className="py-6 text-center text-xs text-muted-foreground space-y-1">
          <Clock className="h-5 w-5 mx-auto text-muted-foreground/60" />
          <p>No past code review runs found for this repository.</p>
        </div>
      )}

      {!loading && !error && runs.length > 0 && (
        <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
          {runs.map((run) => (
            <div
              key={run.id}
              className="p-2.5 rounded-lg border border-border/60 bg-card/60 hover:border-border flex items-center justify-between gap-3 text-xs"
            >
              <div className="space-y-1 min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-muted-foreground truncate">
                    {new Date(run.created_at).toLocaleString()}
                  </span>
                  <span
                    className={cn(
                      'px-1.5 py-0.5 rounded text-[9px] font-mono uppercase font-bold',
                      run.status === 'COMPLETED'
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                        : 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
                    )}
                  >
                    {run.status}
                  </span>
                </div>
                <div className="font-mono text-[11px] truncate text-foreground">
                  Target: {run.target_path || 'All Changes'}{' '}
                  {run.source_revision && (
                    <span className="text-muted-foreground">(@{run.source_revision.slice(0, 7)})</span>
                  )}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {run.findings_count} finding{run.findings_count === 1 ? '' : 's'} recorded
                </div>
              </div>

              <button
                type="button"
                disabled={reopeningId === run.id}
                onClick={() => handleReopen(run.id)}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 text-xs font-semibold shrink-0 transition-colors disabled:opacity-50"
              >
                {reopeningId === run.id ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RotateCcw className="h-3 w-3" />
                )}
                <span>Reopen</span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
