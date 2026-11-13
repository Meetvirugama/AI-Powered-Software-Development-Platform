import tempfile
from reader import read_text_safely
with tempfile.NamedTemporaryFile('w', delete=False) as tf:
    tf.write('hello')
    p = tf.name
assert read_text_safely(p) == 'hello'
