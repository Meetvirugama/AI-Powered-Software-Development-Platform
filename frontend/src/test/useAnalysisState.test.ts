import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAnalysisState } from '../hooks/useAnalysisState';

describe('useAnalysisState (F-05)', () => {
  it('maintains isolated state for each feature', () => {
    const { result } = renderHook(() => useAnalysisState('explain'));

    expect(result.current.activeFeature).toBe('explain');
    expect(result.current.currentStatus).toBe('IDLE');

    // Start explain
    act(() => {
      result.current.startAnalysis('explain', { type: 'file', path: 'src/main.py' });
    });

    expect(result.current.currentStatus).toBe('RUNNING');
    expect(result.current.states.explain.status).toBe('RUNNING');
    // Other features remain IDLE
    expect(result.current.states.bugs.status).toBe('IDLE');
    expect(result.current.states.tests.status).toBe('IDLE');
    expect(result.current.states.review.status).toBe('IDLE');

    // Switch to bugs
    act(() => {
      result.current.setActiveFeature('bugs');
    });

    // Current status reflects bugs (IDLE), not explain
    expect(result.current.activeFeature).toBe('bugs');
    expect(result.current.currentStatus).toBe('IDLE');
  });

  it('drops stale responses when file target changed during flight (F-05 race protection)', () => {
    const { result } = renderHook(() => useAnalysisState('explain'));

    // Request initiated for file A
    act(() => {
      result.current.startAnalysis('explain', { type: 'file', path: 'src/file_a.py' });
    });

    // User switches to file B
    act(() => {
      result.current.resetFileFeatures('src/file_b.py');
      result.current.startAnalysis('explain', { type: 'file', path: 'src/file_b.py' });
    });

    // Delayed response arrives for file A
    act(() => {
      result.current.completeAnalysis(
        'explain',
        { purpose: 'Old response for File A' },
        { type: 'file', path: 'src/file_a.py' }
      );
    });

    // File A's response is dropped because current target is file B!
    expect(result.current.states.explain.result).toBeNull();
    expect(result.current.states.explain.status).toBe('RUNNING');

    // Correct response arrives for file B
    act(() => {
      result.current.completeAnalysis(
        'explain',
        { purpose: 'Response for File B' },
        { type: 'file', path: 'src/file_b.py' }
      );
    });

    expect(result.current.states.explain.status).toBe('COMPLETED');
    expect(result.current.states.explain.result?.purpose).toBe('Response for File B');
  });

  it('reopens feature from history and sets active feature and result', () => {
    const { result } = renderHook(() => useAnalysisState());

    act(() => {
      result.current.reopenFeature(
        'bugs',
        { findings: [{ id: 'f-1', title: 'Bug found' }], total_findings: 1 },
        { type: 'file', path: 'src/app.py' },
        'run-reopened-123'
      );
    });

    expect(result.current.activeFeature).toBe('bugs');
    expect(result.current.currentStatus).toBe('COMPLETED');
    expect(result.current.states.bugs.runId).toBe('run-reopened-123');
    expect(result.current.states.bugs.result?.total_findings).toBe(1);
  });

  it('drops stale errors when file target changed during flight', () => {
    const { result } = renderHook(() => useAnalysisState('bugs'));

    // Request initiated for file A
    act(() => {
      result.current.startAnalysis('bugs', { type: 'file', path: 'src/old_file.py' });
    });

    // User switches to file B
    act(() => {
      result.current.resetFileFeatures('src/new_file.py');
      result.current.startAnalysis('bugs', { type: 'file', path: 'src/new_file.py' });
    });

    // Error arrives for old file A
    act(() => {
      result.current.failAnalysis(
        'bugs',
        { message: 'AST parsing error on old file', code: 'PARSE_ERROR' },
        { type: 'file', path: 'src/old_file.py' }
      );
    });

    // Stale error is ignored; status for new file remains RUNNING
    expect(result.current.states.bugs.status).toBe('RUNNING');
    expect(result.current.states.bugs.error).toBeNull();
  });

  it('handles cancellation error code cleanly', () => {
    const { result } = renderHook(() => useAnalysisState('tests'));

    act(() => {
      result.current.startAnalysis('tests', { type: 'file', path: 'src/calc.py' });
    });

    act(() => {
      result.current.failAnalysis(
        'tests',
        { message: 'Request was cancelled.', code: 'REQUEST_CANCELLED' },
        { type: 'file', path: 'src/calc.py' }
      );
    });

    expect(result.current.states.tests.status).toBe('FAILED');
    expect(result.current.states.tests.error).toBe('Request was cancelled.');
    expect(result.current.states.tests.errorCode).toBe('REQUEST_CANCELLED');
  });
});
