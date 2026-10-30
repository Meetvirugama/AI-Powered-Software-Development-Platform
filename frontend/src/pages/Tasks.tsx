import { useState, useMemo, useTransition } from 'react';
import { Link } from 'react-router-dom';
import {
  Plus,
  Search,
  Filter,
  RefreshCw,
  FolderGit2,
  ListTodo,
  X,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { useTasks } from '../hooks/useTasks';
import { useRepositories } from '../hooks/useRepositories';
import { TaskStatus } from '../types/task';
import { TaskCard } from '../components/tasks/TaskCard';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';

const ALL_STATUS_OPTIONS: TaskStatus[] = [
  TaskStatus.CREATED,
  TaskStatus.PLANNING,
  TaskStatus.PENDING_APPROVAL,
  TaskStatus.APPROVED,
  TaskStatus.REJECTED,
  TaskStatus.WORKSPACE_SETUP,
  TaskStatus.EXECUTING,
  TaskStatus.TESTING,
  TaskStatus.REPAIRING,
  TaskStatus.VERIFYING,
  TaskStatus.READY_FOR_PUBLICATION,
  TaskStatus.PUBLISHING,
  TaskStatus.DRAFT_PR_CREATED,
  TaskStatus.FAILED,
  TaskStatus.CANCELLED,
  TaskStatus.RECOVERY_REQUIRED,
  TaskStatus.BLOCKED,
];

export function Tasks() {
  const [searchInput, setSearchInput] = useState('');
  const [selectedStatus, setSelectedStatus] = useState<string>('ALL');
  const [selectedRepo, setSelectedRepo] = useState<string>('ALL');
  const [page, setPage] = useState(1);
  const pageSize = 12;

  const [, startTransition] = useTransition();

  // Query connected repositories for the filter dropdown
  const { data: repoData } = useRepositories(1, 100);

  // Query tasks with server/MSW filter params
  const {
    data: taskData,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useTasks({
    repository_id: selectedRepo !== 'ALL' ? selectedRepo : undefined,
    status: selectedStatus !== 'ALL' ? (selectedStatus as TaskStatus) : undefined,
    search: searchInput.trim() ? searchInput.trim() : undefined,
    page,
    page_size: pageSize,
  });

  const tasks = taskData?.items ?? [];
  const total = taskData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  // Extract known repositories for the filter dropdown
  const availableRepositories = useMemo(() => {
    const list: { id: string; name: string }[] = [];
    const seen = new Set<string>();

    if (repoData?.items) {
      for (const repo of repoData.items) {
        if (!seen.has(repo.id)) {
          seen.add(repo.id);
          list.push({ id: repo.id, name: repo.full_name || repo.name || repo.id });
        }
      }
    }

    // Also include any repository_ids from current tasks if not in list
    if (taskData?.items) {
      for (const t of taskData.items) {
        if (!seen.has(t.repository_id)) {
          seen.add(t.repository_id);
          list.push({ id: t.repository_id, name: t.repository_id });
        }
      }
    }

    return list;
  }, [repoData, taskData]);

  const hasActiveFilters = searchInput.trim() !== '' || selectedStatus !== 'ALL' || selectedRepo !== 'ALL';

  function handleResetFilters() {
    startTransition(() => {
      setSearchInput('');
      setSelectedStatus('ALL');
      setSelectedRepo('ALL');
      setPage(1);
    });
  }

  return (
    <div className="flex flex-col h-full space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Tasks</h1>
            {isFetching && !isLoading && (
              <RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" />
            )}
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            Autonomous software engineering tasks, structured plan review, human approvals and execution timelines.
          </p>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-md border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors disabled:opacity-50"
            title="Refresh tasks"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>

          <Link
            to="/app/tasks/new"
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-xs"
          >
            <Plus className="h-4 w-4" />
            <span>New Task</span>
          </Link>
        </div>
      </div>

      {/* Filters Toolbar */}
      <div className="rounded-lg border border-border bg-card p-4 shadow-xs space-y-3">
        <div className="flex flex-col md:flex-row items-stretch md:items-center gap-3">
          {/* Search Input */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              role="searchbox"
              placeholder="Search tasks by title, description or ID..."
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value);
                setPage(1);
              }}
              className="w-full pl-9 pr-8 py-2 text-sm bg-background border border-border rounded-md text-foreground placeholder:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            {searchInput && (
              <button
                onClick={() => setSearchInput('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Status Filter Dropdown */}
          <div className="flex items-center gap-2 min-w-[180px]">
            <Filter className="h-4 w-4 text-muted-foreground shrink-0 hidden sm:inline" />
            <select
              aria-label="Filter by Status"
              value={selectedStatus}
              onChange={(e) => {
                setSelectedStatus(e.target.value);
                setPage(1);
              }}
              className="w-full py-2 px-2.5 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="ALL">All Statuses</option>
              {ALL_STATUS_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {status.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </div>

          {/* Repository Filter Dropdown */}
          <div className="flex items-center gap-2 min-w-[180px]">
            <FolderGit2 className="h-4 w-4 text-muted-foreground shrink-0 hidden sm:inline" />
            <select
              aria-label="Filter by Repository"
              value={selectedRepo}
              onChange={(e) => {
                setSelectedRepo(e.target.value);
                setPage(1);
              }}
              className="w-full py-2 px-2.5 text-sm bg-background border border-border rounded-md text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="ALL">All Repositories</option>
              {availableRepositories.map((repo) => (
                <option key={repo.id} value={repo.id}>
                  {repo.name}
                </option>
              ))}
            </select>
          </div>

          {/* Reset Filters */}
          {hasActiveFilters && (
            <button
              onClick={handleResetFilters}
              className="inline-flex items-center justify-center gap-1 text-xs text-muted-foreground hover:text-foreground px-2 py-2 rounded border border-border/80 hover:bg-accent shrink-0 transition-colors"
            >
              <X className="h-3.5 w-3.5" />
              <span>Reset</span>
            </button>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 min-h-0">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-24">
            <LoadingSpinner size="lg" label="Loading tasks..." />
            <p className="mt-4 text-sm text-muted-foreground">Fetching workflow tasks...</p>
          </div>
        ) : isError ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-6 text-center space-y-4">
            <ErrorMessage error={error} />
            <div>
              <button
                onClick={() => refetch()}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-md bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Retry
              </button>
            </div>
          </div>
        ) : tasks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-12 text-center flex flex-col items-center justify-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground mb-4">
              <ListTodo className="h-6 w-6" />
            </div>
            <h3 className="text-base font-semibold text-foreground">No tasks found</h3>
            <p className="mt-1 text-sm text-muted-foreground max-w-sm">
              {hasActiveFilters
                ? 'No tasks match your active filter criteria. Try resetting your search or filter options.'
                : 'Get started by creating your first automated planning and implementation task.'}
            </p>
            <div className="mt-6 flex items-center gap-3">
              {hasActiveFilters ? (
                <button
                  onClick={handleResetFilters}
                  className="px-3.5 py-2 text-xs font-medium rounded-md border border-border bg-card text-foreground hover:bg-accent transition-colors"
                >
                  Clear Filters
                </button>
              ) : (
                <Link
                  to="/app/tasks/new"
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  <Plus className="h-4 w-4" />
                  Create Task
                </Link>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Task Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {tasks.map((task) => (
                <TaskCard key={task.task_id} task={task} />
              ))}
            </div>

            {/* Pagination Controls */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between border-t border-border pt-4 text-xs text-muted-foreground">
                <span>
                  Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total} tasks
                </span>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    aria-label="Previous Page"
                    className="p-1.5 rounded border border-border bg-card hover:bg-accent disabled:opacity-40 transition-colors"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <span className="font-mono">
                    Page {page} of {totalPages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                    aria-label="Next Page"
                    className="p-1.5 rounded border border-border bg-card hover:bg-accent disabled:opacity-40 transition-colors"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
