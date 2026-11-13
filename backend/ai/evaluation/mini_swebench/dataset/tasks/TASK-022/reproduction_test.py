from dedup import deduplicate_preserve_order
assert deduplicate_preserve_order(['c', 'a', 'b', 'a', 'c']) == ['c', 'a', 'b']
