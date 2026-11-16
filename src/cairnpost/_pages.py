from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Generic, TypeVar

from ._read import fields, has, items, maybe_text

T = TypeVar("T")

#: The most a server gives in one page of any list: what reading a whole
#: list asks for.
LARGEST_PAGE = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class Page(Generic[T]):
    """One page of a list."""

    data: list[T]
    #: What to pass as `after` for the page that follows; None when this
    #: is the last.
    next: str | None


def paging(limit: int | None, after: str | None) -> dict[str, str | None]:
    """The query of a paged list."""
    return {"limit": str(limit) if limit and limit > 0 else None, "after": after or None}


def read_page(v: object, read: Callable[[object], T]) -> Page[T]:
    """Reads one page of a list whose items `read` reads."""
    o = has(fields(v), "data")
    return Page(data=items(o, "data", read), next=maybe_text(o, "next"))


def walk(page: Callable[[str | None], Page[T]]) -> Iterator[T]:
    """Goes through a paged list a page at a time.

    `page` answers the items after a cursor (None for the first page). It
    ends at the first error, which it raises.
    """
    after: str | None = None
    while True:
        got = page(after)
        yield from got.data
        # A cursor that does not move would be walked for ever.
        if got.next is None or got.next == after:
            return
        after = got.next
