import { useState, useEffect } from 'react';
import { useParams, Outlet } from 'react-router-dom';
import { useRepository } from '../hooks/useRepositories';
import { StudioSubNav } from '../components/studios/StudioSubNav';
import { CommandPalette } from '../components/studios/CommandPalette';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ErrorMessage } from '../components/shared/ErrorMessage';

export function RepositoryStudioLayout() {
  const { id } = useParams<{ id: string }>();
  const { data: repo, isLoading, isError, error, refetch } = useRepository(id);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  // Global Cmd+K / Ctrl+K listener for instant command palette access
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  if (isLoading) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <LoadingSpinner size="lg" label="Loading repository workspace..." />
      </div>
    );
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
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
      />
      <div className="flex-1 min-h-0 overflow-hidden relative flex flex-col">
        <Outlet context={{ repository: repo, id }} />
      </div>

      <CommandPalette
        repoId={id ?? repo.id}
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
      />
    </div>
  );
}

export default RepositoryStudioLayout;
