import re
def strip_html_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text)
