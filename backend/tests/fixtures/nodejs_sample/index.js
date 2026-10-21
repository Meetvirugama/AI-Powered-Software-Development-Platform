/**
 * Entry point for nodejs_sample fixture.
 */
const { formatGreeting } = require('./utils');

function main() {
  const message = formatGreeting('Node.js Sample');
  console.log(message);
}

module.exports = { main };

if (require.main === module) {
  main();
}
