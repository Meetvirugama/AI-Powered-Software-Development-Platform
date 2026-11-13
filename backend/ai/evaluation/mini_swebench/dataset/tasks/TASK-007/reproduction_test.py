from stripper import strip_html_tags
assert strip_html_tags('<b>Hello</b> <i>World</i>') == 'Hello World'
