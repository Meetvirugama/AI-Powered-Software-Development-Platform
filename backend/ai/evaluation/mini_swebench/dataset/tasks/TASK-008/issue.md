# Use safe get with fallback for nested configuration

Nested dictionary access conf['database']['port'] causes KeyError when missing.
