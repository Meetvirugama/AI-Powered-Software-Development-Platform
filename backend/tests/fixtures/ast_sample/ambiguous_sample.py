"""Sample fixture containing ambiguous symbol definitions across different scopes."""

def format_data(item):
    """Top-level format_data function."""
    return str(item).strip()


class PrimaryProcessor:
    """Primary data processor."""

    def __init__(self, prefix: str = "item"):
        self.prefix = prefix

    def format_data(self, item):
        """Method format_data in PrimaryProcessor."""
        return f"{self.prefix}:{item.upper()}"

    def process(self, item):
        return self.format_data(item)


class SecondaryProcessor:
    """Secondary data processor."""

    def format_data(self, item):
        """Method format_data in SecondaryProcessor."""
        return f"secondary:{item.lower()}"
