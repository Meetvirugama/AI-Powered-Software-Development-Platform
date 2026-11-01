import { describe, it, expect } from 'vitest';
import { checkProposedTestPath } from '../lib/testPath';

describe('checkProposedTestPath', () => {
  const repoFiles = [
    { path: 'backend/tests/test_main.py' },
    { path: 'frontend/src/App.test.tsx' },
    { path: 'tests/unit/test_calc.py' },
  ];

  it('detects existing test paths case-insensitively with normalized slashes', () => {
    expect(checkProposedTestPath('backend/tests/test_main.py', repoFiles)).toBe('EXISTS');
    expect(checkProposedTestPath('Backend/Tests/test_main.py', repoFiles)).toBe('EXISTS');
    expect(checkProposedTestPath('backend\\tests\\test_main.py', repoFiles)).toBe('EXISTS');
    expect(checkProposedTestPath('./backend/tests/test_main.py', repoFiles)).toBe('EXISTS');
  });

  it('marks non-existent path as NEW', () => {
    expect(checkProposedTestPath('backend/tests/test_new_feature.py', repoFiles)).toBe('NEW');
    expect(checkProposedTestPath('tests/test_auth.py', repoFiles)).toBe('NEW');
  });

  it('returns UNKNOWN when not found and file list is incomplete (F-02)', () => {
    // File not in loaded page, but repository has more files: must be UNKNOWN, not NEW
    expect(checkProposedTestPath('backend/tests/test_unloaded.py', repoFiles, false, false, false)).toBe('UNKNOWN');
    // But if file exists in loaded page, it is EXISTS regardless of whether list is complete
    expect(checkProposedTestPath('backend/tests/test_main.py', repoFiles, false, false, false)).toBe('EXISTS');
  });

  it('returns UNKNOWN when files are loading, errored, or null', () => {
    expect(checkProposedTestPath('backend/tests/test_main.py', null)).toBe('UNKNOWN');
    expect(checkProposedTestPath('backend/tests/test_main.py', repoFiles, true)).toBe('UNKNOWN');
    expect(checkProposedTestPath('backend/tests/test_main.py', repoFiles, false, true)).toBe('UNKNOWN');
    expect(checkProposedTestPath('', repoFiles)).toBe('UNKNOWN');
    expect(checkProposedTestPath(null, repoFiles)).toBe('UNKNOWN');
  });
});
