from reader import read_text_safely
assert read_text_safely('/non/existent/path/123.txt', default='missing') == 'missing'
