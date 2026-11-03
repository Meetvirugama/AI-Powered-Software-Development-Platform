import type { ReactNode } from 'react';
import {
  CircleDot,
  Sparkles,
  Clock,
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
  RefreshCcw,
  Lock,
  HelpCircle,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { TaskStatus } from '../../types/task';

export interface TaskStatusBadgeProps {
  status: TaskStatus | string | null | undefined;
  className?: string;
  showIcon?: boolean;
  size?: 'sm' | 'md';
}

interface StatusConfig {
  label: string;
  icon: ReactNode;
  classes: string;
}

const STATUS_CONFIGS: Record<TaskStatus, StatusConfig> = {
  [TaskStatus.CREATED]: {
    label: 'Created',
    icon: <CircleDot className="h-3 w-3 shrink-0" />,
    classes: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
  },
  [TaskStatus.PLANNING]: {
    label: 'Planning',
    icon: <Sparkles className="h-3 w-3 shrink-0" />,
    classes: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  },
  [TaskStatus.PENDING_APPROVAL]: {
    label: 'Pending Approval',
    icon: <Clock className="h-3 w-3 shrink-0" />,
    classes: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  },
  [TaskStatus.APPROVED]: {
    label: 'Approved',
    icon: <CheckCircle2 className="h-3 w-3 shrink-0" />,
    classes: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  },
  [TaskStatus.REJECTED]: {
    label: 'Rejected',
    icon: <XCircle className="h-3 w-3 shrink-0" />,
    classes: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
  },
  [TaskStatus.WORKSPACE_SETUP]: {
    label: 'Workspace Setup',
    icon: <FolderGit2 className="h-3 w-3 shrink-0" />,
    classes: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
  },
  [TaskStatus.EXECUTING]: {
    label: 'Executing',
    icon: <Play className="h-3 w-3 shrink-0" />,
    classes: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  },
  [TaskStatus.TESTING]: {
    label: 'Testing',
    icon: <TestTube2 className="h-3 w-3 shrink-0" />,
    classes: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  },
  [TaskStatus.REPAIRING]: {
    label: 'Repairing',
    icon: <Wrench className="h-3 w-3 shrink-0" />,
    classes: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  },
  [TaskStatus.VERIFYING]: {
    label: 'Verifying',
    icon: <ShieldCheck className="h-3 w-3 shrink-0" />,
    classes: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  },
  [TaskStatus.READY_FOR_PUBLICATION]: {
    label: 'Ready for Publication',
    icon: <Send className="h-3 w-3 shrink-0" />,
    classes: 'bg-lime-500/10 text-lime-400 border-lime-500/20',
  },
  [TaskStatus.PUBLISHING]: {
    label: 'Publishing',
    icon: <UploadCloud className="h-3 w-3 shrink-0" />,
    classes: 'bg-teal-500/10 text-teal-400 border-teal-500/20',
  },
  [TaskStatus.DRAFT_PR_CREATED]: {
    label: 'Draft PR Created',
    icon: <GitPullRequest className="h-3 w-3 shrink-0" />,
    classes: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  },
  [TaskStatus.FAILED]: {
    label: 'Failed',
    icon: <AlertTriangle className="h-3 w-3 shrink-0" />,
    classes: 'bg-red-500/10 text-red-400 border-red-500/20',
  },
  [TaskStatus.CANCELLED]: {
    label: 'Cancelled',
    icon: <Slash className="h-3 w-3 shrink-0" />,
    classes: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20',
  },
  [TaskStatus.RECOVERY_REQUIRED]: {
    label: 'Recovery Required',
    icon: <RefreshCcw className="h-3 w-3 shrink-0" />,
    classes: 'bg-amber-600/10 text-amber-500 border-amber-600/20',
  },
  [TaskStatus.BLOCKED]: {
    label: 'Blocked',
    icon: <Lock className="h-3 w-3 shrink-0" />,
    classes: 'bg-rose-900/20 text-rose-400 border-rose-700/30',
  },
};

export function TaskStatusBadge({
  status,
  className,
  showIcon = true,
  size = 'sm',
}: TaskStatusBadgeProps) {
  const safeStatus = (status ?? 'UNKNOWN').toString();
  const isKnown = Object.prototype.hasOwnProperty.call(STATUS_CONFIGS, safeStatus);

  const config: StatusConfig = isKnown
    ? STATUS_CONFIGS[safeStatus as TaskStatus]
    : {
        label: safeStatus.replace(/_/g, ' '),
        icon: <HelpCircle className="h-3 w-3 shrink-0" />,
        classes: 'bg-muted text-muted-foreground border-border',
      };

  const badgeClass = isKnown
    ? `badge-${safeStatus.toLowerCase()}`
    : 'badge-neutral-fallback';

  // Display label: format cleanly
  const displayLabel = safeStatus.replace(/_/g, ' ');

  return (
    <span
      data-testid="status-badge"
      data-status={safeStatus}
      title={`Task Status: ${displayLabel}`}
      className={cn(
        'inline-flex items-center gap-1.5 font-medium border rounded-full transition-colors font-mono',
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm',
        config.classes,
        badgeClass,
        className
      )}
    >
      {showIcon && config.icon}
      <span>{displayLabel}</span>
    </span>
  );
}
