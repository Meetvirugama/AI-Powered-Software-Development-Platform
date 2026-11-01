import { describe, it, expect } from 'vitest';
import {
  isSourceReferenceEqual,
  formatSourceRange,
  normalizeFilePath,
  findMatchingRepositoryFile,
} from '../lib/sourceReference';
import type { SourceReference } from '../types/analysis';
import type { RepositoryFile } from '../types/api';

describe('sourceReference helpers', () => {
  const refA: SourceReference = {
    file_path: 'backend/app/main.py',
    start_line: 10,
    end_line: 25,
  };

  const refB: SourceReference = {
    file_path: './backend/app/main.py',
    start_line: 10,
    end_line: 25,
  };

  const refC: SourceReference = {
    file_path: 'backend/app/main.py',
    start_line: 30,
    end_line: 45,
  };

  it('correctly matches equal source references across path normalization', () => {
    expect(isSourceReferenceEqual(refA, refB)).toBe(true);
    expect(isSourceReferenceEqual(refA, refC)).toBe(false);
  });

  it('handles null and undefined safely', () => {
    expect(isSourceReferenceEqual(null, refA)).toBe(false);
    expect(isSourceReferenceEqual(refA, undefined)).toBe(false);
    expect(isSourceReferenceEqual(null, null)).toBe(false);
  });

  it('formats source range cleanly with line bounds', () => {
    expect(formatSourceRange(refA)).toBe('backend/app/main.py:10-25');
    expect(formatSourceRange({ file_path: 'app.py', start_line: 12, end_line: 12 })).toBe('app.py:12');
    expect(formatSourceRange({ file_path: 'README.md' })).toBe('README.md');
    expect(formatSourceRange(null)).toBe('');
  });

  describe('normalizeFilePath and findMatchingRepositoryFile (F-05)', () => {
    const mockFiles: RepositoryFile[] = [
      {
        id: '1',
        path: 'src/components/Header.tsx',
        language: 'TypeScript',
        size_bytes: 1200,
        line_count: 50,
        content_hash: 'h1',
        last_indexed_at: '2026-01-01',
      },
      {
        id: '2',
        path: 'backend/app/main.py',
        language: 'Python',
        size_bytes: 3500,
        line_count: 120,
        content_hash: 'h2',
        last_indexed_at: '2026-01-01',
      },
      {
        id: '3',
        path: '.gitignore',
        language: null,
        size_bytes: 200,
        line_count: 10,
        content_hash: 'h3',
        last_indexed_at: '2026-01-01',
      },
    ];

    it('normalizes backslashes, leading ./, whitespace and case', () => {
      expect(normalizeFilePath(' .\\src\\components\\Header.tsx ')).toBe('src/components/header.tsx');
      expect(normalizeFilePath('./backend/app/main.py')).toBe('backend/app/main.py');
      expect(normalizeFilePath('')).toBe('');
      expect(normalizeFilePath(null)).toBe('');
    });

    it('finds file by exact match', () => {
      const match = findMatchingRepositoryFile(mockFiles, 'src/components/Header.tsx');
      expect(match?.id).toBe('1');
    });

    it('finds file case-insensitively with leading slash or ./', () => {
      const match = findMatchingRepositoryFile(mockFiles, './SRC/components/header.tsx');
      expect(match?.id).toBe('1');
    });

    it('finds file by segment suffix match', () => {
      const match = findMatchingRepositoryFile(mockFiles, 'app/main.py');
      expect(match?.id).toBe('2');
    });

    it('returns undefined for invalid or non-existent path', () => {
      expect(findMatchingRepositoryFile(mockFiles, 'does/not/exist.ts')).toBeUndefined();
      expect(findMatchingRepositoryFile(mockFiles, '')).toBeUndefined();
      expect(findMatchingRepositoryFile([], 'src/components/Header.tsx')).toBeUndefined();
    });
  });
});
