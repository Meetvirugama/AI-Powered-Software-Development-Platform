import { cn } from '../../lib/utils';

interface LoadingSpinnerProps {
  /** Additional Tailwind classes. */
  className?: string;
  /** Accessible label for screen readers. */
  label?: string;
  /** Size variant. Defaults to 'md'. */
  size?: 'sm' | 'md' | 'lg';
}

const sizeClasses = {
  sm: 'h-4 w-4 border-2',
  md: 'h-8 w-8 border-2',
  lg: 'h-12 w-12 border-4',
};

/**
 * Reusable loading spinner.
 * Usage: <LoadingSpinner /> or <LoadingSpinner size="lg" label="Loading data..." />
 */
export function LoadingSpinner({ className, label = 'Loading...', size = 'md' }: LoadingSpinnerProps) {
  return (
    <div role="status" aria-label={label} className={cn('flex items-center justify-center', className)}>
      <div
        className={cn(
          'animate-spin rounded-full border-primary border-t-transparent',
          sizeClasses[size]
        )}
      />
      <span className="sr-only">{label}</span>
    </div>
  );
}
