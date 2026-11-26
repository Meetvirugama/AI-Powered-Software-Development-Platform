import { useParams, Outlet } from 'react-router-dom';
import { useRepository } from '../hooks/useRepositories';
import { useSseConnectionStatus } from '../hooks/useSseConnectionStatus';
import { StudioSubNav } from '../components/studios/StudioSubNav';
import { useAppStore } from '../stores/useAppStore';
import { StudioLayoutSkeleton } from '../components/shared/Skeletons';
import { ErrorMessage } from '../components/shared/ErrorMessage';

export function RepositoryStudioLayout() {
  const { id } = useParams<{ id: string }>();
  const { isConnected: isSseConnected } = useSseConnectionStatus();
  // Fall back to 20s polling only when SSE is disconnected and a sync is running.
  const { data: repo, isLoading, isError, error, refetch } = useRepository(id, {
    refetchInterval: (query) =>
      isSseConnected ? false : query.state.data?.sync_status === 'SYNCING' ? 20_000 : false,
  });
  // The command palette (and its Ctrl/Cmd+K shortcut) is global and lives in AppLayout.
  const setCommandPaletteOpen = useAppStore((state) => state.setCommandPaletteOpen);

  if (isLoading) {
    return <StudioLayoutSkeleton />;
  }

  if (isError || !repo) {
    return (
      <div className="flex h-full w-full items-center justify-center p-6">
        <div className="max-w-md w-full">
          <ErrorMessage
            message={error?.message ?? 'Failed to load repository workspace.'}
          />
          <button
            onClick={() => refetch()}
            className="mt-3 w-full inline-flex items-center justify-center px-4 py-2 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-xs"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full overflow-hidden bg-background">
      <StudioSubNav
        repository={repo}
        isLoading={isLoading}
        onOpenCommandPalette={() => setCommandPaletteOpen(true)}
      />
      <div className="flex-1 min-h-0 overflow-hidden relative flex flex-col">
        <Outlet key={id} context={{ repository: repo, id }} />
      </div>
    </div>
  );
}

export default RepositoryStudioLayout;
