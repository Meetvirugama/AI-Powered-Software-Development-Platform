import { useState, useMemo, useEffect, useRef } from 'react';
import {
  FlaskConical,
  Copy,
  Check,
  Download,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Info,
  FileCode,
  Code2,
  Terminal,
  ChevronDown,
  ChevronUp,
  ShieldCheck,
  HelpCircle,
  Activity,
  ListChecks,
  PlayCircle,
  Gauge,
  Repeat,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type {
  TestGenerationResult,
  TestScenario,
  TestScenarioCategory,
  SupportedTestFramework,
  SourceReference,
  TestRequirement,
  TestQualityReport,
  TestVerificationStatus,
} from '../../types/analysis';

export interface TestGenerationViewProps {
  result: TestGenerationResult;
  proposedPathStatus?: 'EXISTS' | 'NEW' | 'UNKNOWN';
  proposedPathExists?: boolean;
  onSelectSourceReference?: (source: SourceReference) => void;
  activeSourceReference?: SourceReference | null;
  onSelectFramework?: (framework: SupportedTestFramework | null) => void;
  selectedFrameworkOverride?: SupportedTestFramework | null;
  className?: string;
}

const CATEGORY_CONFIG: Record<
  TestScenarioCategory,
  {
    label: string;
    badgeClass: string;
    pillClass: string;
    dotClass: string;
  }
> = {
  normal: {
    label: 'Normal Behavior',
    badgeClass: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    pillClass: 'hover:bg-emerald-500/20 data-[active=true]:bg-emerald-500/25 data-[active=true]:text-emerald-300 data-[active=true]:border-emerald-500/50',
    dotClass: 'bg-emerald-400',
  },
  edge_case: {
    label: 'Edge Cases',
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    pillClass: 'hover:bg-amber-500/20 data-[active=true]:bg-amber-500/25 data-[active=true]:text-amber-300 data-[active=true]:border-amber-500/50',
    dotClass: 'bg-amber-400',
  },
  failure_path: {
    label: 'Failure Paths',
    badgeClass: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
    pillClass: 'hover:bg-rose-500/20 data-[active=true]:bg-rose-500/25 data-[active=true]:text-rose-300 data-[active=true]:border-rose-500/50',
    dotClass: 'bg-rose-400',
  },
};

const FRAMEWORK_COMMANDS: Record<SupportedTestFramework, string> = {
  pytest: 'pytest <path>',
  unittest: 'python -m unittest <path>',
  jest: 'npm test -- <path>',
  vitest: 'npm test -- --run <path>',
};

export function TestGenerationView({
  result,
  proposedPathStatus,
  proposedPathExists = false,
  onSelectSourceReference,
  activeSourceReference,
  onSelectFramework,
  selectedFrameworkOverride,
  className,
}: TestGenerationViewProps) {
  const {
    detected_framework,
    proposed_test_path,
    test_content,
    covered_scenarios = [],
    assumptions_and_warnings = [],
    syntax_valid,
    validation_errors = [],
    sources = [],
  } = result;

  const [activeCategoryFilter, setActiveCategoryFilter] = useState<TestScenarioCategory | 'ALL'>('ALL');
  const [showAssumptions, setShowAssumptions] = useState(true);
  const [showRequirements, setShowRequirements] = useState(true);
  const [showQualityReport, setShowQualityReport] = useState(true);
  const [reqFilter, setReqFilter] = useState<'ALL' | 'MISSING' | 'COVERED' | 'CRITICAL'>('ALL');
  const [showStabilityDetails, setShowStabilityDetails] = useState(true);
  const [showCoverageDetails, setShowCoverageDetails] = useState(true);
  const [showIterationDetails, setShowIterationDetails] = useState(true);
  const [showRawOutput, setShowRawOutput] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copiedCommand, setCopiedCommand] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [downloadSuccess, setDownloadSuccess] = useState(false);
  const timeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const requirements = useMemo<TestRequirement[]>(() => result.requirements || [], [result.requirements]);
  const qualityReport: TestQualityReport | null = result.quality_report || null;

  const filteredRequirements = useMemo(() => {
    if (reqFilter === 'ALL') return requirements;
    if (reqFilter === 'MISSING')
      return requirements.filter((r) => r.status === 'MISSING' || r.status === 'PARTIAL');
    if (reqFilter === 'COVERED') return requirements.filter((r) => r.status === 'COVERED');
    if (reqFilter === 'CRITICAL')
      return requirements.filter((r) => (r.priority || '').toUpperCase() === 'CRITICAL');
    return requirements;
  }, [requirements, reqFilter]);

  useEffect(() => {
    return () => {
      timeoutsRef.current.forEach(clearTimeout);
      timeoutsRef.current = [];
    };
  }, []);

  const registerTimeout = (fn: () => void, ms: number) => {
    const id = setTimeout(fn, ms);
    timeoutsRef.current.push(id);
    return id;
  };

  // Determine effective path collision state (EXISTS, NEW, or UNKNOWN)
  const effectivePathStatus = useMemo<'EXISTS' | 'NEW' | 'UNKNOWN'>(() => {
    if (proposedPathStatus) return proposedPathStatus;
    if (typeof proposedPathExists === 'boolean') {
      return proposedPathExists ? 'EXISTS' : 'NEW';
    }
    return 'UNKNOWN';
  }, [proposedPathStatus, proposedPathExists]);

  // Target language determination for framework compatibility
  const targetLanguage = useMemo<'python' | 'javascript' | 'unknown'>(() => {
    const p = (proposed_test_path || '').toLowerCase();
    if (p.endsWith('.py')) return 'python';
    if (p.endsWith('.ts') || p.endsWith('.tsx') || p.endsWith('.js') || p.endsWith('.jsx')) {
      return 'javascript';
    }
    return 'unknown';
  }, [proposed_test_path]);

  // Frameworks supported by repository configuration and backend contract
  const compatibleFrameworks: SupportedTestFramework[] = useMemo(() => {
    if (targetLanguage === 'python') {
      return ['pytest', 'unittest'];
    }
    if (targetLanguage === 'javascript') {
      return ['jest'];
    }
    return ['pytest', 'unittest', 'jest'];
  }, [targetLanguage]);

  const hasFrameworkOverride = Boolean(
    selectedFrameworkOverride && selectedFrameworkOverride !== detected_framework
  );

  // Group scenarios by category
  const categorizedScenarios = useMemo(() => {
    const normal = covered_scenarios.filter((s) => s.category === 'normal');
    const edge = covered_scenarios.filter((s) => s.category === 'edge_case');
    const failure = covered_scenarios.filter((s) => s.category === 'failure_path');
    const other = covered_scenarios.filter(
      (s) => !['normal', 'edge_case', 'failure_path'].includes(s.category)
    );
    return { normal, edge, failure, other };
  }, [covered_scenarios]);

  const filteredScenarios = useMemo(() => {
    if (activeCategoryFilter === 'ALL') return covered_scenarios;
    return covered_scenarios.filter((s) => s.category === activeCategoryFilter);
  }, [covered_scenarios, activeCategoryFilter]);

  // Derive safe download filename from proposed test path
  const downloadFilename = useMemo(() => {
    const fallback = detected_framework === 'jest' ? 'test.test.ts' : 'test_suite.py';
    if (!proposed_test_path) return fallback;
    const cleaned = proposed_test_path.replace(/\\/g, '/');
    const rawName = cleaned.split('/').pop() || fallback;
    // Sanitize filename against directory traversal and special chars
    const sanitized = rawName.replace(/[^a-zA-Z0-9._-]/g, '_');
    return sanitized || fallback;
  }, [proposed_test_path, detected_framework]);

  // Code line metrics
  const lines = useMemo(() => {
    if (!test_content) return [];
    return test_content.split(/\r?\n/);
  }, [test_content]);

  // Copy full content handler
  async function handleCopy() {
    if (!test_content || !test_content.trim()) return;
    setCopyError(null);
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(test_content);
        setCopied(true);
        registerTimeout(() => setCopied(false), 2000);
      } else {
        // Fallback for non-secure contexts / headless browsers
        const textarea = document.createElement('textarea');
        textarea.value = test_content;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        textarea.style.top = '-9999px';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        const successful = document.execCommand('copy');
        document.body.removeChild(textarea);
        if (successful) {
          setCopied(true);
          registerTimeout(() => setCopied(false), 2000);
        } else {
          throw new Error('execCommand copy failed');
        }
      }
    } catch {
      setCopyError('Unable to access clipboard. Please copy manually from the preview below.');
      registerTimeout(() => setCopyError(null), 4000);
    }
  }

  // Download test file handler (Blob-based export, strictly local non-destructive)
  function handleDownload() {
    if (!test_content || !test_content.trim()) return;
    try {
      const blob = new Blob([test_content], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = downloadFilename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      registerTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloadSuccess(true);
      registerTimeout(() => setDownloadSuccess(false), 2500);
    } catch {
      // Ignore download trigger errors
    }
  }

  // Copy terminal runner command handler
  async function handleCopyCommand() {
    const formatted = runnerCommand.replace('<path>', proposed_test_path || '<path>');
    if (!formatted) return;
    try {
      if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        await navigator.clipboard.writeText(formatted);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = formatted;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setCopiedCommand(true);
      registerTimeout(() => setCopiedCommand(false), 2000);
    } catch {
      // Ignore clipboard write failures
    }
  }

  const effectiveFramework = selectedFrameworkOverride || detected_framework;
  const runnerCommand = FRAMEWORK_COMMANDS[effectiveFramework] || 'pytest <path>';

  const verificationStatus: TestVerificationStatus = result.verification_status || 'UNVERIFIED';
  const stabilityReport = result.stability_report;
  const coverageReport = result.coverage_report;
  const iterationReport = result.iteration_report;
  const rawOutput = result.raw_execution_output;

  return (
    <div className={cn('space-y-4 text-xs', className)}>
      {/* -------------------------------------------------------------- */}
      {/* 0. Execution Verification Status Banner (task.md §4, §10)       */}
      {/* -------------------------------------------------------------- */}
      <div
        className={cn(
          'rounded-xl border p-3.5 space-y-2.5 shadow-xs transition-colors',
          verificationStatus === 'VERIFIED'
            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
            : verificationStatus === 'REJECTED'
            ? 'border-rose-500/40 bg-rose-500/10 text-rose-300'
            : verificationStatus === 'EXECUTION_ERROR'
            ? 'border-zinc-500/40 bg-zinc-500/10 text-zinc-300'
            : 'border-amber-500/40 bg-amber-500/10 text-amber-300'
        )}
      >
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            {verificationStatus === 'VERIFIED' ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
            ) : verificationStatus === 'REJECTED' ? (
              <XCircle className="h-4 w-4 text-rose-400 shrink-0" />
            ) : verificationStatus === 'EXECUTION_ERROR' ? (
              <AlertTriangle className="h-4 w-4 text-zinc-400 shrink-0" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
            )}
            <div>
              <div className="text-[10px] font-mono uppercase tracking-wider opacity-80">
                Verification Pipeline Status
              </div>
              <div className="text-xs font-bold font-mono tracking-tight flex items-center gap-1.5">
                <span>{verificationStatus}</span>
                {verificationStatus === 'VERIFIED' && (
                  <span className="text-[10px] font-sans font-normal opacity-90">
                    (Passed static checks, 3/3 stability runs, and attributed coverage)
                  </span>
                )}
                {verificationStatus === 'UNVERIFIED' && (
                  <span className="text-[10px] font-sans font-normal opacity-90">
                    (Pending sandbox execution or verification conditions unmet)
                  </span>
                )}
              </div>
            </div>
          </div>

          <span
            className={cn(
              'px-2 py-0.5 rounded-full text-[10px] font-mono uppercase font-semibold border',
              verificationStatus === 'VERIFIED'
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                : verificationStatus === 'REJECTED'
                ? 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                : verificationStatus === 'EXECUTION_ERROR'
                ? 'bg-zinc-500/20 text-zinc-300 border-zinc-500/40'
                : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
            )}
          >
            {verificationStatus}
          </span>
        </div>

        {result.verification_reasons && result.verification_reasons.length > 0 && (
          <div className="pt-2 border-t border-current/15 space-y-1">
            <div className="text-[10px] font-mono uppercase tracking-wider opacity-80">
              Verification Details:
            </div>
            {result.verification_reasons.map((reason, idx) => (
              <div key={idx} className="flex items-start gap-1.5 text-[11px] leading-relaxed">
                <span className="font-mono text-[10px] mt-0.5">•</span>
                <span>{reason}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* -------------------------------------------------------------- */}
      {/* 0.1. Stability Validation Report (task.md §4.6)                 */}
      {/* -------------------------------------------------------------- */}
      {stabilityReport && (
        <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-2.5 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 font-semibold text-foreground text-xs">
              <PlayCircle className="h-3.5 w-3.5 text-primary" />
              <span>Three-Run Stability Validation</span>
              <span
                className={cn(
                  'px-1.5 py-0.5 rounded text-[10px] font-mono font-bold border',
                  stabilityReport.classification === 'STABLE'
                    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                    : stabilityReport.classification === 'UNSTABLE'
                    ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                    : 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                )}
              >
                {stabilityReport.passed_runs}/{stabilityReport.total_runs} PASSED ({stabilityReport.classification})
              </span>
            </div>
            <button
              type="button"
              onClick={() => setShowStabilityDetails(!showStabilityDetails)}
              className="p-1 rounded hover:bg-muted/40 text-muted-foreground cursor-pointer"
            >
              {showStabilityDetails ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>

          {showStabilityDetails && stabilityReport.runs && (
            <div className="space-y-1.5 pt-1 border-t border-border/40">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {stabilityReport.runs.map((run) => (
                  <div
                    key={run.run_number}
                    className={cn(
                      'p-2 rounded-lg border font-mono text-[11px] space-y-1',
                      run.passed
                        ? 'bg-emerald-500/5 border-emerald-500/20 text-emerald-400'
                        : 'bg-rose-500/5 border-rose-500/20 text-rose-400'
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold">Run #{run.run_number}</span>
                      <span className="text-[10px]">{run.passed ? 'PASS' : 'FAIL'}</span>
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      {run.duration_seconds}s • exit {run.exit_code}
                    </div>
                    {run.error_message && (
                      <div className="text-[9px] text-rose-300 truncate" title={run.error_message}>
                        {run.error_message}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* 0.2. Runtime Coverage Delta & Attribution (task.md §5)          */}
      {/* -------------------------------------------------------------- */}
      {coverageReport && (
        <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-2.5 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 font-semibold text-foreground text-xs">
              <Gauge className="h-3.5 w-3.5 text-primary" />
              <span>Runtime Coverage Attribution</span>
              {coverageReport.coverage_attributable_to_generated_tests && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                  Attributed
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => setShowCoverageDetails(!showCoverageDetails)}
              className="p-1 rounded hover:bg-muted/40 text-muted-foreground cursor-pointer"
            >
              {showCoverageDetails ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>

          {showCoverageDetails && (
            <div className="space-y-2.5 pt-1 border-t border-border/40">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono text-[11px]">
                <div className="p-2 rounded-lg bg-muted/20 border border-border/40 space-y-1">
                  <div className="text-[10px] text-muted-foreground uppercase">Baseline Line Cov</div>
                  <div className="text-sm font-semibold text-foreground">
                    {coverageReport.baseline_line_coverage !== null && coverageReport.baseline_line_coverage !== undefined
                      ? `${coverageReport.baseline_line_coverage}%`
                      : 'N/A'}
                  </div>
                </div>
                <div className="p-2 rounded-lg bg-muted/20 border border-border/40 space-y-1">
                  <div className="text-[10px] text-muted-foreground uppercase">Final Line Cov</div>
                  <div className="text-sm font-semibold text-emerald-400">
                    {coverageReport.final_line_coverage !== null && coverageReport.final_line_coverage !== undefined
                      ? `${coverageReport.final_line_coverage}%`
                      : 'N/A'}
                  </div>
                </div>
                <div className="p-2 rounded-lg bg-muted/20 border border-border/40 space-y-1">
                  <div className="text-[10px] text-muted-foreground uppercase">Line Gain</div>
                  <div className="text-sm font-semibold text-primary">
                    {coverageReport.line_coverage_gain !== null && coverageReport.line_coverage_gain !== undefined
                      ? `${coverageReport.line_coverage_gain > 0 ? '+' : ''}${coverageReport.line_coverage_gain}%`
                      : 'N/A'}
                  </div>
                </div>
                <div className="p-2 rounded-lg bg-muted/20 border border-border/40 space-y-1">
                  <div className="text-[10px] text-muted-foreground uppercase">New Lines Covered</div>
                  <div className="text-sm font-semibold text-blue-400">
                    {coverageReport.newly_covered_lines ? coverageReport.newly_covered_lines.length : 0}
                  </div>
                </div>
              </div>

              {coverageReport.newly_covered_lines && coverageReport.newly_covered_lines.length > 0 && (
                <div className="p-2 rounded-lg bg-muted/15 border border-border/40 font-mono text-[10px] text-muted-foreground space-y-1">
                  <span className="font-semibold text-foreground">Exercised Source Lines: </span>
                  <span>{coverageReport.newly_covered_lines.join(', ')}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* 0.3. Iterative Feedback Rounds (task.md §6)                    */}
      {/* -------------------------------------------------------------- */}
      {iterationReport && (
        <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-2.5 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 font-semibold text-foreground text-xs">
              <Repeat className="h-3.5 w-3.5 text-primary" />
              <span>Coverage-Guided Iterative Rounds ({iterationReport.total_rounds}/3)</span>
            </div>
            <button
              type="button"
              onClick={() => setShowIterationDetails(!showIterationDetails)}
              className="p-1 rounded hover:bg-muted/40 text-muted-foreground cursor-pointer"
            >
              {showIterationDetails ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>

          {showIterationDetails && (
            <div className="space-y-1.5 pt-1 border-t border-border/40 text-[11px]">
              <div className="text-muted-foreground">
                <span className="font-semibold text-foreground">Stopping Reason: </span>
                <span>{iterationReport.stopping_reason}</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* 0.4. Raw Execution Terminal Console (Collapsible)               */}
      {/* -------------------------------------------------------------- */}
      {rawOutput && (
        <div className="rounded-xl border border-border/80 bg-background/60 overflow-hidden shadow-xs">
          <button
            type="button"
            onClick={() => setShowRawOutput(!showRawOutput)}
            className="w-full p-3 bg-muted/20 flex items-center justify-between text-left text-xs font-semibold text-foreground cursor-pointer hover:bg-muted/30 transition-colors"
          >
            <div className="flex items-center gap-1.5">
              <Terminal className="h-3.5 w-3.5 text-primary" />
              <span>Sandboxed Execution Logs</span>
            </div>
            {showRawOutput ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
          {showRawOutput && (
            <div className="p-3 bg-black/80 font-mono text-[11px] text-zinc-300 whitespace-pre-wrap overflow-x-auto max-h-48 border-t border-border/40">
              {rawOutput}
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* 1. Framework Banner & Runner Command                            */}
      {/* -------------------------------------------------------------- */}
      <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-2.5 shadow-xs">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <div className="h-6 w-6 rounded-md bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
              <FlaskConical className="h-3.5 w-3.5" />
            </div>
            <div>
              <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <span>Detected Framework</span>
                <span className="text-[9px] px-1 rounded bg-muted/60 text-muted-foreground">
                  Repository Engine
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-foreground font-mono">
                  {detected_framework}
                </span>
                {hasFrameworkOverride && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-500/15 text-purple-300 border border-purple-500/30">
                    Active Override: {selectedFrameworkOverride}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Supported Framework Override Selector (restricted to configuration) */}
          {onSelectFramework && compatibleFrameworks.length > 1 && (
            <div className="flex items-center gap-1.5 text-[11px]">
              <span className="text-muted-foreground">Runner:</span>
              <select
                value={selectedFrameworkOverride || detected_framework}
                onChange={(e) =>
                  onSelectFramework(
                    e.target.value === detected_framework
                      ? null
                      : (e.target.value as SupportedTestFramework)
                  )
                }
                className="px-2 py-1 rounded-md border border-border bg-card text-foreground font-mono text-[11px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring cursor-pointer"
                aria-label="Select test framework override"
              >
                {compatibleFrameworks.map((fw) => (
                  <option key={fw} value={fw}>
                    {fw} {fw === detected_framework ? '(Detected)' : '(Override)'}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 pt-2 border-t border-border/40 text-[11px] font-mono text-muted-foreground">
          <div className="flex items-center gap-1.5 truncate flex-1 min-w-0">
            <Terminal className="h-3 w-3 text-primary shrink-0" />
            <span className="truncate shrink-0">Runner Command:</span>
            <code className="text-foreground bg-muted/40 px-1.5 py-0.5 rounded text-[10px] truncate">
              {runnerCommand.replace('<path>', proposed_test_path || '<path>')}
            </code>
          </div>
          <button
            type="button"
            onClick={handleCopyCommand}
            className="shrink-0 p-1 rounded hover:bg-muted/40 text-muted-foreground hover:text-foreground transition-colors"
            title="Copy test runner command"
            aria-label="Copy test runner command"
          >
            {copiedCommand ? (
              <Check className="h-3 w-3 text-emerald-400" />
            ) : (
              <Copy className="h-3 w-3" />
            )}
          </button>
        </div>
      </div>

      {/* -------------------------------------------------------------- */}
      {/* 2. Proposed Test Path & Collision / Uncertainty Warning        */}
      {/* -------------------------------------------------------------- */}
      <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground flex items-center gap-1">
            <FileCode className="h-3 w-3 text-primary" />
            <span>Proposed Test Path:</span>
          </div>

          {effectivePathStatus === 'EXISTS' ? (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-mono font-medium bg-amber-500/15 text-amber-400 border border-amber-500/30">
              <AlertTriangle className="h-2.5 w-2.5" />
              File Exists (Collision Detected)
            </span>
          ) : effectivePathStatus === 'UNKNOWN' ? (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-mono font-medium bg-blue-500/15 text-blue-400 border border-blue-500/30">
              <HelpCircle className="h-2.5 w-2.5" />
              Existence Unverified
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-mono font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              <CheckCircle2 className="h-2.5 w-2.5" />
              New File (No Collision)
            </span>
          )}
        </div>

        <div className="p-2 rounded-lg bg-muted/20 border border-border/60 font-mono text-[11px] text-foreground break-all select-all">
          {proposed_test_path}
        </div>

        {/* Existing file collision warning callout */}
        {effectivePathStatus === 'EXISTS' && (
          <div
            role="alert"
            className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 space-y-1 animate-in fade-in duration-150"
          >
            <div className="flex items-center gap-1.5 text-amber-400 font-semibold text-[11px]">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              <span>File already exists in this repository</span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              The generated content will not overwrite your existing repository file. Generating, copying, and downloading are local non-destructive export workflows.
            </p>
          </div>
        )}

        {/* Uncertainty notice when file index is unverified */}
        {effectivePathStatus === 'UNKNOWN' && (
          <div
            role="status"
            className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-2.5 space-y-1 animate-in fade-in duration-150"
          >
            <div className="flex items-center gap-1.5 text-blue-400 font-semibold text-[11px]">
              <Info className="h-3.5 w-3.5 shrink-0" />
              <span>Path existence could not be verified automatically</span>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Repository file index is currently loading or unavailable. Please inspect existing workspace files before manually placing exported tests.
            </p>
          </div>
        )}

        {effectivePathStatus === 'NEW' && (
          <p className="text-[10px] text-muted-foreground leading-relaxed">
            Path derived from detected directory layout and naming conventions.
          </p>
        )}

        {/* Non-destructive guarantee badge */}
        <div className="flex items-center gap-1.5 pt-1 text-[10px] text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
          <span>Safety guarantee: Generated tests are preview-only and never modify repository files.</span>
        </div>
      </div>

      {/* -------------------------------------------------------------- */}
      {/* 2.5. Quality Scorecard Dashboard (task.md §8)                  */}
      {/* -------------------------------------------------------------- */}
      {qualityReport && (
        <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-3 shadow-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 font-semibold text-foreground text-xs">
              <Activity className="h-3.5 w-3.5 text-primary" />
              <span>Test Quality Scorecard</span>
              {qualityReport.quality_score !== undefined && qualityReport.quality_score !== null && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-primary/15 text-primary border border-primary/30">
                  {qualityReport.quality_score}/100
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => setShowQualityReport(!showQualityReport)}
              className="p-1 rounded hover:bg-muted/40 text-muted-foreground cursor-pointer"
            >
              {showQualityReport ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>

          {showQualityReport && (
            <div className="space-y-3 pt-1 border-t border-border/40">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 font-mono text-[11px]">
                <div className="p-2 rounded-lg bg-muted/20 border border-border/40 space-y-1">
                  <div className="text-[10px] text-muted-foreground uppercase">Req. Coverage</div>
                  <div className="text-sm font-semibold text-emerald-400">
                    {qualityReport.requirement_coverage_percent !== null && qualityReport.requirement_coverage_percent !== undefined
                      ? `${qualityReport.requirement_coverage_percent}%`
                      : 'N/A'}
                  </div>
                </div>
                <div className="p-2 rounded-lg bg-muted/20 border border-border/40 space-y-1">
                  <div className="text-[10px] text-muted-foreground uppercase">Line Coverage</div>
                  <div className="text-sm font-semibold text-blue-400">
                    {qualityReport.line_coverage_percent !== null && qualityReport.line_coverage_percent !== undefined
                      ? `${qualityReport.line_coverage_percent}%`
                      : 'N/A'}
                  </div>
                </div>
                <div className="p-2 rounded-lg bg-muted/20 border border-border/40 space-y-1">
                  <div className="text-[10px] text-muted-foreground uppercase">Mutation Score</div>
                  <div className="text-sm font-semibold text-purple-400">
                    {qualityReport.mutation_score_percent !== null && qualityReport.mutation_score_percent !== undefined
                      ? `${qualityReport.mutation_score_percent}%`
                      : 'N/A'}
                  </div>
                </div>
                <div className="p-2 rounded-lg bg-muted/20 border border-border/40 space-y-1">
                  <div className="text-[10px] text-muted-foreground uppercase">Weak Assertions</div>
                  <div className={`text-sm font-semibold ${qualityReport.weak_assertion_count > 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                    {qualityReport.weak_assertion_count}
                  </div>
                </div>
              </div>

              {qualityReport.untested_critical_requirements && qualityReport.untested_critical_requirements.length > 0 && (
                <div className="p-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-[11px] flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                  <span>
                    Untested critical requirements remaining: {qualityReport.untested_critical_requirements.join(', ')}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* 3. Static Syntax Validation & Test Execution Disclaimer        */}
      {/* -------------------------------------------------------------- */}
      <div
        className={cn(
          'rounded-xl border p-3 space-y-2',
          syntax_valid
            ? 'border-emerald-500/30 bg-emerald-500/5'
            : 'border-rose-500/30 bg-rose-500/5'
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            {syntax_valid ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0" />
            ) : (
              <XCircle className="h-4 w-4 text-rose-400 shrink-0" />
            )}
            <span
              className={cn(
                'text-xs font-semibold',
                syntax_valid ? 'text-emerald-400' : 'text-rose-400'
              )}
            >
              {syntax_valid
                ? 'Static Syntax Validation Passed'
                : 'Static Syntax Validation Failed'}
            </span>
          </div>

          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-border/60 bg-muted/40 text-muted-foreground">
            Static Check
          </span>
        </div>

        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {syntax_valid
            ? 'Static syntax validation passed. Generated tests have not been executed in the repository.'
            : 'Static syntax or structural errors were detected in the generated test file. The content is preserved below for inspection.'}
        </p>

        {/* Validation Errors List */}
        {!syntax_valid && validation_errors.length > 0 && (
          <div className="pt-2 border-t border-rose-500/20 space-y-1">
            <div className="text-[10px] font-mono uppercase tracking-wider text-rose-400">
              Validation Errors ({validation_errors.length}):
            </div>
            <div className="space-y-1">
              {validation_errors.map((err, idx) => (
                <div
                  key={idx}
                  className="p-1.5 rounded bg-rose-500/10 border border-rose-500/20 font-mono text-[10px] text-rose-300"
                >
                  {err}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* -------------------------------------------------------------- */}
      {/* 4. Covered Scenarios Summary                                   */}
      {/* -------------------------------------------------------------- */}
      <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-3 shadow-xs">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-1.5">
            <Code2 className="h-3.5 w-3.5 text-primary" />
            <h3 className="text-xs font-semibold text-foreground">
              Covered Scenarios ({covered_scenarios.length})
            </h3>
          </div>

          {/* Scenario Category Filter Pills */}
          <div className="flex items-center gap-1 flex-wrap">
            <button
              type="button"
              onClick={() => setActiveCategoryFilter('ALL')}
              data-active={activeCategoryFilter === 'ALL'}
              className="px-2 py-0.5 rounded-full text-[10px] font-mono border border-border/60 text-muted-foreground hover:text-foreground data-[active=true]:bg-primary/20 data-[active=true]:text-primary data-[active=true]:border-primary/40 transition-colors"
            >
              All ({covered_scenarios.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveCategoryFilter('normal')}
              data-active={activeCategoryFilter === 'normal'}
              className={cn(
                'px-2 py-0.5 rounded-full text-[10px] font-mono border border-border/60 text-muted-foreground transition-colors',
                CATEGORY_CONFIG.normal.pillClass
              )}
            >
              Normal ({categorizedScenarios.normal.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveCategoryFilter('edge_case')}
              data-active={activeCategoryFilter === 'edge_case'}
              className={cn(
                'px-2 py-0.5 rounded-full text-[10px] font-mono border border-border/60 text-muted-foreground transition-colors',
                CATEGORY_CONFIG.edge_case.pillClass
              )}
            >
              Edge ({categorizedScenarios.edge.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveCategoryFilter('failure_path')}
              data-active={activeCategoryFilter === 'failure_path'}
              className={cn(
                'px-2 py-0.5 rounded-full text-[10px] font-mono border border-border/60 text-muted-foreground transition-colors',
                CATEGORY_CONFIG.failure_path.pillClass
              )}
            >
              Failure ({categorizedScenarios.failure.length})
            </button>
          </div>
        </div>

        {filteredScenarios.length === 0 ? (
          <div className="p-3 text-center text-muted-foreground text-[11px] italic">
            No scenarios match the selected filter.
          </div>
        ) : (
          <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
            {filteredScenarios.map((scenario: TestScenario, idx: number) => {
              const catConfig =
                CATEGORY_CONFIG[scenario.category] || CATEGORY_CONFIG.normal;

              return (
                <div
                  key={idx}
                  className="p-2.5 rounded-lg border border-border/60 bg-muted/20 space-y-1 hover:border-border transition-colors"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] font-semibold text-foreground truncate" title={scenario.name}>
                      {scenario.name}
                    </span>
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono uppercase tracking-wider border shrink-0',
                        catConfig.badgeClass
                      )}
                    >
                      <span className={cn('h-1.5 w-1.5 rounded-full', catConfig.dotClass)} />
                      {(scenario.category || '').replace(/_/g, ' ')}
                    </span>
                  </div>
                  <p className="text-[11px] text-muted-foreground leading-relaxed">
                    {scenario.description}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* -------------------------------------------------------------- */}
      {/* 4.5. Test Requirement Matrix & Gap Tracker (task.md §2, §7)   */}
      {/* -------------------------------------------------------------- */}
      {requirements.length > 0 && (
        <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-2.5 shadow-xs">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-1.5 font-semibold text-foreground text-xs">
              <ListChecks className="h-3.5 w-3.5 text-primary" />
              <span>Test Requirement Matrix ({requirements.length})</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setReqFilter('ALL')}
                className={`px-2 py-0.5 rounded text-[10px] font-mono border transition-colors cursor-pointer ${
                  reqFilter === 'ALL'
                    ? 'bg-primary/20 text-primary border-primary/40'
                    : 'text-muted-foreground border-border/60 hover:text-foreground'
                }`}
              >
                All ({requirements.length})
              </button>
              <button
                type="button"
                onClick={() => setReqFilter('MISSING')}
                className={`px-2 py-0.5 rounded text-[10px] font-mono border transition-colors cursor-pointer ${
                  reqFilter === 'MISSING'
                    ? 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                    : 'text-muted-foreground border-border/60 hover:text-foreground'
                }`}
              >
                Gaps ({requirements.filter((r) => r.status === 'MISSING' || r.status === 'PARTIAL').length})
              </button>
              <button
                type="button"
                onClick={() => setReqFilter('COVERED')}
                className={`px-2 py-0.5 rounded text-[10px] font-mono border transition-colors cursor-pointer ${
                  reqFilter === 'COVERED'
                    ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                    : 'text-muted-foreground border-border/60 hover:text-foreground'
                }`}
              >
                Covered ({requirements.filter((r) => r.status === 'COVERED').length})
              </button>
              <button
                type="button"
                onClick={() => setShowRequirements(!showRequirements)}
                className="p-1 rounded hover:bg-muted/40 text-muted-foreground ml-1 cursor-pointer"
              >
                {showRequirements ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              </button>
            </div>
          </div>

          {showRequirements && (
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1 pt-1 border-t border-border/40">
              {filteredRequirements.map((req, idx) => {
                const isCovered = req.status === 'COVERED';
                const isPartial = req.status === 'PARTIAL';
                const statusBadge = isCovered
                  ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                  : isPartial
                  ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                  : 'bg-rose-500/15 text-rose-400 border-rose-500/30';

                return (
                  <div key={idx} className="p-2.5 rounded-lg border border-border/60 bg-muted/20 space-y-1.5">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-[10px] font-bold text-foreground">{req.requirement_id}</span>
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-mono uppercase bg-muted/60 text-muted-foreground">
                          {req.category}
                        </span>
                        <span
                          className={`px-1.5 py-0.5 rounded text-[9px] font-mono uppercase ${
                            req.priority === 'CRITICAL'
                              ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30 font-semibold'
                              : 'bg-muted/60 text-muted-foreground'
                          }`}
                        >
                          {req.priority}
                        </span>
                      </div>
                      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-mono border ${statusBadge}`}>
                        {req.status}
                      </span>
                    </div>
                    <div className="text-[11px] font-medium text-foreground">{req.title}</div>
                    <p className="text-[11px] text-muted-foreground leading-relaxed">{req.expected_behavior}</p>
                    {req.evidence && req.evidence.length > 0 && (
                      <div className="text-[10px] font-mono text-muted-foreground/80 flex items-center gap-1 truncate">
                        <span className="text-primary">•</span>
                        <span className="truncate">{req.evidence[0]}</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* 5. Assumptions and Warnings (Collapsible)                      */}
      {/* -------------------------------------------------------------- */}
      {assumptions_and_warnings.length > 0 && (
        <div className="rounded-xl border border-border/80 bg-background/60 p-3 space-y-2 shadow-xs">
          <button
            type="button"
            onClick={() => setShowAssumptions(!showAssumptions)}
            className="w-full flex items-center justify-between text-left text-xs font-semibold text-foreground"
          >
            <div className="flex items-center gap-1.5">
              <Info className="h-3.5 w-3.5 text-primary" />
              <span>Assumptions &amp; Warnings ({assumptions_and_warnings.length})</span>
            </div>
            {showAssumptions ? (
              <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            )}
          </button>

          {showAssumptions && (
            <div className="space-y-1.5 pt-1 border-t border-border/40">
              {assumptions_and_warnings.map((note, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-2 p-2 rounded-lg bg-muted/15 border border-border/40 text-[11px] text-muted-foreground"
                >
                  <span className="text-primary font-mono text-[10px] mt-0.5">•</span>
                  <span className="leading-relaxed">{note}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* 6. Complete Generated Test File Preview                         */}
      {/* -------------------------------------------------------------- */}
      <div className="rounded-xl border border-border/80 bg-background/60 overflow-hidden shadow-xs space-y-0">
        {/* Code Preview Header with Actions */}
        <div className="p-3 bg-muted/30 border-b border-border/80 flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <FileCode className="h-4 w-4 text-emerald-400 shrink-0" />
            <div className="min-w-0">
              <div className="text-xs font-semibold text-foreground truncate font-mono">
                {downloadFilename}
              </div>
              <div className="text-[10px] text-muted-foreground font-mono">
                {lines.length} lines • {test_content.length} characters
              </div>
            </div>
          </div>

          {/* Action Buttons: Copy & Download */}
          <div className="flex items-center gap-1.5 shrink-0">
            {/* Copy Full Content Button */}
            <button
              type="button"
              onClick={handleCopy}
              disabled={!test_content}
              className={cn(
                'inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all shadow-xs disabled:opacity-50 disabled:pointer-events-none',
                copied
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : 'bg-card text-foreground border-border hover:bg-accent hover:border-border'
              )}
              title="Copy the complete generated test file to clipboard"
            >
              {copied ? (
                <>
                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                  <span>Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="h-3.5 w-3.5 text-muted-foreground" />
                  <span>Copy</span>
                </>
              )}
            </button>

            {/* Download Test File Button */}
            <button
              type="button"
              onClick={handleDownload}
              disabled={!test_content}
              className={cn(
                'inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all shadow-xs disabled:opacity-50 disabled:pointer-events-none',
                downloadSuccess
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : 'bg-primary text-primary-foreground border-primary hover:bg-primary/90'
              )}
              title="Download test file to your local computer"
            >
              {downloadSuccess ? (
                <>
                  <Check className="h-3.5 w-3.5" />
                  <span>Saved!</span>
                </>
              ) : (
                <>
                  <Download className="h-3.5 w-3.5" />
                  <span>Download</span>
                </>
              )}
            </button>
          </div>
        </div>

        {copyError && (
          <div className="p-2 bg-destructive/10 text-destructive text-[11px] border-b border-destructive/20 text-center">
            {copyError}
          </div>
        )}

        {/* Code Content View */}
        <div className="p-0 bg-muted/10 max-h-96 overflow-auto">
          {!test_content ? (
            <div className="p-6 text-center text-xs text-muted-foreground italic">
              No test code was returned by the generator.
            </div>
          ) : (
            <div className="flex font-mono text-[11px] leading-5 select-text py-2">
              {/* Line Numbers Gutter */}
              <div className="shrink-0 text-right text-muted-foreground/40 select-none bg-muted/5 border-r border-border/40 px-2.5">
                {lines.map((_, i) => (
                  <div key={i + 1}>{i + 1}</div>
                ))}
              </div>

              {/* Code Preformatted Text */}
              <pre className="flex-1 px-3 text-foreground whitespace-pre overflow-x-auto min-w-0 font-mono">
                <code>{test_content}</code>
              </pre>
            </div>
          )}
        </div>
      </div>

      {/* -------------------------------------------------------------- */}
      {/* 7. Source Citations (if present)                                */}
      {/* -------------------------------------------------------------- */}
      {sources.length > 0 && (
        <div className="pt-2 border-t border-border/60 space-y-1.5">
          <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            Analysis Context Sources ({sources.length}):
          </div>
          <div className="space-y-1">
            {sources.map((src, idx) => {
              const isSelected =
                activeSourceReference?.file_path === src.file_path &&
                activeSourceReference?.start_line === src.start_line;

              return (
                <button
                  key={idx}
                  type="button"
                  onClick={() => onSelectSourceReference?.(src)}
                  className={cn(
                    'w-full text-left p-2 rounded-lg border text-xs font-mono flex items-center justify-between gap-2 transition-colors cursor-pointer',
                    isSelected
                      ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                      : 'border-border/50 bg-muted/20 text-muted-foreground hover:bg-accent hover:border-border hover:text-foreground'
                  )}
                >
                  <span className="truncate" title={src.file_path}>
                    {src.file_path}
                    {src.symbol_name ? ` (${src.symbol_name})` : ''}
                  </span>
                  <span className="text-[10px] shrink-0 font-sans">
                    {typeof src.start_line === 'number' && typeof src.end_line === 'number'
                      ? `L${src.start_line}–${src.end_line}`
                      : 'File'}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
