import { cn } from '../../lib/utils';
import type { ApiError } from '../../types/api';

interface ErrorMessageProps {
  /** A plain string message. */
  message?: string;
  /** An ApiError object (takes precedence over `message`). */
  error?: ApiError | null;
  /** Additional Tailwind classes. */
  className?: string;
}

/**
 * Reusable error message display component.
 * Accepts either a plain string or a normalised ApiError.
 *
 * Usage:
 *   <ErrorMessage message="Could not load data." />
 *   <ErrorMessage error={apiError} />
 */
export function ErrorMessage({ message, error, className }: ErrorMessageProps) {
  const displayMessage = error?.message ?? message ?? 'An unexpected error occurred.';

  return (
    <div
      role="alert"
      className={cn(
        'rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive',
        className
      )}
    >
      {error?.code && (
        <span className="mr-2 font-mono text-xs opacity-70">[{error.code}]</span>
      )}
      {displayMessage}
    </div>
  );
}
