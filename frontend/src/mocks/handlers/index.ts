/**
 * Mock Service Worker Handler Aggregator.
 */

import { taskHandlers } from './task';

export const handlers = [
  ...taskHandlers,
];

export { resetMockStore, getMockStore } from './task';
