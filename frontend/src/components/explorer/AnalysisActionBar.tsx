import { BookOpen, Bug, FlaskConical, FileCheck, History } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { AnalysisFeatureType, AnalysisTarget } from '../../types/analysis';

export interface AnalysisActionBarProps {
  activeFeature: AnalysisFeatureType | null;
  activeTarget: AnalysisTarget;
  onSelectFeature: (feature: AnalysisFeatureType) => void;
  onOpenHistory?: () => void;
  disabled?: boolean;
  className?: string;
}

interface ActionItem {
  id: AnalysisFeatureType;
  label: string;
  description: string;
  icon: typeof BookOpen;
  accentColor: string;
  activeClass: string;
}

const ACTIONS: ActionItem[] = [
  {
    id: 'explain',
    label: 'Explain Code',
    description: 'Understand purpose, logic flow, and dependencies',
    icon: BookOpen,
    accentColor: 'text-blue-400',
    activeClass: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  },
  {
    id: 'bugs',
    label: 'Find Bugs',
    description: 'Detect defects using static rules and AI reasoning',
    icon: Bug,
    accentColor: 'text-amber-400',
    activeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  },
  {
    id: 'tests',
    label: 'Generate Tests',
    description: 'Generate framework-aware test cases and assertions',
    icon: FlaskConical,
    accentColor: 'text-emerald-400',
    activeClass: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  },
  {
    id: 'review',
    label: 'Code Review',
    description: 'Standalone review for correctness, security, and quality',
    icon: FileCheck,
    accentColor: 'text-purple-400',
    activeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  },
];

export function AnalysisActionBar({
  activeFeature,
  activeTarget,
  onSelectFeature,
  onOpenHistory,
  disabled = false,
  className,
}: AnalysisActionBarProps) {
  const targetLabel =
    activeTarget.type === 'symbol' && activeTarget.symbol
      ? `Symbol: ${activeTarget.symbol}`
      : activeTarget.type === 'range' && activeTarget.start_line
      ? `Lines ${activeTarget.start_line}–${activeTarget.end_line}`
      : 'Entire File';

  return (
    <div
      className={cn(
        'shrink-0 border-b border-border bg-card/60 p-2 flex flex-wrap items-center justify-between gap-2',
        className
      )}
    >
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mr-1 hidden sm:inline">
          Developer Intelligence:
        </span>

        {ACTIONS.map((action) => {
          const Icon = action.icon;
          const isActive = activeFeature === action.id;

          return (
            <button
              key={action.id}
              type="button"
              disabled={disabled}
              onClick={() => onSelectFeature(action.id)}
              className={cn(
                'inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-all shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 disabled:pointer-events-none',
                isActive
                  ? action.activeClass
                  : 'border-border/70 bg-background/60 text-muted-foreground hover:text-foreground hover:bg-accent/60 hover:border-border'
              )}
              title={`${action.label}: ${action.description} (${targetLabel})`}
            >
              <Icon className={cn('h-3.5 w-3.5', isActive ? action.accentColor : 'text-muted-foreground')} />
              <span>{action.label}</span>
            </button>
          );
        })}
      </div>


      <div className="flex items-center gap-2">
        <div className="text-[10px] text-muted-foreground font-mono hidden md:flex items-center gap-1">
          <span>Target:</span>
          <span className="text-foreground font-medium truncate max-w-[180px]">
            {targetLabel}
          </span>
        </div>

        {onOpenHistory && (
          <button
            type="button"
            onClick={onOpenHistory}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border/70 bg-background/60 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-colors shadow-xs"
            title="View Analysis History & Reopen Past Runs"
          >
            <History className="h-3.5 w-3.5 text-primary" />
            <span>History</span>
          </button>
        )}
      </div>
    </div>
  );
}
