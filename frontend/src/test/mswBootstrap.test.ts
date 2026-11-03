import { describe, it, expect, vi, beforeEach } from 'vitest';
import { shouldEnableMsw, enableMocking } from '../lib/mswBootstrap';

describe('MSW Bootstrap (P0.5)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('shouldEnableMsw', () => {
    it('returns false by default in development when VITE_ENABLE_MSW is undefined', () => {
      expect(shouldEnableMsw({ DEV: true, VITE_ENABLE_MSW: undefined })).toBe(false);
    });

    it('returns false in development when VITE_ENABLE_MSW is empty or false', () => {
      expect(shouldEnableMsw({ DEV: true, VITE_ENABLE_MSW: '' })).toBe(false);
      expect(shouldEnableMsw({ DEV: true, VITE_ENABLE_MSW: 'false' })).toBe(false);
    });

    it('returns false for arbitrary non-true values', () => {
      expect(shouldEnableMsw({ DEV: true, VITE_ENABLE_MSW: '1' })).toBe(false);
      expect(shouldEnableMsw({ DEV: true, VITE_ENABLE_MSW: 'yes' })).toBe(false);
    });

    it('returns true ONLY when DEV is true and VITE_ENABLE_MSW is strictly "true"', () => {
      expect(shouldEnableMsw({ DEV: true, VITE_ENABLE_MSW: 'true' })).toBe(true);
    });

    it('returns false in production even if VITE_ENABLE_MSW is "true"', () => {
      expect(
        shouldEnableMsw({
          DEV: false,
          PROD: true,
          VITE_ENABLE_MSW: 'true',
        })
      ).toBe(false);
    });
  });

  describe('enableMocking', () => {
    it('does not start worker when MSW is disabled', async () => {
      const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const enabled = await enableMocking({ DEV: true, VITE_ENABLE_MSW: 'false' });
      expect(enabled).toBe(false);
      expect(consoleWarnSpy).not.toHaveBeenCalled();
    });

    it('does not start worker in production even if VITE_ENABLE_MSW is "true"', async () => {
      const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const enabled = await enableMocking({ DEV: false, PROD: true, VITE_ENABLE_MSW: 'true' });
      expect(enabled).toBe(false);
      expect(consoleWarnSpy).not.toHaveBeenCalled();
    });
  });
});

