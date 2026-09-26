/**
 * Utility functions for nodejs_sample.
 */

function formatGreeting(name) {
  return `Hello, ${name}! Welcome to the platform.`;
}

function calculateSum(a, b) {
  return a + b;
}

module.exports = {
  formatGreeting,
  calculateSum,
};
