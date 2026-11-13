from pagination import get_page_items
data = list(range(100))
page = get_page_items(data, 1, 10)
assert len(page) == 10
assert page == list(range(10))
