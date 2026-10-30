import { Link } from 'react-router-dom';
import {
  GitPullRequest,
  Clock,
  Layers,
  ChevronRight,
  FolderGit2,
  FileCode2,
  Wrench,
} from 'lucide-react';
import type { TaskDetailResponse } from '../../types/task';
import { TaskStatusBadge } from './TaskStatusBadge';
import { cn } from '../../lib/utils';

export interface TaskCardProps {
  task: TaskDetailResponse;
  className?: string;
}

function formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return dateStr;
  }
}

function formatRelativeTime(dateStr: string): string {
  try {
    const ms = Date.now() - new Date(dateStr).getTime();
    const minutes = Math.floor(ms / 60000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return dateStr;
  }
}

export function TaskCard({ task, className }: TaskCardProps) {
  const reqCount = task.requirements?.length ?? 0;

  return (
    <div
      data-testid={`task-card-${task.task_id}`}
      className={cn(
        'group relative flex flex-col justify-between rounded-lg border border-border bg-card p-5 shadow-xs transition-all hover:border-primary/40 hover:shadow-md',
        className
      )}
    >
      <div>
        {/* Top Header: Source, Repo & Status Badge */}
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
            <span className="inline-flex items-center gap-1 font-mono bg-accent/60 px-2 py-0.5 rounded text-[11px] text-foreground/80">
              <FolderGit2 className="h-3 w-3 text-primary shrink-0" />
              {task.repository_id}
            </span>

            {task.source?.type === 'GITHUB_ISSUE' && (
              <span className="inline-flex items-center gap-1 bg-primary/10 text-primary border border-primary/20 px-2 py-0.5 rounded text-[11px]">
                <GitPullRequest className="h-3 w-3 shrink-0" />
                Issue #{task.source.issue_number}
              </span>
            )}
            {task.source?.type === 'BUG_FINDING' && (
              <span className="inline-flex items-center gap-1 bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded text-[11px]">
                <FileCode2 className="h-3 w-3 shrink-0" />
                {task.source.finding_id || 'Bug Finding'}
              </span>
            )}
            {task.source?.type === 'USER_PROMPT' && (
              <span className="inline-flex items-center gap-1 bg-muted px-2 py-0.5 rounded text-[11px]">
                Prompt
              </span>
            )}
          </div>

          <TaskStatusBadge status={task.status} />
        </div>

        {/* Task Title (link to detail) */}
        <h3 className="text-base font-semibold text-foreground tracking-tight group-hover:text-primary transition-colors">
          <Link
            to={`/app/tasks/${task.task_id}`}
            className="focus:outline-none focus-visible:underline"
          >
            {task.title}
          </Link>
        </h3>

        {/* Description snippet */}
        {task.description && (
          <p className="mt-1.5 text-sm text-muted-foreground line-clamp-2 leading-relaxed">
            {task.description}
          </p>
        )}
      </div>

      {/* Footer Info & Metrics */}
      <div className="mt-4 pt-3 border-t border-border/60 flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
        <div className="flex items-center gap-3.5 flex-wrap">
          {/* Requirements count */}
          <span
            className="inline-flex items-center gap-1"
            title={`${reqCount} requirement(s)`}
          >
            <Layers className="h-3.5 w-3.5 text-muted-foreground/70 shrink-0" />
            <span>
              {reqCount} {reqCount === 1 ? 'req' : 'reqs'}
            </span>
          </span>

          {/* Plan version */}
          <span className="inline-flex items-center gap-1 font-mono">
            <span>v{task.plan_version}</span>
            {task.approved_plan_version && (
              <span className="text-emerald-400 text-[10px] bg-emerald-500/10 px-1 rounded">
                (approved)
              </span>
            )}
          </span>

          {/* Repair attempts indicator if used */}
          {task.repair_attempts_used > 0 && (
            <span
              className="inline-flex items-center gap-1 text-amber-400 font-mono text-[11px]"
              title={`Repair attempts: ${task.repair_attempts_used} of ${task.repair_attempts_max}`}
            >
              <Wrench className="h-3 w-3 shrink-0" />
              {task.repair_attempts_used}/{task.repair_attempts_max}
            </span>
          )}

          {/* Created date */}
          <span
            className="inline-flex items-center gap-1"
            title={`Created ${formatDate(task.created_at)}`}
          >
            <Clock className="h-3.5 w-3.5 text-muted-foreground/70 shrink-0" />
            <span>{formatRelativeTime(task.updated_at || task.created_at)}</span>
          </span>
        </div>

        {/* Detail link */}
        <Link
          to={`/app/tasks/${task.task_id}`}
          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline shrink-0"
        >
          View Plan
          <ChevronRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>
    </div>
  );
}
