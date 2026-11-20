import { useState, useMemo } from 'react';
import { Database, FileText, Code, Layers, Box, Search, X } from 'lucide-react';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { useRepositoryMetrics } from '../../hooks/useRepositories';
import type { Repository, RepositoryDependency } from '../../types/api';

export interface RepositoryMetricsSidebarProps {
  repo: Pick<Repository, 'file_count' | 'symbol_count' | 'chunk_count'>;
  /** Enables the language breakdown and top-symbol ranking from GET /repositories/:id/metrics. */
  repositoryId?: string;
  totalFiles?: number;
  dependencies?: RepositoryDependency[] | null;
  depsLoading: boolean;
  depsError: boolean;
}

export function RepositoryMetricsSidebar({
  repo,
  repositoryId,
  totalFiles,
  dependencies,
  depsLoading,
  depsError,
}: RepositoryMetricsSidebarProps) {
  const [dependencyFilter, setDependencyFilter] = useState('');
  const { data: metrics } = useRepositoryMetrics(repositoryId);

  // Filter dependencies
  const filteredDependencies = useMemo(() => {
    if (!dependencies) return [];
    if (!dependencyFilter.trim()) return dependencies;
    const q = dependencyFilter.toLowerCase();
    return dependencies.filter(
      (dep) => dep.name.toLowerCase().includes(q) || dep.ecosystem?.toLowerCase().includes(q)
    );
  }, [dependencies, dependencyFilter]);

  return (
    <div className="flex flex-col gap-3 min-h-0 h-full">
      {/* Box A: Quick Statistics */}
      <div className="shrink-0 rounded-xl border border-border bg-card shadow-sm p-3.5 space-y-3">
        <div className="flex items-center justify-between border-b border-border/60 pb-2">
          <span className="font-semibold text-xs text-foreground uppercase tracking-wider flex items-center gap-1.5">
            <Database className="h-3.5 w-3.5 text-primary" />
            Codebase Metrics
          </span>
          <span className="text-[10px] text-muted-foreground font-mono">Live Index</span>
        </div>

        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-lg bg-muted/20 border border-border/50 p-2">
            <div className="flex items-center justify-center gap-1 text-[11px] text-muted-foreground">
              <FileText className="h-3 w-3" />
              <span>Files</span>
            </div>
            <div className="font-bold text-base text-foreground mt-0.5">
              {repo.file_count ?? totalFiles ?? '-'}
            </div>
          </div>

          <div className="rounded-lg bg-muted/20 border border-border/50 p-2">
            <div className="flex items-center justify-center gap-1 text-[11px] text-muted-foreground">
              <Code className="h-3 w-3" />
              <span>Symbols</span>
            </div>
            <div className="font-bold text-base text-foreground mt-0.5">
              {repo.symbol_count ?? '-'}
            </div>
          </div>

          <div className="rounded-lg bg-muted/20 border border-border/50 p-2">
            <div className="flex items-center justify-center gap-1 text-[11px] text-muted-foreground">
              <Layers className="h-3 w-3" />
              <span>Chunks</span>
            </div>
            <div className="font-bold text-base text-foreground mt-0.5">
              {repo.chunk_count ?? '-'}
            </div>
          </div>
        </div>

        {metrics && metrics.languages.length > 0 && (
          <div className="space-y-1.5 pt-1" aria-label="Language breakdown">
            <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted">
              {metrics.languages.slice(0, 6).map((lang, i) => (
                <div
                  key={lang.language}
                  className={['bg-primary', 'bg-emerald-500', 'bg-amber-500', 'bg-sky-500', 'bg-fuchsia-500', 'bg-muted-foreground'][i]}
                  style={{ width: `${metrics.total_lines ? (lang.lines / metrics.total_lines) * 100 : 0}%` }}
                  title={`${lang.language}: ${lang.lines.toLocaleString()} lines`}
                />
              ))}
            </div>
            <ul className="space-y-0.5 text-[11px]">
              {metrics.languages.slice(0, 4).map((lang) => (
                <li key={lang.language} className="flex justify-between text-muted-foreground">
                  <span className="truncate">{lang.language === 'unknown' ? 'Other' : lang.language}</span>
                  <span className="font-mono">
                    {lang.files} files · {lang.lines.toLocaleString()} lines
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-[10px] text-muted-foreground font-mono">
              {metrics.total_lines.toLocaleString()} lines · {metrics.edge_count.toLocaleString()} graph edges
            </p>
          </div>
        )}

        {metrics && metrics.top_symbols.length > 0 && (
          <div className="space-y-1 pt-1 border-t border-border/60" aria-label="Most important symbols">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground pt-1.5">
              Key symbols (PageRank)
            </p>
            <ul className="space-y-0.5">
              {metrics.top_symbols.slice(0, 5).map((sym) => (
                <li key={sym.id} className="flex items-center justify-between gap-2 text-[11px]">
                  <span className="truncate font-mono text-foreground" title={sym.signature ?? sym.name}>
                    {sym.name}
                  </span>
                  <span className="text-muted-foreground shrink-0">{sym.kind}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Box B: Dependencies Explorer (Scrollable Box) */}
      <div className="flex-1 min-h-0 flex flex-col rounded-xl border border-border bg-card shadow-sm overflow-hidden">
        {/* Header */}
        <div className="bg-muted/30 px-3.5 py-2.5 border-b border-border flex items-center justify-between shrink-0">
          <span className="font-semibold text-xs text-foreground flex items-center gap-1.5">
            <Box className="h-3.5 w-3.5 text-primary" />
            Dependencies
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-primary/10 text-primary border border-primary/20">
            {dependencies?.length ?? 0}
          </span>
        </div>

        {/* Filter input */}
        <div className="p-2 border-b border-border/60 bg-background/50 shrink-0">
          <div className="relative flex items-center">
            <Search className="h-3 w-3 absolute left-2.5 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              value={dependencyFilter}
              onChange={(e) => setDependencyFilter(e.target.value)}
              placeholder="Filter dependencies…"
              className="w-full pl-7 pr-7 py-1 text-xs rounded-md bg-muted/20 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary transition-colors"
            />
            {dependencyFilter && (
              <button
                onClick={() => setDependencyFilter('')}
                className="absolute right-2 text-muted-foreground hover:text-foreground"
                aria-label="Clear filter"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>

        {/* Scrollable dependencies list */}
        <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-1.5">
          {depsLoading ? (
            <div className="flex justify-center py-8">
              <LoadingSpinner size="sm" label="Loading dependencies…" />
            </div>
          ) : depsError ? (
            <p className="text-xs text-destructive p-2">Failed to load dependencies.</p>
          ) : !dependencies || dependencies.length === 0 ? (
            <p className="text-xs text-muted-foreground italic p-2 text-center">
              No dependencies discovered in manifests.
            </p>
          ) : filteredDependencies.length === 0 ? (
            <p className="text-xs text-muted-foreground italic p-2 text-center">
              No dependencies matching "{dependencyFilter}".
            </p>
          ) : (
            filteredDependencies.map((dep, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between gap-2 p-2 rounded-lg border border-border/50 bg-background/40 hover:bg-accent/40 transition-colors"
              >
                <div className="min-w-0">
                  <p className="text-xs font-medium text-foreground truncate" title={dep.name}>
                    {dep.name}
                  </p>
                  <span className="text-[10px] text-muted-foreground uppercase font-mono">
                    {dep.ecosystem}
                  </span>
                </div>
                <span className="text-[11px] font-mono text-muted-foreground px-1.5 py-0.5 rounded bg-muted/40 border border-border/40 shrink-0">
                  {dep.version}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

