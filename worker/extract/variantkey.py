"""The one place a variant key is built.

A variant key is the lowercase string "<size>|<color>": exactly one "|", each
side stripped with inner whitespace collapsed, and "" when the variant has
neither a size nor a color. Everything that produces a key (learned paths, the
pinned-URL variant) goes through variant_key() so the same variant always gets
the same key. The rule matches assert_well_formed() in tests/test_extract.py.
"""

import re

_SPACE = re.compile(r"\s+")


def _part(value: str | None) -> str:
    # "|" is the separator, so it can never appear inside a part.
    return _SPACE.sub(" ", (value or "").replace("|", " ")).strip().lower()


def variant_key(size: str | None, color: str | None) -> str:
    """("XS", "Black") -> "xs|black"; ("XS", None) -> "xs|"; (None, None) -> ""."""
    s, c = _part(size), _part(color)
    return f"{s}|{c}" if (s or c) else ""


def is_well_formed(key: object) -> bool:
    """True for "" and for any string variant_key() could have produced."""
    if not isinstance(key, str):
        return False
    if key == "":
        return True
    if key.count("|") != 1:
        return False
    size, color = key.split("|")
    return variant_key(size, color) == key
