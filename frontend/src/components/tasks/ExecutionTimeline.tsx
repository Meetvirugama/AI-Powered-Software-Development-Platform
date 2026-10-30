import type { ReactNode } from 'react';
import {
  CircleDot,
  Brain,
  RefreshCw,
  CheckCircle2,
  XCircle,
  FolderGit2,
  Play,
  TestTube2,
  Wrench,
  ShieldCheck,
  Send,
  UploadCloud,
  GitPullRequest,
  AlertTriangle,
  Slash,
  Clock,
  Activity,
} from 'lucide-react';
import { useTaskEvents } from '../../hooks/useTasks';
import type { TaskEvent } from '../../types/task';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { ErrorMessage } from '../shared/ErrorMessage';
import { cn } from '../../lib/utils';

export interface ExecutionTimelineProps {
  taskId: string;
  className?: string;
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

function getEventIcon(eventType: string): { icon: ReactNode; bgClass: string; textClass: string } {
  switch (eventType) {
    case 'TASK_CREATED':
      return {
        icon: <CircleDot className="h-3.5 w-3.5" />,
        bgClass: 'bg-slate-500/10 border-slate-500/20',
        textClass: 'text-slate-400',
      };
    case 'PLAN_GENERATED':
      return {
        icon: <Brain className="h-3.5 w-3.5" />,
        bgClass: 'bg-purple-500/10 border-purple-500/20',
        textClass: 'text-purple-400',
      };
    case 'PLAN_REVISED':
      return {
        icon: <RefreshCw className="h-3.5 w-3.5" />,
        bgClass: 'bg-purple-500/10 border-purple-500/20',
        textClass: 'text-purple-400',
      };
    case 'PLAN_APPROVED':
      return {
        icon: <CheckCircle2 className="h-3.5 w-3.5" />,
        bgClass: 'bg-emerald-500/10 border-emerald-500/20',
        textClass: 'text-emerald-400',
      };
    case 'PLAN_REJECTED':
      return {
        icon: <XCircle className="h-3.5 w-3.5" />,
        bgClass: 'bg-rose-500/10 border-rose-500/20',
        textClass: 'text-rose-400',
      };
    case 'WORKSPACE_SETUP':
      return {
        icon: <FolderGit2 className="h-3.5 w-3.5" />,
        bgClass: 'bg-sky-500/10 border-sky-500/20',
        textClass: 'text-sky-400',
      };
    case 'EXECUTING':
    case 'CODE_MODIFICATION':
      return {
        icon: <Play className="h-3.5 w-3.5" />,
        bgClass: 'bg-blue-500/10 border-blue-500/20',
        textClass: 'text-blue-400',
      };
    case 'TESTING':
    case 'TESTS_EXECUTED':
      return {
        icon: <TestTube2 className="h-3.5 w-3.5" />,
        bgClass: 'bg-cyan-500/10 border-cyan-500/20',
        textClass: 'text-cyan-400',
      };
    case 'REPAIRING':
    case 'REPAIR_ATTEMPT':
      return {
        icon: <Wrench className="h-3.5 w-3.5" />,
        bgClass: 'bg-orange-500/10 border-orange-500/20',
        textClass: 'text-orange-400',
      };
    case 'VERIFYING':
    case 'VERIFICATION_COMPLETED':
      return {
        icon: <ShieldCheck className="h-3.5 w-3.5" />,
        bgClass: 'bg-indigo-500/10 border-indigo-500/20',
        textClass: 'text-indigo-400',
      };
    case 'READY_FOR_PUBLICATION':
      return {
        icon: <Send className="h-3.5 w-3.5" />,
        bgClass: 'bg-lime-500/10 border-lime-500/20',
        textClass: 'text-lime-400',
      };
    case 'PUBLISHING':
      return {
        icon: <UploadCloud className="h-3.5 w-3.5" />,
        bgClass: 'bg-teal-500/10 border-teal-500/20',
        textClass: 'text-teal-400',
      };
    case 'DRAFT_PR_CREATED':
      return {
        icon: <GitPullRequest className="h-3.5 w-3.5" />,
        bgClass: 'bg-emerald-500/10 border-emerald-500/20',
        textClass: 'text-emerald-400',
      };
    case 'FAILED':
      return {
        icon: <AlertTriangle className="h-3.5 w-3.5" />,
        bgClass: 'bg-red-500/10 border-red-500/20',
        textClass: 'text-red-400',
      };
    case 'CANCELLED':
      return {
        icon: <Slash className="h-3.5 w-3.5" />,
        bgClass: 'bg-zinc-500/10 border-zinc-500/20',
        textClass: 'text-zinc-400',
      };
    default:
      return {
        icon: <Clock className="h-3.5 w-3.5" />,
        bgClass: 'bg-accent border-border',
        textClass: 'text-muted-foreground',
      };
  }
}

export function ExecutionTimeline({ taskId, className }: ExecutionTimelineProps) {
  const { data: eventsData, isLoading, isError, error, refetch } = useTaskEvents(taskId);

  const events: TaskEvent[] = eventsData?.items || [];

  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-card p-5 shadow-xs space-y-4',
        className
      )}
    >
      <div className="flex items-center justify-between border-b border-border pb-3">
        <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          Lifecycle & Event Timeline
        </h3>
        <span className="text-xs font-mono text-muted-foreground">
          {isError ? 'Error' : `${events.length} event(s)`}
        </span>
      </div>

      {isError ? (
        <div className="space-y-3 py-2">
          <ErrorMessage error={error} message="Failed to load timeline events." />
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => refetch()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-border bg-card text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Retry</span>
            </button>
          </div>
        </div>
      ) : isLoading ? (
        <div className="py-8 text-center">
          <LoadingSpinner size="sm" label="Loading timeline events..." />
        </div>
      ) : events.length === 0 ? (
        <div className="py-8 text-center text-muted-foreground">
          <p className="text-xs italic">No lifecycle events recorded for this task yet.</p>
        </div>
      ) : (
        <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-border">
          {events.map((evt, idx) => {
            const { icon, bgClass, textClass } = getEventIcon(evt.event_type);

            return (
              <div key={evt.id || idx} className="relative group">
                {/* Event node badge */}
                <div
                  className={cn(
                    'absolute -left-6 mt-0.5 flex h-5 w-5 items-center justify-center rounded-full border bg-card transition-colors',
                    bgClass,
                    textClass
                  )}
                  title={evt.event_type}
                >
                  {icon}
                </div>

                {/* Event card */}
                <div className="rounded-md border border-border/80 bg-background/50 p-3 text-xs space-y-1.5 hover:border-border transition-colors">
                  <div className="flex flex-wrap items-center justify-between gap-1">
                    <span className="font-mono font-semibold text-foreground text-[11px]">
                      {evt.event_type.replace(/_/g, ' ')}
                    </span>
                    <span className="text-[10px] text-muted-foreground font-mono">
                      {formatDate(evt.created_at)}
                    </span>
                  </div>

                  <p className="text-muted-foreground">{evt.description}</p>

                  {/* Metadata / Details */}
                  {evt.details && Object.keys(evt.details).length > 0 && (
                    <div className="mt-2 pt-2 border-t border-border/60 flex flex-wrap gap-x-4 gap-y-1 text-[11px] font-mono text-muted-foreground/90">
                      {Object.entries(evt.details).map(([k, v]) => (
                        <div key={k} className="truncate max-w-xs">
                          <span className="text-muted-foreground mr-1">{k}:</span>
                          <span className="text-foreground">
                            {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* User / Actor */}
                  {evt.user_id && (
                    <div className="text-[10px] text-muted-foreground pt-1">
                      Actor: <span className="text-foreground font-mono">{evt.user_id}</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
