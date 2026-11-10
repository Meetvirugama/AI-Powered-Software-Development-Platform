/**
 * Mock Service Worker Handler Aggregator.
 */

import { taskHandlers } from './task';
import { memoryHandlers } from './memory';

export const handlers = [
  ...taskHandlers,
  ...memoryHandlers,
];

export { resetMockStore, getMockStore } from './task';
export { resetMockMemoryStore } from './memory';
