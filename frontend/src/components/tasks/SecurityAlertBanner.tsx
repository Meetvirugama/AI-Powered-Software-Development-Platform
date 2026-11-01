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
  'INVARIANT_VALIDATION_FAILED',
  'POST_VERIFICATION_MUTATION_DETECTED',
  'DISK_QUOTA_EXCEEDED',
]);

/**
 * Client-side credential sanitization applied as defense in depth.
 * Server-side redaction remains authoritative.
 */
export function sanitizeSecurityMessage(raw: unknown): string {
  if (raw === null || raw === undefined) {
    return 'Security policy enforcement blocked the requested operation.';
  }
  let msg = typeof raw === 'string' ? raw : typeof raw === 'object' ? JSON.stringify(raw) : String(raw);
  if (!msg.trim()) {
    return 'Security policy enforcement blocked the requested operation.';
  }

  // 1. Redact Authorization headers: Bearer, Basic (does not corrupt ordinary prose like 'token exfiltration')
  msg = msg.replace(/\b(bearer|basic)\s+[^\s,;]+/gi, (match) => {
    const scheme = match.split(/\s+/)[0];
    return `${scheme} [REDACTED_TOKEN]`;
  });

  // 2. Redact known token prefixes: GitHub tokens, OpenAI keys, AWS keys, Slack tokens
  msg = msg.replace(/\b(gh[pousr]_[a-zA-Z0-9]{30,255})\b/g, '[REDACTED_CREDENTIAL]');
  msg = msg.replace(/\b(sk-[a-zA-Z0-9]{20,})\b/g, '[REDACTED_CREDENTIAL]');
  msg = msg.replace(/\b(AKIA[0-9A-Z]{16})\b/g, '[REDACTED_CREDENTIAL]');
  msg = msg.replace(/\b(xox[baprs]-[0-9a-zA-Z-]{10,})\b/g, '[REDACTED_CREDENTIAL]');

  // 3. Redact key-value and JSON-serialized secrets: password, token, secret, api_key, auth_token, access_token, private_key
  msg = msg.replace(
    /((?:["']|\b)(?:password|passwd|pwd|token|secret|api[_-]?key|auth(?:orization)?[_-]?token|access[_-]?token|private[_-]?key)(?:["']|\b)?\s*[:=]\s*)(?:(["'])(?:(?!\2)[^\\]|\\.)*\2|([^\s,;}\]]+))/gi,
    (_match, prefix, quote) => {
      if (quote) {
        return `${prefix}${quote}[REDACTED]${quote}`;
      }
      return `${prefix}[REDACTED]`;
    }
  );

  // 4. Redact connection URIs containing credentials
  msg = msg.replace(/([a-zA-Z][a-zA-Z0-9+.-]*:\/\/[^:]+:)[^@]+(@[^\s]+)/g, '$1[REDACTED]$2');

  return msg;
}

export function SecurityAlertBanner({ events = [], className }: SecurityAlertBannerProps) {
  if (!Array.isArray(events) || events.length === 0) {
    return null;
  }

  const securityEvents = events.filter(
    (e) => e && typeof e === 'object' && e.event_type && SECURITY_EVENT_TYPES.has(e.event_type)
  );

  if (securityEvents.length === 0) {
    return null;
  }

  const latest = securityEvents[securityEvents.length - 1];

  // Prefer backend-provided sanitized messages if available
  const backendSanitized =
    (latest as any).sanitized_message ||
    (latest.details as any)?.sanitized_message ||
    (latest.details as any)?.sanitized_description;

  const rawDescription = backendSanitized || latest.description || latest.summary || '';
  const sanitized = sanitizeSecurityMessage(rawDescription);
  const eventTypeLabel = latest.event_type ? latest.event_type.replace(/_/g, ' ') : 'SECURITY ALERT';

  return (
    <div
      data-testid="security-alert-banner"
      className={cn(
        'rounded-lg border-2 border-red-500/50 bg-red-950/25 p-4 shadow-sm text-xs space-y-2',
        className
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 font-semibold text-red-400">
          <ShieldAlert className="h-4 w-4 shrink-0 text-red-400" />
          <span>Security Policy Enforcement Blocked Operation</span>
        </div>
        <span className="font-mono text-[10px] bg-red-500/20 text-red-300 border border-red-500/30 px-2 py-0.5 rounded uppercase font-bold">
          {eventTypeLabel}
        </span>
      </div>

      <p className="text-red-200/90 leading-relaxed font-mono text-[11px] pl-6 bg-red-950/40 p-2.5 rounded border border-red-500/20 whitespace-pre-wrap break-all">
        {sanitized}
      </p>

      <div className="flex items-center gap-4 text-[11px] text-red-300/70 pl-6 pt-1 flex-wrap">
        <span className="flex items-center gap-1">
          <Lock className="h-3 w-3" /> Sandbox Isolation Active
        </span>
        <span>•</span>
        <span>
          Prohibited actions are blocked and audited per system security baseline. Client-side sanitization applied as defense in depth.
        </span>
      </div>
    </div>
  );
}
