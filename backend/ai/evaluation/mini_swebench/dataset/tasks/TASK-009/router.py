def find_item_response(items_db: dict, item_id: str) -> dict:
    item = items_db.get(item_id)
    if item is None:
        return {'status': 404, 'error': 'Item not found'}
    return {'status': 200, 'data': item}
