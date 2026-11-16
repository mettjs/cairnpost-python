from __future__ import annotations

import json


def parse(raw: bytes) -> tuple[bool, object]:
    """Reads JSON; says False when it is none.

    The decoder's own error holds the text it was given, so it is not let
    out, nor left behind another error.
    """
    try:
        return True, json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return False, None
