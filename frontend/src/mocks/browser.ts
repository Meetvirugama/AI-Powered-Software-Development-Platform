/**
 * MSW Browser Worker configuration for Development Mode.
 *
 * Excluded from production builds via dynamic import guard in main.tsx.
 */

import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';

export const worker = setupWorker(...handlers);
