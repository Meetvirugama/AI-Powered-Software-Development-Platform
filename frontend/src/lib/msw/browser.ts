/**
 * MSW v2 Browser Worker shim (`msw/browser`).
 */

import { setupServer } from './node';
import type { RequestHandler } from './index';

export interface SetupWorkerApi {
  start: (options?: Record<string, unknown>) => Promise<void>;
  stop: () => void;
  resetHandlers: (...nextHandlers: RequestHandler[]) => void;
  use: (...runtimeHandlers: RequestHandler[]) => void;
  listHandlers: () => readonly RequestHandler[];
}

export function setupWorker(...handlers: RequestHandler[]): SetupWorkerApi {
  const srv = setupServer(...handlers);
  return {
    async start() {
      srv.listen();
    },
    stop() {
      srv.close();
    },
    resetHandlers(...nextHandlers: RequestHandler[]) {
      srv.resetHandlers(...nextHandlers);
    },
    use(...runtimeHandlers: RequestHandler[]) {
      srv.use(...runtimeHandlers);
    },
    listHandlers() {
      return srv.listHandlers();
    },
  };
}
