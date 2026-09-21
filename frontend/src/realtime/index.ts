/**
 * Real-time event abstraction using SSE.
 * Connects to the backend SSE endpoint and triggers TanStack Query invalidation
 * or other callbacks when events arrive.
 */
export class RealtimeClient {
  private eventSource: EventSource | null = null;
  private endpoint: string;

  constructor(endpoint: string) {
    this.endpoint = endpoint;
  }

  connect() {
    if (this.eventSource) return;

    this.eventSource = new EventSource(this.endpoint, { withCredentials: true });

    this.eventSource.onmessage = (event) => {
      // Parse event and invalidate queries or update state as needed
      // console.log('SSE Event:', event.data);
    };

    this.eventSource.onerror = (error) => {
      console.error('SSE Error:', error);
      this.disconnect();
      // Logic for retry can be implemented here
    };
  }

  disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}

export const realtimeClient = new RealtimeClient(`${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/events`);
