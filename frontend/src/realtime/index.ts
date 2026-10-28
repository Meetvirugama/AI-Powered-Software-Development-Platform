/**
 * RealtimeClient — SSE connection manager with exponential backoff (F-09).
 *
 * Wraps the browser's EventSource API. Dispatches events to handlers and automatically
 * reconnects with jittered exponential backoff when connectivity drops.
 */
import type { SseEnvelope, SseHandlers } from './events';

const SSE_ENDPOINT = '/api/v1/events';

export type SseConnectionStatus =
  | 'DISCONNECTED'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'RECONNECTING'
  | 'ERROR';

export class RealtimeClient {
  private eventSource: EventSource | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private retryCount = 0;
  private readonly maxRetries = 8;
  private readonly baseDelayMs = 1000;
  private readonly maxDelayMs = 20000;
  private handlers: SseHandlers = {};
  private onErrorCallback?: (event: Event) => void;
  private status: SseConnectionStatus = 'DISCONNECTED';
  private statusListeners = new Set<(status: SseConnectionStatus) => void>();

  /**
   * Open the SSE connection and register event handlers.
   *
   * @param handlers Map of event type → handler function.
   * @param onError Optional callback invoked when the connection errors out.
   */
  connect(handlers: SseHandlers = {}, onError?: (event: Event) => void) {
    this.handlers = handlers;
    this.onErrorCallback = onError;

    if (this.eventSource) return;

    this.setStatus('CONNECTING');
    this.initEventSource();
  }

  private initEventSource() {
    if (typeof EventSource === 'undefined') {
      this.setStatus('ERROR');
      return;
    }

    try {
      this.eventSource = new EventSource(SSE_ENDPOINT, { withCredentials: true });

      this.eventSource.onopen = () => {
        this.retryCount = 0;
        this.setStatus('CONNECTED');
      };

      this.eventSource.onmessage = (event: MessageEvent) => {
        let envelope: SseEnvelope;
        try {
          envelope = JSON.parse(event.data as string) as SseEnvelope;
        } catch {
          // Malformed message — ignore silently.
          return;
        }

        const handler = this.handlers[envelope.type as keyof typeof this.handlers];
        if (handler) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (handler as (payload: any) => void)(envelope.data);
        }
      };

      this.eventSource.onerror = (event: Event) => {
        this.onErrorCallback?.(event);
        this.cleanupEventSource();

        if (this.status === 'DISCONNECTED') return;

        if (this.retryCount < this.maxRetries) {
          this.setStatus('RECONNECTING');
          const delay = Math.min(
            this.baseDelayMs * Math.pow(1.5, this.retryCount),
            this.maxDelayMs
          );
          const jitter = delay * 0.2 * (Math.random() - 0.5);
          const actualDelay = Math.max(500, Math.round(delay + jitter));
          this.retryCount += 1;

          this.reconnectTimer = setTimeout(() => {
            if (this.status !== 'DISCONNECTED') {
              this.initEventSource();
            }
          }, actualDelay);
        } else {
          this.setStatus('ERROR');
        }
      };
    } catch {
      this.setStatus('ERROR');
    }
  }

  private cleanupEventSource() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.cleanupEventSource();
    this.setStatus('DISCONNECTED');
  }

  get isConnected(): boolean {
    return this.status === 'CONNECTED';
  }

  get connectionStatus(): SseConnectionStatus {
    return this.status;
  }

  onStatusChange(listener: (status: SseConnectionStatus) => void): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  private setStatus(newStatus: SseConnectionStatus) {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.statusListeners.forEach((listener) => {
        try {
          listener(newStatus);
        } catch {
          // Safe listener execution
        }
      });
    }
  }
}

export const realtimeClient = new RealtimeClient();
