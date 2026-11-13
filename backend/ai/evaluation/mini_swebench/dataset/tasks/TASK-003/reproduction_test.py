from tags import add_tag
t1 = add_tag('python')
t2 = add_tag('javascript')
assert t1 == ['python']
assert t2 == ['javascript']
