// JavaScript test fixture with structural defects for AST rule checking

function executeDynamic(userInput) {
    // AST-SEC-001: eval call
    return eval(userInput);
}

function silentErrorHandler() {
    // AST-EXC-001: empty catch block
    try {
        riskyOperation();
    } catch (e) {
    }
}
