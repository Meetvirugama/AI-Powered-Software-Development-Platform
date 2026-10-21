/**
 * Express HTTP server module for nodejs_sample.
 */
const http = require('http');
const { formatGreeting } = require('./utils');

const port = process.env.PORT || 3000;

const server = http.createServer((req, res) => {
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', service: 'nodejs_sample' }));
    return;
  }

  res.writeHead(200, { 'Content-Type': 'text/plain' });
  res.end(formatGreeting('World'));
});

module.exports = { server, port };
