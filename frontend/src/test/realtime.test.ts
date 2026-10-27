import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { RealtimeClient } from '../realtime/index';
import { REPO_UPDATED } from '../realtime/events';

describe('RealtimeClient (F-09)', () => {
  let mockEventSourceInstances: any[] = [];

  beforeEach(() => {
    vi.useFakeTimers();
    mockEventSourceInstances = [];

    // Mock global EventSource
    (globalThis as any).EventSource = vi.fn().mockImplementation(function (url: string) {
      const instance = {
        url,
        onopen: null as any,
        onmessage: null as any,
        onerror: null as any,
        close: vi.fn(),
      };
      mockEventSourceInstances.push(instance);
      return instance;
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    delete (globalThis as any).EventSource;
  });

  it('connects to SSE endpoint and dispatches parsed event envelopes', () => {
    const client = new RealtimeClient();
    const handler = vi.fn();

    client.connect({ [REPO_UPDATED]: handler });

    expect(mockEventSourceInstances.length).toBe(1);
    const es = mockEventSourceInstances[0];

    // Trigger onopen
    es.onopen();
    expect(client.isConnected).toBe(true);
    expect(client.connectionStatus).toBe('CONNECTED');

    // Trigger onmessage with repository.updated payload
    es.onmessage({
      data: JSON.stringify({
        type: REPO_UPDATED,
        data: { repository_id: 'test-repo-123' },
      }),
    });

    expect(handler).toHaveBeenCalledWith({ repository_id: 'test-repo-123' });

    client.disconnect();
    expect(es.close).toHaveBeenCalled();
    expect(client.isConnected).toBe(false);
  });

  it('reconnects with exponential backoff upon error', () => {
    const client = new RealtimeClient();
    const onError = vi.fn();

    client.connect({}, onError);
    expect(mockEventSourceInstances.length).toBe(1);
    const es1 = mockEventSourceInstances[0];

    // Simulate error
    es1.onerror(new Event('error'));
    expect(onError).toHaveBeenCalled();
    expect(client.connectionStatus).toBe('RECONNECTING');

    // Advance timers for backoff delay
    vi.advanceTimersByTime(2000);

    // A second EventSource should have been instantiated for reconnection
    expect(mockEventSourceInstances.length).toBe(2);

    client.disconnect();
    expect(client.connectionStatus).toBe('DISCONNECTED');
  });
});
