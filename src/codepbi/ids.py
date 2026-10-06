import secrets
import uuid


def hex_id(length: int = 20) -> str:
    """Matches the folder-name id style PBI Desktop generates for pages/visuals (e.g. '953e48bb4f7e4f9a82ce')."""
    return secrets.token_hex(length // 2)


def guid() -> str:
    return str(uuid.uuid4())
