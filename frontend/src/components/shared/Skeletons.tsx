import { cn } from '../../lib/utils';

function SkeletonBlock({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-muted/60', className)} aria-hidden="true" />;
}

/** Route-level Suspense shell matching the app sidebar + content layout. */
export function PageShellSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading workspace…"
      className="flex min-h-screen w-full bg-background"
    >
      <div className="hidden md:flex w-60 shrink-0 flex-col gap-3 border-r border-border p-4">
        <SkeletonBlock className="h-7 w-32" />
        <SkeletonBlock className="h-8 w-full mt-2" />
        <SkeletonBlock className="h-8 w-full" />
        <SkeletonBlock className="h-8 w-3/4" />
      </div>
      <div className="flex-1 p-6 space-y-6">
        <div className="flex items-center justify-between">
          <SkeletonBlock className="h-7 w-48" />
          <SkeletonBlock className="h-8 w-28" />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, idx) => (
            <div key={idx} className="rounded-xl border border-border bg-card p-4 space-y-3">
              <SkeletonBlock className="h-5 w-2/3" />
              <SkeletonBlock className="h-3.5 w-1/3" />
              <SkeletonBlock className="h-6 w-24 rounded-full" />
              <SkeletonBlock className="h-8 w-full mt-2" />
            </div>
          ))}
        </div>
      </div>
      <span className="sr-only">Loading workspace…</span>
    </div>
  );
}

/** Skeleton card grid matching the Dashboard & Repositories card layout. */
export function RepositoryGridSkeleton({
  count = 6,
  label = 'Loading repositories…',
}: {
  count?: number;
  label?: string;
}) {
  return (
    <div role="status" aria-label={label} className="space-y-4">
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: count }).map((_, idx) => (
          <div key={idx} className="rounded-xl border border-border bg-card p-4 space-y-3">
            <div className="flex items-start justify-between gap-2">
              <div className="space-y-2 flex-1">
                <SkeletonBlock className="h-4 w-3/5" />
                <SkeletonBlock className="h-3 w-1/3" />
              </div>
              <SkeletonBlock className="h-5 w-14" />
            </div>
            <div className="flex items-center gap-2">
              <SkeletonBlock className="h-5 w-20 rounded-full" />
              <SkeletonBlock className="h-3 w-16" />
            </div>
            <div className="flex items-center justify-between pt-2 border-t border-border/60">
              <SkeletonBlock className="h-3 w-28" />
              <SkeletonBlock className="h-7 w-20" />
            </div>
          </div>
        ))}
      </div>
      <span className="sr-only">{label}</span>
    </div>
  );
}

/** Skeleton matching the Dashboard recent tasks card rows. */
export function DashboardTasksSkeleton() {
  return (
    <div role="status" aria-label="Loading tasks…" className="divide-y divide-border">
      {Array.from({ length: 3 }).map((_, idx) => (
        <div key={idx} className="flex items-center justify-between px-4 py-3">
          <div className="space-y-1.5 flex-1">
            <SkeletonBlock className="h-4 w-1/2" />
            <SkeletonBlock className="h-3 w-1/4" />
          </div>
          <SkeletonBlock className="h-5 w-20 rounded-full" />
        </div>
      ))}
      <span className="sr-only">Loading tasks…</span>
    </div>
  );
}

/** Full-height skeleton matching the Repository Studio workspace header and split panes. */
export function StudioLayoutSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading repository…"
      className="flex flex-col h-full min-h-0 overflow-hidden"
    >
      <div className="shrink-0 px-4 lg:px-6 pt-3 pb-2 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-3">
          <SkeletonBlock className="h-5 w-44" />
          <SkeletonBlock className="h-5 w-20 rounded-full" />
        </div>
        <div className="flex items-center gap-2">
          <SkeletonBlock className="h-7 w-24" />
          <SkeletonBlock className="h-7 w-24" />
        </div>
      </div>
      <div className="flex-1 min-h-0 p-4 lg:p-6 grid grid-cols-1 lg:grid-cols-12 gap-4">
        <div className="lg:col-span-5 rounded-xl border border-border bg-card p-4 space-y-3">
          <SkeletonBlock className="h-6 w-40" />
          <SkeletonBlock className="h-4 w-full" />
          <SkeletonBlock className="h-4 w-5/6" />
          <SkeletonBlock className="h-64 w-full" />
        </div>
        <div className="lg:col-span-7 rounded-xl border border-border bg-card p-4 space-y-3">
          <SkeletonBlock className="h-6 w-48" />
          <SkeletonBlock className="h-4 w-3/4" />
          <SkeletonBlock className="h-4 w-2/3" />
          <SkeletonBlock className="h-64 w-full" />
        </div>
      </div>
      <span className="sr-only">Loading repository…</span>
    </div>
  );
}
