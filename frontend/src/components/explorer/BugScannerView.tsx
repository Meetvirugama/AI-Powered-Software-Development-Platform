import { useState, useMemo } from 'react';
import {
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
  ShieldCheck,
  Check,
  HelpCircle,
  FileCode,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type {
  BugDetectionResponse,
  FindingSeverity,
  FindingSourceType,
  SourceReference,
} from '../../types/analysis';

export interface BugScannerViewProps {
  result: BugDetectionResponse;
  onSelectSourceReference?: (source: SourceReference) => void;
  activeSourceReference?: SourceReference | null;
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
    pillClass: 'hover:bg-rose-500/20 data-[active=true]:bg-rose-500/25 data-[active=true]:text-rose-300 data-[active=true]:border-rose-500/50',
    textClass: 'text-rose-400',
    borderClass: 'border-l-rose-500',
  },
  HIGH: {
    label: 'High',
    icon: ShieldAlert,
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    pillClass: 'hover:bg-amber-500/20 data-[active=true]:bg-amber-500/25 data-[active=true]:text-amber-300 data-[active=true]:border-amber-500/50',
    textClass: 'text-amber-400',
    borderClass: 'border-l-amber-500',
  },
  MEDIUM: {
    label: 'Medium',
    icon: AlertTriangle,
    badgeClass: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
    pillClass: 'hover:bg-yellow-500/20 data-[active=true]:bg-yellow-500/25 data-[active=true]:text-yellow-300 data-[active=true]:border-yellow-500/50',
    textClass: 'text-yellow-400',
    borderClass: 'border-l-yellow-500',
  },
  LOW: {
    label: 'Low',
    icon: Info,
    badgeClass: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    pillClass: 'hover:bg-blue-500/20 data-[active=true]:bg-blue-500/25 data-[active=true]:text-blue-300 data-[active=true]:border-blue-500/50',
    textClass: 'text-blue-400',
    borderClass: 'border-l-blue-500',
  },
  INFO: {
    label: 'Info',
    icon: Info,
    badgeClass: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
    pillClass: 'hover:bg-slate-500/20 data-[active=true]:bg-slate-500/25 data-[active=true]:text-slate-300 data-[active=true]:border-slate-500/50',
    textClass: 'text-slate-400',
    borderClass: 'border-l-slate-400',
  },
};

const SOURCE_TYPE_CONFIG: Record<
  FindingSourceType,
  {
    label: string;
    icon: typeof Cpu;
    className: string;
    description: string;
  }
> = {
  STATIC: {
    label: 'Static Rule',
    icon: Cpu,
    className: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
    description: 'Detected deterministically by static analyzer / AST pattern',
  },
  AI: {
    label: 'AI Reasoning',
    icon: Sparkles,
    className: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
    description: 'Inferred via AI defect analysis and semantic reasoning',
  },
  COMBINED: {
    label: 'Static + AI',
    icon: ShieldAlert,
    className: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/40 font-semibold',
    description: 'Corroborated by both static rules and AI validation (High Confidence)',
  },
};

function formatCategory(category: string): string {
  const map: Record<string, string> = {
    off_by_one: 'Off-by-One',
    null_safety: 'Null Safety',
    unhandled_exception: 'Unhandled Exception',
    boundary_condition: 'Boundary Condition',
    resource_leak: 'Resource Leak',
    race_condition: 'Race Condition',
    logic_error: 'Logic Error',
    security: 'Security',
    other: 'Code Smell',
  };
  return map[category] || category.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function BugScannerView({
  result,
  onSelectSourceReference,
  activeSourceReference,
  className,
}: BugScannerViewProps) {
  const [selectedSeverity, setSelectedSeverity] = useState<FindingSeverity | 'ALL'>('ALL');
  const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
  const [selectedFile, setSelectedFile] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [expandedFindings, setExpandedFindings] = useState<Record<string, boolean>>(() => {
    // Default open first 3 findings
    const initial: Record<string, boolean> = {};
    (result.findings || []).slice(0, 3).forEach((f) => {
      initial[f.id] = true;
    });
    return initial;
  });

  const findings = useMemo(() => result.findings || [], [result.findings]);

  // Severity counts based on full results
  const severityCounts = useMemo(() => {
    const counts: Record<FindingSeverity, number> = {
      CRITICAL: 0,
      HIGH: 0,
      MEDIUM: 0,
      LOW: 0,
      INFO: 0,
    };
    for (const f of findings) {
      if (counts[f.severity] !== undefined) {
        counts[f.severity]++;
      }
    }
    return counts;
  }, [findings]);

  // Unique categories in current findings
  const availableCategories = useMemo(() => {
    const cats = new Set<string>();
    for (const f of findings) {
      if (f.category) cats.add(f.category);
    }
    return Array.from(cats).sort();
  }, [findings]);

  // Unique files cited in current findings
  const availableFiles = useMemo(() => {
    const files = new Set<string>();
    for (const f of findings) {
      if (f.source_reference?.file_path) {
        files.add(f.source_reference.file_path);
      }
    }
    return Array.from(files).sort();
  }, [findings]);

  // Filtered findings based on user selection
  const filteredFindings = useMemo(() => {
    return findings.filter((f) => {
      if (selectedSeverity !== 'ALL' && f.severity !== selectedSeverity) {
        return false;
      }
      if (selectedCategory !== 'ALL' && f.category !== selectedCategory) {
        return false;
      }
      if (selectedFile !== 'ALL' && f.source_reference?.file_path !== selectedFile) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesTitle = f.title.toLowerCase().includes(q);
        const matchesDesc = f.description.toLowerCase().includes(q);
        const matchesEvidence = f.evidence?.toLowerCase().includes(q);
        const matchesRule = f.rule_id?.toLowerCase().includes(q);
        if (!matchesTitle && !matchesDesc && !matchesEvidence && !matchesRule) {
          return false;
        }
      }
      return true;
    });
  }, [findings, selectedSeverity, selectedCategory, selectedFile, searchQuery]);

  function toggleExpand(id: string) {
    setExpandedFindings((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  }

  function handleResetFilters() {
    setSelectedSeverity('ALL');
    setSelectedCategory('ALL');
    setSelectedFile('ALL');
    setSearchQuery('');
  }

  const hasActiveFilters =
    selectedSeverity !== 'ALL' ||
    selectedCategory !== 'ALL' ||
    selectedFile !== 'ALL' ||
    searchQuery.trim() !== '';

  return (
    <div className={cn('space-y-4 animate-in fade-in duration-200', className)}>
      {/* -------------------------------------------------------------- */}
      {/* Top Banner: Metrics & Engine Origin Summary                     */}
      {/* -------------------------------------------------------------- */}
      <div className="rounded-xl border border-border/80 bg-background/60 p-3.5 space-y-3 shadow-xs">
        <div className="flex items-center justify-between gap-2 border-b border-border/60 pb-2.5">
          <div className="flex items-center gap-2">
            <div className="h-7 w-7 rounded-lg bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-400">
              <ShieldAlert className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-foreground">Defect Scanner Report</h3>
              <p className="text-[10px] text-muted-foreground font-mono">
                Run ID: {result.run_id.slice(0, 8)} · Status:{' '}
                <span className="text-emerald-400 font-medium">{result.status}</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 text-[10px] font-mono">
            <span className="px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-primary font-semibold">
              {result.total_findings} {result.total_findings === 1 ? 'Finding' : 'Findings'}
            </span>
          </div>
        </div>

        {/* Engine Origin Counts */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
          <div className="rounded-lg bg-muted/20 border border-border/50 p-2 flex items-center gap-2">
            <Cpu className="h-3.5 w-3.5 text-sky-400 shrink-0" />
            <div className="min-w-0">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-mono">Static Rules</div>
              <div className="font-bold text-foreground text-xs mt-0.5">
                {result.static_findings_count} {result.static_findings_count === 1 ? 'rule' : 'rules'}
              </div>
            </div>
          </div>

          <div className="rounded-lg bg-muted/20 border border-border/50 p-2 flex items-center gap-2">
            <Sparkles className="h-3.5 w-3.5 text-purple-400 shrink-0" />
            <div className="min-w-0">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-mono">AI Reasoning</div>
              <div className="font-bold text-foreground text-xs mt-0.5">
                {result.ai_findings_count} {result.ai_findings_count === 1 ? 'defect' : 'defects'}
              </div>
            </div>
          </div>

          <div className="rounded-lg bg-muted/20 border border-border/50 p-2 flex items-center gap-2 col-span-2 sm:col-span-1">
            <Code2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
            <div className="min-w-0">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-mono">Target Scope</div>
              <div className="font-bold text-foreground text-xs mt-0.5 truncate" title={result.target.path}>
                {result.target.type === 'symbol' && result.target.symbol
                  ? result.target.symbol
                  : result.target.type === 'range' && result.target.start_line
                  ? `L${result.target.start_line}–${result.target.end_line}`
                  : 'Full File'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* -------------------------------------------------------------- */}
      {/* Missing Context Warnings (if any)                              */}
      {/* -------------------------------------------------------------- */}
      {result.missing_context && result.missing_context.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 space-y-1.5 text-xs text-amber-300">
          <div className="flex items-center gap-1.5 font-semibold text-[11px] uppercase tracking-wider">
            <Info className="h-3.5 w-3.5 text-amber-400 shrink-0" />
            <span>Analysis Scope Warnings ({result.missing_context.length}):</span>
          </div>
          <ul className="list-disc list-inside space-y-0.5 text-[11px] text-muted-foreground font-mono pl-1">
            {result.missing_context.map((msg, i) => (
              <li key={i}>{msg}</li>
            ))}
          </ul>
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Zero Findings Success State                                    */}
      {/* -------------------------------------------------------------- */}
      {findings.length === 0 && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-6 text-center space-y-3">
          <div className="h-12 w-12 rounded-full bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 flex items-center justify-center mx-auto shadow-xs">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div className="space-y-1 max-w-sm mx-auto">
            <h4 className="text-sm font-semibold text-emerald-300">Clean Scan: No Bugs Detected</h4>
            <p className="text-xs text-muted-foreground leading-relaxed">
              No defect patterns, off-by-one errors, null dereferences, or dangerous patterns were identified in{' '}
              <span className="font-mono text-foreground font-medium">{result.target.path}</span>.
            </p>
          </div>
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-[10px] font-mono text-emerald-300">
            <Check className="h-3 w-3" />
            <span>Verified with static analyzers and AI reasoning</span>
          </div>
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Filters Bar (Only shown when findings exist)                   */}
      {/* -------------------------------------------------------------- */}
      {findings.length > 0 && (
        <div className="space-y-2.5">
          {/* Severity Pills */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs">
            <button
              type="button"
              data-active={selectedSeverity === 'ALL'}
              onClick={() => setSelectedSeverity('ALL')}
              className={cn(
                'inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border text-xs font-mono transition-all shrink-0',
                selectedSeverity === 'ALL'
                  ? 'bg-primary/20 text-primary border-primary font-semibold shadow-xs'
                  : 'bg-muted/20 border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/40'
              )}
            >
              <span>All</span>
              <span className="text-[10px] px-1 rounded bg-background/60 border border-border/40">
                {findings.length}
              </span>
            </button>

            {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'] as FindingSeverity[]).map((sev) => {
              const cfg = SEVERITY_CONFIG[sev];
              const count = severityCounts[sev];
              const isActive = selectedSeverity === sev;
              const Icon = cfg.icon;

              return (
                <button
                  key={sev}
                  type="button"
                  data-active={isActive}
                  onClick={() => setSelectedSeverity((prev) => (prev === sev ? 'ALL' : sev))}
                  className={cn(
                    'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-medium transition-all shrink-0 font-mono',
                    isActive
                      ? cfg.badgeClass + ' font-semibold shadow-xs ring-1 ring-ring/40'
                      : count > 0
                      ? 'border-border/60 bg-muted/20 text-muted-foreground hover:text-foreground hover:bg-muted/40'
                      : 'border-border/30 bg-muted/5 text-muted-foreground/50 opacity-60'
                  )}
                  title={`Filter by ${cfg.label} severity (${count} findings)`}
                >
                  <Icon className={cn('h-3 w-3', cfg.textClass)} />
                  <span>{cfg.label}</span>
                  <span className="text-[10px] px-1 rounded bg-background/50 border border-border/40">
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Search & Category / File Dropdowns */}
          <div className="grid grid-cols-1 sm:grid-cols-12 gap-2 text-xs">
            {/* Search Input */}
            <div className="sm:col-span-6 relative flex items-center">
              <Search className="h-3 w-3 absolute left-2.5 text-muted-foreground pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search findings, rules, evidence…"
                className="w-full pl-7 pr-7 py-1.5 text-xs rounded-lg bg-muted/20 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary transition-colors font-mono"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 text-muted-foreground hover:text-foreground"
                  aria-label="Clear search"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>

            {/* Category Dropdown */}
            <div className="sm:col-span-3">
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="w-full py-1.5 px-2 text-xs rounded-lg bg-muted/20 border border-border text-foreground focus:outline-none focus:border-primary transition-colors truncate font-mono"
                aria-label="Filter by category"
              >
                <option value="ALL">All Categories ({availableCategories.length})</option>
                {availableCategories.map((cat) => (
                  <option key={cat} value={cat}>
                    {formatCategory(cat)}
                  </option>
                ))}
              </select>
            </div>

            {/* File Dropdown */}
            <div className="sm:col-span-3">
              <select
                value={selectedFile}
                onChange={(e) => setSelectedFile(e.target.value)}
                className="w-full py-1.5 px-2 text-xs rounded-lg bg-muted/20 border border-border text-foreground focus:outline-none focus:border-primary transition-colors truncate font-mono"
                aria-label="Filter by file"
              >
                <option value="ALL">All Files ({availableFiles.length})</option>
                {availableFiles.map((f) => (
                  <option key={f} value={f}>
                    {f.split('/').pop() || f}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Active Filter Indicator & Reset */}
          {hasActiveFilters && (
            <div className="flex items-center justify-between text-[11px] text-muted-foreground px-1">
              <span>
                Showing <strong className="text-foreground">{filteredFindings.length}</strong> of{' '}
                {findings.length} findings
              </span>
              <button
                type="button"
                onClick={handleResetFilters}
                className="text-primary hover:underline inline-flex items-center gap-1 font-mono"
              >
                <Filter className="h-2.5 w-2.5" />
                <span>Reset filters</span>
              </button>
            </div>
          )}
        </div>
      )}

      {/* -------------------------------------------------------------- */}
      {/* Findings List                                                  */}
      {/* -------------------------------------------------------------- */}
      {findings.length > 0 && (
        <div className="space-y-3">
          {filteredFindings.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-6 text-center space-y-2">
              <p className="text-xs text-muted-foreground">
                No findings match your active filters.
              </p>
              <button
                type="button"
                onClick={handleResetFilters}
                className="text-xs font-medium text-primary hover:underline font-mono"
              >
                Clear all filters
              </button>
            </div>
          ) : (
            filteredFindings.map((finding) => {
              const sevCfg = SEVERITY_CONFIG[finding.severity] || SEVERITY_CONFIG.LOW;
              const originCfg = SOURCE_TYPE_CONFIG[finding.source_type] || SOURCE_TYPE_CONFIG.AI;
              const isExpanded = Boolean(expandedFindings[finding.id]);
              const SevIcon = sevCfg.icon;
              const OriginIcon = originCfg.icon;

              const hasLines =
                typeof finding.source_reference?.start_line === 'number' &&
                typeof finding.source_reference?.end_line === 'number';

              const isCitedActive =
                Boolean(activeSourceReference) &&
                activeSourceReference?.file_path === finding.source_reference?.file_path &&
                activeSourceReference?.start_line === finding.source_reference?.start_line;

              return (
                <div
                  key={finding.id}
                  className={cn(
                    'rounded-xl border bg-card/60 backdrop-blur-xs transition-all overflow-hidden shadow-xs border-l-4',
                    sevCfg.borderClass,
                    isCitedActive
                      ? 'border-cyan-400 ring-2 ring-cyan-500/30'
                      : 'border-border/80 hover:border-border'
                  )}
                >
                  {/* Card Header (Clickable to toggle expand) */}
                  <div
                    onClick={() => toggleExpand(finding.id)}
                    className="p-3 cursor-pointer hover:bg-muted/15 transition-colors space-y-2"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                        {/* Severity Badge */}
                        <span
                          className={cn(
                            'inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[10px] font-bold font-mono uppercase tracking-wider',
                            sevCfg.badgeClass
                          )}
                        >
                          <SevIcon className="h-3 w-3" />
                          <span>{finding.severity}</span>
                        </span>

                        {/* Origin Badge */}
                        <span
                          className={cn(
                            'inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[10px] font-mono',
                            originCfg.className
                          )}
                          title={originCfg.description}
                        >
                          <OriginIcon className="h-3 w-3" />
                          <span>{originCfg.label}</span>
                        </span>

                        {/* Rule ID Tag (if available) */}
                        {finding.rule_id && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted/40 border border-border/50 text-[10px] font-mono text-muted-foreground">
                            <span>#{finding.rule_id}</span>
                          </span>
                        )}

                        {/* Category */}
                        <span className="text-[10px] text-muted-foreground font-mono bg-muted/20 px-1.5 py-0.5 rounded border border-border/40">
                          {formatCategory(finding.category)}
                        </span>

                        {/* Uncertainty Badge */}
                        {finding.is_uncertain && (
                          <span
                            className="inline-flex items-center gap-0.5 text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/25"
                            title="Conclusion is uncertain; runtime verification recommended."
                          >
                            <HelpCircle className="h-2.5 w-2.5" />
                            <span>Uncertain</span>
                          </span>
                        )}
                      </div>

                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleExpand(finding.id);
                        }}
                        className="text-muted-foreground hover:text-foreground p-0.5 shrink-0"
                        aria-label={isExpanded ? 'Collapse finding' : 'Expand finding'}
                      >
                        {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      </button>
                    </div>

                    {/* Title */}
                    <h4 className="text-xs font-semibold text-foreground tracking-tight leading-snug">
                      {finding.title}
                    </h4>

                    {/* Source Reference & Line Range Navigation */}
                    {finding.source_reference?.file_path && (
                      <div className="flex items-center justify-between gap-2 pt-1 border-t border-border/40 text-[11px] font-mono">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (finding.source_reference && onSelectSourceReference) {
                              onSelectSourceReference(finding.source_reference);
                            }
                          }}
                          className={cn(
                            'inline-flex items-center gap-1.5 text-left text-[11px] font-mono transition-colors rounded hover:underline cursor-pointer truncate max-w-full',
                            hasLines ? 'text-primary hover:text-primary/90' : 'text-muted-foreground'
                          )}
                          title={
                            hasLines
                              ? `Navigate to ${finding.source_reference.file_path}: Lines ${finding.source_reference.start_line}-${finding.source_reference.end_line}`
                              : `Source file: ${finding.source_reference.file_path}`
                          }
                        >
                          <FileCode className="h-3 w-3 shrink-0" />
                          <span className="truncate">{finding.source_reference.file_path}</span>
                          {hasLines && (
                            <span className="text-[10px] px-1 py-0.2 rounded bg-primary/10 border border-primary/20 shrink-0">
                              L{finding.source_reference.start_line}–{finding.source_reference.end_line}
                            </span>
                          )}
                        </button>

                        {finding.confidence && (
                          <span className="text-[10px] text-muted-foreground font-mono shrink-0 hidden sm:inline">
                            Confidence:{' '}
                            <span className="text-foreground capitalize">{finding.confidence}</span>
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Card Body (Expanded Details) */}
                  {isExpanded && (
                    <div className="px-3.5 pb-3.5 pt-1 space-y-3 text-xs border-t border-border/50 bg-background/40">
                      {/* Description */}
                      <div className="space-y-1">
                        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider font-mono">
                          Description & Impact:
                        </span>
                        <p className="text-xs text-foreground/90 leading-relaxed font-sans">
                          {finding.description}
                        </p>
                      </div>

                      {/* Code Evidence */}
                      {finding.evidence && (
                        <div className="space-y-1">
                          <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider font-mono">
                            Supporting Evidence:
                          </span>
                          <div className="rounded-lg bg-black/40 border border-border/70 p-2.5 font-mono text-[11px] overflow-x-auto text-amber-300 whitespace-pre leading-relaxed select-text">
                            {finding.evidence}
                          </div>
                        </div>
                      )}

                      {/* Suggested Fix / Remediation */}
                      {finding.suggested_fix ? (
                        <div className="space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider font-mono flex items-center gap-1">
                              <CheckCircle2 className="h-3 w-3" />
                              Suggested Remediation:
                            </span>
                            <span className="text-[9px] text-muted-foreground font-mono italic">
                              Review before applying
                            </span>
                          </div>
                          <div className="rounded-lg bg-emerald-950/25 border border-emerald-500/30 p-2.5 font-mono text-[11px] overflow-x-auto text-emerald-300 whitespace-pre leading-relaxed select-text">
                            {finding.suggested_fix}
                          </div>
                        </div>
                      ) : (
                        <p className="text-[10px] text-muted-foreground/80 italic font-mono">
                          Remediation: No automated fix suggested. Manual code refactoring recommended.
                        </p>
                      )}

                      {/* Uncertainty Note */}
                      {finding.is_uncertain && (
                        <div className="rounded-lg bg-amber-500/10 border border-amber-500/25 p-2 text-[11px] text-amber-300 flex items-start gap-1.5">
                          <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-400" />
                          <span>
                            This finding was identified based on pattern heuristics. Confirm whether surrounding runtime preconditions or framework guards mitigate this defect.
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
