from __future__ import annotations

import json


def _whole(text: str) -> int | float:
    """A whole number as it is written.

    Python reads no int of more digits than a limit it sets. Such a
    number is still JSON, and the other clients read it, so it is read
    here as the nearest number there is.
    """
    try:
        return int(text)
    except ValueError:
        return float(text)


def _no_number(name: str) -> object:
    """NaN and Infinity are not JSON, though Python's decoder takes them."""
    raise ValueError


def parse(raw: bytes) -> tuple[bool, object]:
    """Reads JSON; says False when it is none.

    The decoder's own error holds the text it was given, so it is not let
    out, nor left behind another error.
    """
    try:
        return True, json.loads(raw.decode("utf-8"), parse_int=_whole, parse_constant=_no_number)
    except (ValueError, RecursionError):
        return False, None
