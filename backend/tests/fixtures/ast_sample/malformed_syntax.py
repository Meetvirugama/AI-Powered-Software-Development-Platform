# Intentionally malformed syntax for error-resilience tests
def broken_syntax_function(x, y):
    return x + %%% invalid syntax

class ValidClassAfterError:
    def valid_method(self):
        return True
