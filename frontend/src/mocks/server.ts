/**
 * MSW Node Server configuration for Unit & Integration Tests (Vitest).
 */

import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);
