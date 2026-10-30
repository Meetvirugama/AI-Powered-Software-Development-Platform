import { CheckCircle2, XCircle, Shield, Clock } from 'lucide-react';
import { useTaskEvents } from '../../hooks/useTasks';
import type { TaskDetailResponse } from '../../types/task';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { cn } from '../../lib/utils';

export interface ApprovalHistoryPanelProps {
  taskId: string;
  task: TaskDetailResponse;
  className?: string;
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

export function ApprovalHistoryPanel({
  taskId,
  task,
  className,
}: ApprovalHistoryPanelProps) {
  const { data: eventsData, isLoading } = useTaskEvents(taskId);

  const approvalEvents = (eventsData?.items || []).filter(
    (e) => e.event_type === 'PLAN_APPROVED' || e.event_type === 'PLAN_REJECTED'
  );

  return (
    <div
      className={cn(
        'rounded-lg border border-border bg-card p-5 shadow-xs space-y-4',
        className
      )}
    >
      <div className="flex items-center justify-between border-b border-border pb-3">
        <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
          <Shield className="h-4 w-4 text-primary" />
          Approval & Rejection History
        </h3>
        <span className="text-xs font-mono text-muted-foreground">
          {approvalEvents.length} decision(s)
        </span>
      </div>

      {isLoading ? (
        <div className="py-8 text-center">
          <LoadingSpinner size="sm" label="Loading approval records..." />
        </div>
      ) : approvalEvents.length === 0 ? (
        <div className="py-6 text-center text-muted-foreground space-y-1">
          <p className="text-xs italic">No approval or rejection decisions recorded yet.</p>
          {task.status === 'PENDING_APPROVAL' && (
            <p className="text-[11px] text-amber-400">
              Awaiting human sign-off on implementation plan v{task.plan_version}.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {approvalEvents.map((evt, idx) => {
            const isApproved = evt.event_type === 'PLAN_APPROVED';
            const notes =
              (evt.details?.notes as string) ||
              (evt.details?.reason as string) ||
              evt.description;

            return (
              <div
                key={evt.id || idx}
                className={cn(
                  'p-3.5 rounded-md border text-xs space-y-2',
                  isApproved
                    ? 'border-emerald-500/20 bg-emerald-500/5'
                    : 'border-rose-500/20 bg-rose-500/5'
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 font-mono font-bold px-2 py-0.5 rounded text-[11px]',
                        isApproved
                          ? 'bg-emerald-500/10 text-emerald-400'
                          : 'bg-rose-500/10 text-rose-400'
                      )}
                    >
                      {isApproved ? (
                        <CheckCircle2 className="h-3 w-3" />
                      ) : (
                        <XCircle className="h-3 w-3" />
                      )}
                      {isApproved ? 'APPROVED' : 'REJECTED'}
                    </span>

                    <span className="font-mono text-muted-foreground text-[11px]">
                      Plan v{task.approved_plan_version || task.plan_version}
                    </span>
                  </div>

                  <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    <span>{formatDate(evt.created_at)}</span>
                  </div>
                </div>

                {/* Reviewer */}
                <div className="text-[11px] text-muted-foreground">
                  Decision by:{' '}
                  <span className="font-medium text-foreground">
                    {evt.user_id || 'Human Reviewer'}
                  </span>
                </div>

                {/* Decision notes/reason */}
                {notes && (
                  <div className="p-2 rounded bg-background/60 border border-border/60 text-foreground/90 font-sans">
                    <span className="font-medium text-muted-foreground mr-1">
                      {isApproved ? 'Notes:' : 'Reason:'}
                    </span>
                    {notes}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
