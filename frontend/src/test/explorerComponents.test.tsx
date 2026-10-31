import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SyncProgressIndicator } from '../components/explorer/SyncProgressIndicator';
import { RepositorySyncCard } from '../components/explorer/RepositorySyncCard';
import { RepositoryMetricsSidebar } from '../components/explorer/RepositoryMetricsSidebar';
import type { RepositoryDependency } from '../types/api';

describe('SyncProgressIndicator', () => {
  it('renders all four progress stages: Cloning, Scanning, Indexing, and Ready', () => {
    render(<SyncProgressIndicator currentStage="SCANNING" isFailed={false} />);

    expect(screen.getByText('Cloning')).toBeInTheDocument();
    expect(screen.getByText('Scanning')).toBeInTheDocument();
    expect(screen.getByText('Indexing')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('renders failed stage indicator when isFailed is true', () => {
    render(<SyncProgressIndicator currentStage="INDEXING" isFailed={true} />);
    // Scanning and Indexing are present, and text-destructive class is applied to failed stage label
    const failedLabel = screen.getByText('Indexing');
    expect(failedLabel).toHaveClass('text-destructive');
  });
});

describe('RepositorySyncCard', () => {
  it('renders synchronization in progress header and stages', () => {
    const onSync = vi.fn();
    render(
      <RepositorySyncCard
        repo={{ sync_status: 'SYNCING' }}
        progress={{
          stage: 'INDEXING',
          label: 'Indexing',
          isActive: true,
          isComplete: false,
          isFailed: false,
        }}
        isSyncActive={true}
        onSync={onSync}
      />
    );

    expect(screen.getByText('Repository Synchronization in Progress')).toBeInTheDocument();
    expect(screen.getByText('Indexing')).toBeInTheDocument();
  });

  it('renders retry button and triggers onSync when failed', () => {
    const onSync = vi.fn();
    render(
      <RepositorySyncCard
        repo={{ sync_status: 'FAILED' }}
        progress={{
          stage: 'SCANNING',
          label: 'Failed',
          isActive: false,
          isComplete: false,
          isFailed: true,
        }}
        isSyncActive={false}
        onSync={onSync}
      />
    );

    expect(screen.getByText('Synchronization Failed')).toBeInTheDocument();
    const retryBtn = screen.getByRole('button', { name: /Retry Sync/i });
    expect(retryBtn).toBeInTheDocument();
    fireEvent.click(retryBtn);
    expect(onSync).toHaveBeenCalledTimes(1);
  });
});

describe('RepositoryMetricsSidebar', () => {
  const mockDeps: RepositoryDependency[] = [
    { name: 'fastapi', version: '^0.115.0', ecosystem: 'pypi' },
    { name: 'pydantic', version: '^2.10.0', ecosystem: 'pypi' },
    { name: 'react', version: '^19.0.0', ecosystem: 'npm' },
  ];

  it('renders metrics numbers for files, symbols, and chunks', () => {
    render(
      <RepositoryMetricsSidebar
        repo={{ file_count: 55, symbol_count: 210, chunk_count: 880 }}
        totalFiles={55}
        dependencies={mockDeps}
        depsLoading={false}
        depsError={false}
      />
    );

    expect(screen.getByText('55')).toBeInTheDocument();
    expect(screen.getByText('210')).toBeInTheDocument();
    expect(screen.getByText('880')).toBeInTheDocument();
  });

  it('filters dependencies by search input', () => {
    render(
      <RepositoryMetricsSidebar
        repo={{ file_count: 3, symbol_count: 10, chunk_count: 20 }}
        totalFiles={3}
        dependencies={mockDeps}
        depsLoading={false}
        depsError={false}
      />
    );

    expect(screen.getByText('fastapi')).toBeInTheDocument();
    expect(screen.getByText('react')).toBeInTheDocument();

    const searchInput = screen.getByPlaceholderText('Filter dependencies…');
    fireEvent.change(searchInput, { target: { value: 'react' } });

    expect(screen.getByText('react')).toBeInTheDocument();
    expect(screen.queryByText('fastapi')).not.toBeInTheDocument();
  });

  it('displays empty message when filter matches no dependencies', () => {
    render(
      <RepositoryMetricsSidebar
        repo={{ file_count: 3, symbol_count: 10, chunk_count: 20 }}
        totalFiles={3}
        dependencies={mockDeps}
        depsLoading={false}
        depsError={false}
      />
    );

    const searchInput = screen.getByPlaceholderText('Filter dependencies…');
    fireEvent.change(searchInput, { target: { value: 'nonexistent-pkg' } });

    expect(screen.getByText(/No dependencies matching "nonexistent-pkg"/i)).toBeInTheDocument();
  });
});
