import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useSearchParams, useNavigate, useParams } from 'react-router-dom';
import { useStudioFile } from '../hooks/useStudioFile';
import type { RepositoryFile } from '../types/api';

const repo1Files: RepositoryFile[] = [
  { id: '1', path: '.env', language: null, size_bytes: 100, line_count: 5, content_hash: 'h1', last_indexed_at: '2026-01-01' },
  { id: '2', path: 'src/App.tsx', language: 'TypeScript', size_bytes: 2500, line_count: 100, content_hash: 'h2', last_indexed_at: '2026-01-01' },
  { id: '3', path: 'src/utils.ts', language: 'TypeScript', size_bytes: 800, line_count: 40, content_hash: 'h3', last_indexed_at: '2026-01-01' },
];

const repo2Files: RepositoryFile[] = [
  { id: '4', path: 'backend/main.py', language: 'Python', size_bytes: 3000, line_count: 110, content_hash: 'h4', last_indexed_at: '2026-01-01' },
];

function TestStudioComponent({ files }: { files: RepositoryFile[] }) {
  const { selectedFile, handleSelectFile, targetRange, handleTargetChange } = useStudioFile(files);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  return (
    <div>
      <div data-testid="selected-file">{selectedFile?.path ?? 'none'}</div>
      <div data-testid="target-range">{targetRange.start_line ? `${targetRange.start_line}-${targetRange.end_line}` : 'none'}</div>
      <div data-testid="all-params">{searchParams.toString()}</div>
      <button
        onClick={() => handleSelectFile(files[files.length - 1])}
        data-testid="select-last-file"
      >
        Select Last
      </button>
      <button
        onClick={() => handleTargetChange({ type: 'range', path: selectedFile?.path ?? '', start_line: 10, end_line: 20 })}
        data-testid="select-range"
      >
        Set Range
      </button>
      <button
        onClick={() => navigate('/repositories/repo-2/explain')}
        data-testid="switch-to-repo-2"
      >
        Switch Repo
      </button>
    </div>
  );
}

describe('useStudioFile hook (F-05)', () => {
  it('selects first non-hidden file by default', () => {
    render(
      <MemoryRouter initialEntries={['/repositories/repo-1/explain']}>
        <Routes>
          <Route path="/repositories/:id/explain" element={<TestStudioComponent files={repo1Files} />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByTestId('selected-file').textContent).toBe('src/App.tsx');
  });

  it('resolves deep-link file query parameter with case/path normalization', () => {
    render(
      <MemoryRouter initialEntries={['/repositories/repo-1/explain?file=./SRC/utils.ts']}>
        <Routes>
          <Route path="/repositories/:id/explain" element={<TestStudioComponent files={repo1Files} />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByTestId('selected-file').textContent).toBe('src/utils.ts');
  });

  it('safely falls back to default file when deep link file is not found', () => {
    render(
      <MemoryRouter initialEntries={['/repositories/repo-1/explain?file=nonexistent.tsx']}>
        <Routes>
          <Route path="/repositories/:id/explain" element={<TestStudioComponent files={repo1Files} />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByTestId('selected-file').textContent).toBe('src/App.tsx');
  });

  it('preserves existing search parameters when selecting a file', () => {
    render(
      <MemoryRouter initialEntries={['/repositories/repo-1/explain?mode=strict&tab=findings']}>
        <Routes>
          <Route path="/repositories/:id/explain" element={<TestStudioComponent files={repo1Files} />} />
        </Routes>
      </MemoryRouter>
    );
    fireEvent.click(screen.getByTestId('select-last-file'));
    expect(screen.getByTestId('selected-file').textContent).toBe('src/utils.ts');
    const params = screen.getByTestId('all-params').textContent ?? '';
    expect(params).toContain('mode=strict');
    expect(params).toContain('tab=findings');
    expect(params).toContain('file=src%2Futils.ts');
  });

  it('resets selected file and target range when switching repositories', () => {
    function SwitchContainer() {
      const { id } = useParams<{ id: string }>();
      const files = id === 'repo-2' ? repo2Files : repo1Files;
      return <TestStudioComponent files={files} />;
    }

    render(
      <MemoryRouter initialEntries={['/repositories/repo-1/explain']}>
        <Routes>
          <Route path="/repositories/:id/explain" element={<SwitchContainer />} />
        </Routes>
      </MemoryRouter>
    );

    // Select last file and range in Repo 1
    fireEvent.click(screen.getByTestId('select-last-file'));
    fireEvent.click(screen.getByTestId('select-range'));
    expect(screen.getByTestId('selected-file').textContent).toBe('src/utils.ts');
    expect(screen.getByTestId('target-range').textContent).toBe('10-20');

    // Switch to Repo 2
    fireEvent.click(screen.getByTestId('switch-to-repo-2'));

    // Should now show Repo 2 default file, not Repo 1 stale file
    expect(screen.getByTestId('selected-file').textContent).toBe('backend/main.py');
    expect(screen.getByTestId('target-range').textContent).toBe('none');
  });
});
