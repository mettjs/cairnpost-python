from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from ._errors import TransportError
from ._read import Misshapen

T = TypeVar("T")


def reading(answer: object, read: Callable[[object], T]) -> T:
    """Runs a reader over an answer; one of another shape is not CairnPost's."""
    try:
        return read(answer)
    except Misshapen:
        pass
    # Raised out here, with nothing behind it, and without the answer left
    # in this frame for a traceback to show.
    del answer
    raise TransportError("not_cairnpost")


def place_of(place: int) -> str:
    """A file's place as a path takes it."""
    if isinstance(place, bool) or not isinstance(place, int) or place < 1:
        raise ValueError("cairnpost: a file's place counts from 1")
    return str(place)
