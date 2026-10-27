import { describe, it, expect } from 'vitest';
import { syncProgressFromStatus } from '../hooks/useRepositories';

describe('syncProgressFromStatus', () => {
  it('maps NOT_SYNCED to NOT_STARTED stage', () => {
    const progress = syncProgressFromStatus('NOT_SYNCED');
    expect(progress.stage).toBe('NOT_STARTED');
    expect(progress.isActive).toBe(false);
    expect(progress.isComplete).toBe(false);
    expect(progress.isFailed).toBe(false);
  });

  it('maps SYNCING to active CLONING stage', () => {
    const progress = syncProgressFromStatus('SYNCING');
    expect(progress.stage).toBe('CLONING');
    expect(progress.isActive).toBe(true);
    expect(progress.isComplete).toBe(false);
    expect(progress.isFailed).toBe(false);
  });

  it('maps SYNCED to READY stage with complete flag', () => {
    const progress = syncProgressFromStatus('SYNCED');
    expect(progress.stage).toBe('READY');
    expect(progress.isActive).toBe(false);
    expect(progress.isComplete).toBe(true);
    expect(progress.isFailed).toBe(false);
  });

  it('maps FAILED to FAILED stage with failed flag', () => {
    const progress = syncProgressFromStatus('FAILED');
    expect(progress.stage).toBe('FAILED');
    expect(progress.isActive).toBe(false);
    expect(progress.isComplete).toBe(false);
    expect(progress.isFailed).toBe(true);
  });
});
