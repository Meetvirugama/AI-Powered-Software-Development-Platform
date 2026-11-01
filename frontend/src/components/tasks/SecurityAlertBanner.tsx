import { ShieldAlert, Lock } from 'lucide-react';
import type { TaskEvent } from '../../types/task';
import { cn } from '../../lib/utils';

export interface SecurityAlertBannerProps {
  events?: TaskEvent[];
  className?: string;
}

const SECURITY_EVENT_TYPES = new Set([
  'SECURITY_POLICY_VIOLATION',
  'POLICY_VIOLATION',
  'COMMAND_BLOCKED',
  'SECRET_LEAK_DETECTED',
  'RESTRICTED_ACCESS',
  'RESOURCE_LIMIT_EXCEEDED',
  'EXECUTION_BLOCKED',
  'UNAUTHORIZED_OPERATION',
]);

function sanitizeMessage(msg: string): string {
  if (!msg) return 'Security policy enforcement blocked the requested operation.';
  return msg
    .replace(/(ghp_[a-zA-Z0-9]{30,}|sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16})/g, '[REDACTED_CREDENTIAL]')
    .replace(/(bearer\s+)[^\s]+/gi, '$1[REDACTED_TOKEN]')
    .replace(/(password|token|secret)\s*[:=]\s*['"][^'"]+['"]/gi, '$1=[REDACTED]');
}

export function SecurityAlertBanner({ events = [], className }: SecurityAlertBannerProps) {
  const securityEvents = events.filter((e) => SECURITY_EVENT_TYPES.has(e.event_type));

  if (securityEvents.length === 0) {
    return null;
  }

  const latest = securityEvents[securityEvents.length - 1];
  const sanitized = sanitizeMessage(latest.description || latest.summary || '');

  return (
    <div
      data-testid="security-alert-banner"
      className={cn(
        'rounded-lg border border-red-500/50 bg-red-950/20 p-4 shadow-sm text-xs space-y-2',
        className
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-red-400">
          <ShieldAlert className="h-4 w-4 shrink-0 text-red-400" />
          <span>Security Policy Enforcement Blocked Operation</span>
        </div>
        <span className="font-mono text-[10px] bg-red-500/20 text-red-300 border border-red-500/30 px-2 py-0.5 rounded uppercase font-bold">
          {latest.event_type.replace(/_/g, ' ')}
        </span>
      </div>

      <p className="text-red-200/90 leading-relaxed font-mono text-[11px] pl-6 bg-red-950/40 p-2.5 rounded border border-red-500/20">
        {sanitized}
      </p>

      <div className="flex items-center gap-4 text-[11px] text-red-300/70 pl-6 pt-1">
        <span className="flex items-center gap-1">
          <Lock className="h-3 w-3" /> Sandbox Isolation Active
        </span>
        <span>•</span>
        <span>Prohibited actions are blocked and audited per system security baseline.</span>
      </div>
    </div>
  );
}
