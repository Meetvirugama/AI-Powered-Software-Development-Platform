def read_text_safely(path: str, default: str = '') -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return default
