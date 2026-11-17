"""Readers for what a server answered.

An answer is not trusted to have the shape CairnPost gives: a field of
another kind than expected raises Misshapen, which the caller turns into
"not a CairnPost answer". A field that is missing, or null, reads as
nothing.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

T = TypeVar("T")

Fields = dict[str, Any]


class Misshapen(Exception):
    """An answer, or a part of one, that is not of the kind CairnPost gives."""


def fields(v: object) -> Fields:
    """The value as an object with fields; nothing reads as one with none."""
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise Misshapen
    return v


def has(o: Fields, *keys: str) -> Fields:
    """The object, once it is seen to name each of these fields.

    An answer that lacks what CairnPost always says ("{}" above all) is
    not CairnPost's, and must not read as "nothing" or "no".
    """
    for key in keys:
        if o.get(key) is None:
            raise Misshapen
    return o


def said(o: Fields, key: str) -> str:
    """A text that must be there: what names a record is never empty."""
    v = maybe_text(o, key)
    if v is None:
        raise Misshapen
    return v


def maybe_text(o: Fields, key: str) -> str | None:
    """A text field; None when it is not there or empty."""
    v = o.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise Misshapen
    return v or None


def text(o: Fields, key: str) -> str:
    """A text field; "" when it is not there."""
    return maybe_text(o, key) or ""


def count(o: Fields, key: str) -> int:
    """A whole number; 0 when it is not there."""
    v = o.get(key)
    if v is None:
        return 0
    # A yes or no is a number to Python, and is not one here.
    if isinstance(v, bool) or not isinstance(v, int):
        raise Misshapen
    return v


def flag(o: Fields, key: str) -> bool:
    """A yes or no; False when it is not there."""
    v = o.get(key)
    if v is None:
        return False
    if not isinstance(v, bool):
        raise Misshapen
    return v


# A time as CairnPost writes one: RFC 3339, with a zone.
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})", re.ASCII)

# How a time that was never set is written by a server in Go: the first
# instant of the year 1.
_UNSET = datetime(1, 1, 1, tzinfo=UTC)


def maybe_time(o: Fields, key: str) -> datetime | None:
    """A time, in UTC; None when it is not there, or was never set."""
    v = o.get(key)
    if v is None:
        return None
    if not isinstance(v, str) or not _STAMP.fullmatch(v):
        raise Misshapen
    at: datetime | None = None
    with contextlib.suppress(ValueError, OverflowError):
        at = datetime.fromisoformat(v).astimezone(UTC)
    if at is None:
        raise Misshapen
    return None if at == _UNSET else at


def a_strangers_time(o: Fields, key: str) -> datetime | None:
    """A time a stranger wrote, such as a received email's date.

    One that cannot be read (a year this language has no date for) is
    none, not an answer that is not CairnPost's.
    """
    try:
        return maybe_time(o, key)
    except Misshapen:
        return None


def time(o: Fields, key: str) -> datetime:
    """A time that must be there."""
    at = maybe_time(o, key)
    if at is None:
        raise Misshapen
    return at


def items(o: Fields, key: str, read: Callable[[object], T]) -> list[T]:
    """A list, each item read by `read`; empty when it is not there."""
    v = o.get(key)
    if v is None:
        return []
    if not isinstance(v, list):
        raise Misshapen
    return [read(item) for item in v]


def _a_text(item: object) -> str:
    if not isinstance(item, str):
        raise Misshapen
    return item


def texts(o: Fields, key: str) -> list[str]:
    """A list of texts; empty when it is not there."""
    return items(o, key, _a_text)


def text_map(o: Fields, key: str) -> dict[str, str] | None:
    """Names with a text each (an email's headers); None when not there."""
    v = o.get(key)
    if v is None:
        return None
    return {name: _a_text(value) for name, value in fields(v).items()}


def part(o: Fields, key: str, read: Callable[[Fields], T]) -> T | None:
    """A part that is an object, read by `read`; None when not there."""
    v = o.get(key)
    return None if v is None else read(fields(v))
