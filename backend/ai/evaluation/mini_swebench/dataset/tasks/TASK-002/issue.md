# Fix off-by-one error in pagination slice

get_page_items slice boundary is range(offset, offset + limit + 1) which returns limit + 1 items.
