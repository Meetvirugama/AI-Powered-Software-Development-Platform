import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  GitPullRequest,
  Search,
  FolderGit2,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  ArrowRight,
  Filter,
} from 'lucide-react';
import { useRepositories } from '../../hooks/useRepositories';
import { useRepositoryIssues, useImportIssue } from '../../hooks/useTasks';
import type { GitHubIssue } from '../../types/task';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { ErrorMessage } from '../shared/ErrorMessage';
import { cn } from '../../lib/utils';

export function ImportIssueForm() {
  const navigate = useNavigate();

  // Load repositories for selector
  const { data: repoData } = useRepositories(1, 100);

  // Selected repository state
  const [selectedRepoId, setSelectedRepoId] = useState<string>('');
  const activeRepoId = selectedRepoId || repoData?.items?.[0]?.id || 'repo-1';

  // Issue state filter and search
  const [issueState, setIssueState] = useState<'open' | 'closed' | 'all'>('open');
  const [issueSearch, setIssueSearch] = useState('');

  // Selected issue for preview and import
  const [selectedIssueNumber, setSelectedIssueNumber] = useState<number | null>(null);

  // Query issues for the active repository
  const {
    data: issuesData,
    isLoading: isLoadingIssues,
    isError: isIssuesError,
    error: issuesError,
  } = useRepositoryIssues(activeRepoId, {
    state: issueState,
    page: 1,
    page_size: 50,
  });

  const issuesList = issuesData?.items;

  // Filter issues by search term client-side
  const filteredIssues = useMemo(() => {
    if (!issuesList) return [];
    if (!issueSearch.trim()) return issuesList;
    const term = issueSearch.toLowerCase().trim();
    return issuesList.filter(
      (issue) =>
        issue.title.toLowerCase().includes(term) ||
        issue.issue_number.toString().includes(term) ||
        issue.labels.some((l) => l.toLowerCase().includes(term))
    );
  }, [issuesList, issueSearch]);

  // Find currently selected issue details
  const selectedIssue = useMemo<GitHubIssue | undefined>(() => {
    if (selectedIssueNumber === null || !issuesList) return undefined;
    return issuesList.find((i) => i.issue_number === selectedIssueNumber);
  }, [issuesList, selectedIssueNumber]);

  // Import mutation hook
  const importMutation = useImportIssue(activeRepoId);

  async function handleImport() {
    if (!selectedIssueNumber) return;
    if (selectedIssue?.is_imported) return;

    try {
      const res = await importMutation.mutateAsync({
        issue_number: selectedIssueNumber,
      });
      navigate(`/app/tasks/${res.task_id}`);
    } catch {
      // Handled by mutation error state
    }
  }

  return (
    <div className="space-y-6">
      {/* Backend / Mutation Error */}
      {importMutation.isError && <ErrorMessage error={importMutation.error} />}

      {/* ------------------------------------------------------------------ */}
      {/* 1. Repository Selection Bar                                         */}
      {/* ------------------------------------------------------------------ */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-4 shadow-xs">
        <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
          <FolderGit2 className="h-4 w-4 text-primary" />
          Select GitHub Repository
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-foreground mb-1">
              Connected Repository
            </label>
            {repoData?.items && repoData.items.length > 0 ? (
              <select
                aria-label="Select Repository"
                value={activeRepoId}
                onChange={(e) => {
                  setSelectedRepoId(e.target.value);
                  setSelectedIssueNumber(null);
                }}
                className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {repoData.items.map((repo) => (
                  <option key={repo.id} value={repo.id}>
                    {repo.full_name || repo.name}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                placeholder="Repository ID (e.g. repo-1)"
                value={activeRepoId}
                onChange={(e) => {
                  setSelectedRepoId(e.target.value);
                  setSelectedIssueNumber(null);
                }}
                className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-foreground mb-1">
              Issue State Filter
            </label>
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground shrink-0 hidden sm:inline" />
              <select
                aria-label="Filter Issue State"
                value={issueState}
                onChange={(e) => {
                  setIssueState(e.target.value as 'open' | 'closed' | 'all');
                  setSelectedIssueNumber(null);
                }}
                className="w-full py-2 px-3 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="open">Open Issues</option>
                <option value="closed">Closed Issues</option>
                <option value="all">All Issues</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* 2. Issue Search and Selection Grid                                  */}
      {/* ------------------------------------------------------------------ */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Issues List */}
        <div className="lg:col-span-7 space-y-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search issues by title, #number, or label..."
              value={issueSearch}
              onChange={(e) => setIssueSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm bg-background border border-border rounded-md text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="rounded-lg border border-border bg-card p-2 min-h-[350px] max-h-[500px] overflow-y-auto space-y-1.5">
            {isLoadingIssues ? (
              <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
                <LoadingSpinner size="md" label="Loading issues..." />
                <p className="mt-2 text-xs">Fetching repository issues from GitHub...</p>
              </div>
            ) : isIssuesError ? (
              <div className="p-4 text-center">
                <ErrorMessage error={issuesError} />
              </div>
            ) : filteredIssues.length === 0 ? (
              <div className="py-16 text-center text-muted-foreground">
                <GitPullRequest className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p className="text-sm font-medium">No issues found</p>
                <p className="text-xs mt-1">
                  {issueSearch
                    ? 'No issues match your search criteria.'
                    : 'No issues match the selected repository and filter.'}
                </p>
              </div>
            ) : (
              filteredIssues.map((issue) => {
                const isSelected = selectedIssueNumber === issue.issue_number;
                return (
                  <button
                    key={issue.issue_number}
                    type="button"
                    onClick={() => setSelectedIssueNumber(issue.issue_number)}
                    className={cn(
                      'w-full text-left p-3 rounded-md border transition-all text-sm flex flex-col gap-1.5 focus:outline-none',
                      isSelected
                        ? 'border-primary bg-primary/10 shadow-xs'
                        : 'border-border/60 bg-background/50 hover:bg-accent/60 hover:border-border'
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs font-semibold text-primary">
                          #{issue.issue_number}
                        </span>
                        <span
                          className={cn(
                            'text-[10px] uppercase font-mono px-1.5 py-0.5 rounded border',
                            issue.state === 'open'
                              ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                              : 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20'
                          )}
                        >
                          {issue.state}
                        </span>
                      </div>

                      {issue.is_imported && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
                          <CheckCircle2 className="h-3 w-3 shrink-0" />
                          Imported
                        </span>
                      )}
                    </div>

                    <p className="font-medium text-foreground line-clamp-1">{issue.title}</p>

                    <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
                      <span>by @{issue.author}</span>
                      {issue.labels.length > 0 && (
                        <div className="flex items-center gap-1 flex-wrap">
                          {issue.labels.slice(0, 3).map((lbl) => (
                            <span
                              key={lbl}
                              className="text-[10px] bg-muted px-1.5 py-0.2 rounded font-mono"
                            >
                              {lbl}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Selected Issue Preview Card */}
        <div className="lg:col-span-5">
          <div className="rounded-lg border border-border bg-card p-5 shadow-xs sticky top-4 flex flex-col justify-between min-h-[350px]">
            {selectedIssue ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between border-b border-border pb-3">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-bold text-primary">
                      #{selectedIssue.issue_number}
                    </span>
                    <span
                      className={cn(
                        'text-xs font-mono uppercase px-2 py-0.5 rounded border',
                        selectedIssue.state === 'open'
                          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                          : 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20'
                      )}
                    >
                      {selectedIssue.state}
                    </span>
                  </div>

                  {selectedIssue.url && (
                    <a
                      href={selectedIssue.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors"
                    >
                      <span>View on GitHub</span>
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>

                <div>
                  <h3 className="text-base font-semibold text-foreground">
                    {selectedIssue.title}
                  </h3>
                  <p className="text-xs text-muted-foreground mt-1">
                    Opened by <span className="font-medium text-foreground">@{selectedIssue.author}</span>
                  </p>
                </div>

                {selectedIssue.labels.length > 0 && (
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-1">Labels:</h4>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedIssue.labels.map((label) => (
                        <span
                          key={label}
                          className="text-xs bg-accent text-accent-foreground px-2 py-0.5 rounded border border-border font-mono"
                        >
                          {label}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <h4 className="text-xs font-medium text-muted-foreground mb-1">Issue Body:</h4>
                  <div className="p-3 rounded-md bg-background border border-border text-xs text-muted-foreground max-h-48 overflow-y-auto whitespace-pre-wrap leading-relaxed font-sans">
                    {selectedIssue.body || 'No description provided.'}
                  </div>
                </div>

                {selectedIssue.is_imported && (
                  <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-400 flex items-center gap-2">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    <span>This issue has already been imported into an active task.</span>
                  </div>
                )}

                <div className="pt-4 border-t border-border">
                  <button
                    type="button"
                    onClick={handleImport}
                    disabled={
                      selectedIssue.is_imported ||
                      importMutation.isPending ||
                      !selectedIssueNumber
                    }
                    className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 text-xs font-semibold rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-xs disabled:opacity-50"
                  >
                    {importMutation.isPending ? (
                      <>
                        <LoadingSpinner size="sm" label="Importing issue..." />
                        <span>Importing Issue...</span>
                      </>
                    ) : (
                      <>
                        <span>Import Issue as Task</span>
                        <ArrowRight className="h-3.5 w-3.5" />
                      </>
                    )}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-20 text-center text-muted-foreground">
                <GitPullRequest className="h-10 w-10 mb-3 opacity-40 text-primary" />
                <p className="text-sm font-medium text-foreground">Select an issue to preview</p>
                <p className="text-xs mt-1 max-w-xs">
                  Choose a candidate GitHub issue from the list on the left to preview its content and convert it into an automated task.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
