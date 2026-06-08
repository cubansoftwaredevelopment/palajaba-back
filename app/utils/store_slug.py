import re
import unicodedata
from urllib.parse import unquote


def store_name_to_slug(store_name: str) -> str:
    normalized = unicodedata.normalize("NFD", store_name.strip().lower())
    without_marks = "".join(
        character for character in normalized if unicodedata.category(character) != "Mn"
    )
    slug = re.sub(r"[^a-z0-9]+", "-", without_marks)
    return slug.strip("-")


def decode_store_ref(value: str) -> str:
    return unquote(value.strip())
