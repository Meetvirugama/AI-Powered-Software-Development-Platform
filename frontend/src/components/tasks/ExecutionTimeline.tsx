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
    case 'DRAFT_PR_PUBLISHED':
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
  const { data: eventsData, isLoading } = useTaskEvents(taskId);

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
          {events.length} event(s)
        </span>
      </div>

      {isLoading ? (
        <div className="py-8 text-center">
          <LoadingSpinner size="sm" label="Loading timeline events..." />
        </div>
      ) : events.length === 0 ? (
        <div className="py-6 text-center text-muted-foreground text-xs italic">
          No events recorded for this task yet.
        </div>
      ) : (
        <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-border">
          {events.map((event, idx) => {
            const { icon, bgClass, textClass } = getEventIcon(event.event_type);

            return (
              <div key={event.id || idx} className="relative group">
                {/* Timeline node icon */}
                <div
                  className={cn(
                    'absolute -left-6 top-0.5 flex h-5 w-5 items-center justify-center rounded-full border bg-card transition-colors',
                    bgClass,
                    textClass
                  )}
                >
                  {icon}
                </div>

                {/* Event content */}
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-xs font-semibold text-foreground">
                      {event.event_type.replace(/_/g, ' ')}
                    </span>
                    <span className="text-[11px] text-muted-foreground font-mono">
                      {formatDate(event.created_at)}
                    </span>
                  </div>

                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {event.description}
                  </p>

                  {/* Details metadata pill/box if present */}
                  {event.details && Object.keys(event.details).length > 0 && (
                    <div className="mt-1.5 p-2 rounded bg-background border border-border/80 text-[11px] font-mono text-muted-foreground flex flex-wrap gap-2">
                      {Object.entries(event.details).map(([key, val]) => (
                        <span key={key} className="inline-flex items-center gap-1">
                          <span className="text-foreground/70">{key}:</span>
                          <span className="text-primary font-medium truncate max-w-xs">
                            {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                          </span>
                        </span>
                      ))}
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
