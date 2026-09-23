import React, { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Optional custom fallback UI. Defaults to a generic error message. */
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Global ErrorBoundary component.
 * Catches unhandled rendering errors and prevents the whole app from crashing.
 * Wrap it around subtrees that may throw during render.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // TODO: forward to an error reporting service (e.g. Sentry) in production.
    console.error('[ErrorBoundary] Caught error:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div className="flex flex-col items-center justify-center min-h-[200px] p-8 text-center">
          <p className="text-destructive font-semibold text-lg mb-2">
            Something went wrong
          </p>
          <p className="text-muted-foreground text-sm">
            {this.state.error?.message ?? 'An unexpected error occurred.'}
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
