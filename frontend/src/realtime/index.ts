/**
 * RealtimeClient — SSE connection manager.
 *
 * Wraps the browser's EventSource API. Callers register event handlers via
 * connect(handlers) and the client dispatches incoming SSE messages to them.
 *
 * Design decisions:
 *  - The client does NOT hold references to QueryClient or Zustand. It is a
 *    pure event dispatcher. The caller (a React hook) bridges SSE → TanStack
 *    Query by passing handler callbacks that call queryClient.invalidateQueries.
 *  - Only one EventSource connection is open at a time. Calling connect()
 *    when already connected is a no-op.
 *  - SSE errors close the connection and call the optional onError callback.
 *    Reconnection strategy is left to the calling hook (e.g. via useEffect
 *    cleanup + re-mount), keeping this class simple.
 */
import type { SseEnvelope, SseHandlers } from './events';

const SSE_ENDPOINT =
  (import.meta.env.VITE_API_BASE_URL || '/api/v1') + '/events';

export class RealtimeClient {
  private eventSource: EventSource | null = null;

  /**
   * Open the SSE connection and register event handlers.
   *
   * @param handlers  Map of event type → handler function.
   * @param onError   Optional callback invoked when the connection errors out.
   */
  connect(handlers: SseHandlers = {}, onError?: (event: Event) => void) {
    if (this.eventSource) return; // already connected

    this.eventSource = new EventSource(SSE_ENDPOINT, { withCredentials: true });

    this.eventSource.onmessage = (event: MessageEvent) => {
      let envelope: SseEnvelope;
      try {
        envelope = JSON.parse(event.data as string) as SseEnvelope;
      } catch {
        // Malformed message — ignore silently.
        return;
      }

      const handler = handlers[envelope.type as keyof typeof handlers];
      if (handler) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (handler as (payload: any) => void)(envelope.data);
      }
    };

    this.eventSource.onerror = (event: Event) => {
      onError?.(event);
      this.disconnect();
    };
  }

  disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  get isConnected(): boolean {
    return this.eventSource !== null;
  }
}

export const realtimeClient = new RealtimeClient();
