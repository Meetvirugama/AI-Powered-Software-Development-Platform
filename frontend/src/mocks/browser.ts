/**
 * MSW browser setup.
 * Started in development only via main.tsx.
 */
import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';

export const worker = setupWorker(...handlers);
