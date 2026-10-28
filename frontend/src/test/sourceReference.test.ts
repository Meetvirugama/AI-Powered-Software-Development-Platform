import { describe, it, expect } from 'vitest';
import { isSourceReferenceEqual, formatSourceRange } from '../lib/sourceReference';
import type { SourceReference } from '../types/analysis';

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
});
