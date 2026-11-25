import { useEffect, useState } from 'react';
import { realtimeClient, type SseConnectionStatus } from '../realtime/index';

/** Subscribe to global EventSource connection state for SSE-aware fallback polling. */
export function useSseConnectionStatus() {
  const [status, setStatus] = useState<SseConnectionStatus>(realtimeClient.connectionStatus);

  useEffect(() => {
    return realtimeClient.onStatusChange(setStatus);
  }, []);

  return {
    status,
    isConnected: status === 'CONNECTED',
  };
}
