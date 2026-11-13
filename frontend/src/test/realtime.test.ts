import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { RealtimeClient } from '../realtime/index';
import {
  REPO_UPDATED,
  CHAT_TOKEN,
  TOOL_INVOCATION_PROGRESS,
  MCP_NOTIFICATION,
  SSE_GAP_DETECTED,
} from '../realtime/events';

describe('RealtimeClient (F-09 & Issue 1 SSE Redis Streams)', () => {
  let mockEventSourceInstances: any[] = [];

  beforeEach(() => {
    vi.useFakeTimers();
    mockEventSourceInstances = [];

    (globalThis as any).EventSource = vi.fn().mockImplementation(function (url: string) {
      const listeners: Record<string, Array<(evt: any) => void>> = {};
      const instance = {
        url,
        onopen: null as any,
        onmessage: null as any,
        onerror: null as any,
        close: vi.fn(),
        addEventListener: vi.fn((evtName: string, cb: (evt: any) => void) => {
          listeners[evtName] = listeners[evtName] || [];
          listeners[evtName].push(cb);
        }),
        emitNamed: (evtName: string, eventObj: any) => {
          for (const cb of listeners[evtName] || []) {
            cb(eventObj);
          }
        },
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

    es.onopen();
    expect(client.isConnected).toBe(true);
    expect(client.connectionStatus).toBe('CONNECTED');

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

  it('reconnects with exponential backoff and preserves Last-Event-ID cursor on reconnect', () => {
    const client = new RealtimeClient();
    const onError = vi.fn();
    const chatHandler = vi.fn();
    const toolHandler = vi.fn();
    const mcpHandler = vi.fn();
    const gapHandler = vi.fn();

    client.connect(
      {
        [CHAT_TOKEN]: chatHandler,
        [TOOL_INVOCATION_PROGRESS]: toolHandler,
        [MCP_NOTIFICATION]: mcpHandler,
        [SSE_GAP_DETECTED]: gapHandler,
      },
      onError
    );
    expect(mockEventSourceInstances.length).toBe(1);
    const es1 = mockEventSourceInstances[0];
    es1.onopen();

    // Emit chat token with Redis Stream ID
    es1.onmessage({
      lastEventId: '1763000100-1',
      data: JSON.stringify({
        id: '1763000100-1',
        type: CHAT_TOKEN,
        data: { session_id: 's1', message_id: 'm1', token: 'Hello', index: 0, done: false },
      }),
    });
    expect(chatHandler).toHaveBeenCalledWith({
      session_id: 's1',
      message_id: 'm1',
      token: 'Hello',
      index: 0,
      done: false,
    });
    expect(client.getLastEventId()).toBe('1763000100-1');

    // Emit tool progress via named SSE event
    es1.emitNamed(TOOL_INVOCATION_PROGRESS, {
      lastEventId: '1763000100-2',
      data: JSON.stringify({
        id: '1763000100-2',
        type: TOOL_INVOCATION_PROGRESS,
        data: { task_id: 't1', call_id: 'c1', tool_name: 'repo_read_file', stage: 'progress', progress_pct: 50 },
      }),
    });
    expect(toolHandler).toHaveBeenCalledWith({
      task_id: 't1',
      call_id: 'c1',
      tool_name: 'repo_read_file',
      stage: 'progress',
      progress_pct: 50,
    });
    expect(client.getLastEventId()).toBe('1763000100-2');

    // Simulate disconnect error and verify reconnect URL includes last_event_id=1763000100-2
    es1.onerror(new Event('error'));
    expect(onError).toHaveBeenCalled();
    expect(client.connectionStatus).toBe('RECONNECTING');

    vi.advanceTimersByTime(2000);
    expect(mockEventSourceInstances.length).toBe(2);
    const es2 = mockEventSourceInstances[1];
    expect(es2.url).toContain('last_event_id=1763000100-2');

    client.disconnect();
    expect(client.connectionStatus).toBe('DISCONNECTED');
  });
});
