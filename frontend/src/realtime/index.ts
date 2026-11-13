/**
 * RealtimeClient — SSE connection manager with exponential backoff & Last-Event-ID resume (F-09 & Issue 1).
 *
 * Wraps the browser's EventSource API. Dispatches events to handlers, tracks the latest
 * Redis Stream cursor (`Last-Event-ID` / `lastEventId`), and automatically reconnects
 * with jittered exponential backoff and cursor resume when connectivity drops.
 */
import { NAMED_SSE_EVENTS, type SseEnvelope, type SseHandlers } from "./events";
import { API_BASE_URL } from "../services/api";

const SSE_ENDPOINT = `${API_BASE_URL.replace(/\/+$/, "")}/events`;

export type SseConnectionStatus =
  | "DISCONNECTED"
  | "CONNECTING"
  | "CONNECTED"
  | "RECONNECTING"
  | "ERROR";

export class RealtimeClient {
  private eventSource: EventSource | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private retryCount = 0;
  private readonly maxRetries = 8;
  private readonly baseDelayMs = 1000;
  private readonly maxDelayMs = 20000;
  private handlers: SseHandlers = {};
  private onErrorCallback?: (event: Event) => void;
  private status: SseConnectionStatus = "DISCONNECTED";
  private statusListeners = new Set<(status: SseConnectionStatus) => void>();
  private lastEventId: string | null = null;
  private channel: string | null = null;

  /**
   * Open the SSE connection and register event handlers.
   *
   * @param handlers Map of event type -> handler function.
   * @param onError Optional callback invoked when the connection errors out.
   * @param options Optional initial lastEventId cursor or channel name.
   */
  connect(
    handlers: SseHandlers = {},
    onError?: (event: Event) => void,
    options?: { lastEventId?: string | null; channel?: string | null }
  ) {
    this.handlers = handlers;
    this.onErrorCallback = onError;
    if (options?.lastEventId !== undefined) {
      this.lastEventId = options.lastEventId;
    }
    if (options?.channel !== undefined) {
      this.channel = options.channel;
    }

    if (this.eventSource) return;

    this.setStatus("CONNECTING");
    this.initEventSource();
  }

  private buildEndpointUrl(): string {
    const params: string[] = [];
    if (this.lastEventId) {
      params.push(`last_event_id=${encodeURIComponent(this.lastEventId)}`);
    }
    if (this.channel) {
      params.push(`channel=${encodeURIComponent(this.channel)}`);
    }
    if (params.length === 0) {
      return SSE_ENDPOINT;
    }
    const sep = SSE_ENDPOINT.includes("?") ? "&" : "?";
    return `${SSE_ENDPOINT}${sep}${params.join("&")}`;
  }

  private dispatchMessage(event: MessageEvent, fallbackEventType?: string) {
    if (typeof event.lastEventId === "string" && event.lastEventId.trim()) {
      this.lastEventId = event.lastEventId.trim();
    }

    let envelope: SseEnvelope;
    try {
      envelope = JSON.parse(event.data as string) as SseEnvelope;
    } catch {
      return;
    }

    if (typeof envelope.id === "string" && envelope.id.trim()) {
      this.lastEventId = envelope.id.trim();
    }

    const eventType = (envelope.type || fallbackEventType || "") as keyof SseHandlers;
    const handler = this.handlers[eventType];
    if (handler) {
      (handler as (payload: unknown) => void)(envelope.data);
    }
  }

  private initEventSource() {
    if (typeof EventSource === "undefined") {
      this.setStatus("ERROR");
      return;
    }

    try {
      const endpointUrl = this.buildEndpointUrl();
      this.eventSource = new EventSource(endpointUrl, { withCredentials: true });

      this.eventSource.onopen = () => {
        this.retryCount = 0;
        this.setStatus("CONNECTED");
      };

      this.eventSource.onmessage = (event: MessageEvent) => {
        this.dispatchMessage(event);
      };

      if (typeof this.eventSource.addEventListener === "function") {
        for (const evtName of NAMED_SSE_EVENTS) {
          this.eventSource.addEventListener(evtName, (evt: Event) => {
            this.dispatchMessage(evt as MessageEvent, evtName);
          });
        }
      }

      this.eventSource.onerror = (event: Event) => {
        this.onErrorCallback?.(event);
        this.cleanupEventSource();

        if (this.status === "DISCONNECTED") return;

        if (this.retryCount < this.maxRetries) {
          this.setStatus("RECONNECTING");
          const delay = Math.min(
            this.baseDelayMs * Math.pow(1.5, this.retryCount),
            this.maxDelayMs
          );
          const jitter = delay * 0.2 * (Math.random() - 0.5);
          const actualDelay = Math.max(500, Math.round(delay + jitter));
          this.retryCount += 1;

          this.reconnectTimer = setTimeout(() => {
            if (this.status !== "DISCONNECTED") {
              this.initEventSource();
            }
          }, actualDelay);
        } else {
          this.setStatus("ERROR");
        }
      };
    } catch {
      this.setStatus("ERROR");
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
    this.setStatus("DISCONNECTED");
  }

  getLastEventId(): string | null {
    return this.lastEventId;
  }

  setLastEventId(id: string | null) {
    this.lastEventId = id ? id.trim() : null;
  }

  get isConnected(): boolean {
    return this.status === "CONNECTED";
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
