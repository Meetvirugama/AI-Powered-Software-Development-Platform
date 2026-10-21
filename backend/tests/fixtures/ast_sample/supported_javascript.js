const path = require('path');
const { format_string } = require('./local_module');

const DEFAULT_PORT = 8080;

function startServer(port) {
    const activePort = port || DEFAULT_PORT;
    return `Server listening on ${activePort}`;
}

class RequestHandler {
    handleRequest(req) {
        return { status: 200, message: "OK" };
    }
}

module.exports = {
    startServer,
    RequestHandler,
};
