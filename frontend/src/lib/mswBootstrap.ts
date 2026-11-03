/**
 * MSW Bootstrap Helper
 *
 * Controls development-only browser mock service worker initialization.
 * Enforces explicit opt-in (VITE_ENABLE_MSW === 'true' in DEV mode).
 * Production builds never enable browser MSW regardless of environment variables.
 */

export interface MswEnvironment {
  DEV?: boolean;
  PROD?: boolean;
  MODE?: string;
  VITE_ENABLE_MSW?: string;
}

export function shouldEnableMsw(env: MswEnvironment = import.meta.env): boolean {
  return Boolean(env?.DEV && env?.VITE_ENABLE_MSW === 'true');
}

export async function enableMocking(env: MswEnvironment = import.meta.env): Promise<boolean> {
  if (shouldEnableMsw(env)) {
    try {
      const { worker } = await import('../mocks/browser');
      await worker.start({
        onUnhandledRequest: 'bypass',
      });
      if (env.DEV) {
        console.warn(
          '[MSW] Mock Service Worker enabled for development (VITE_ENABLE_MSW=true). Live API calls may be intercepted.'
        );
      }
      return true;
    } catch (err) {
      console.error('MSW failed to start:', err);
      return false;
    }
  }
  return false;
}

