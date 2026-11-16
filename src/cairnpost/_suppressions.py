from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ._answer import reading
from ._pages import LARGEST_PAGE, Page, paging, read_page, walk
from ._read import count, fields, flag, has, maybe_text, text, time
from ._transport import Call, Transport


class Reason(StrEnum):
    """Why an address is suppressed."""

    #: A receiving server refused it for good.
    BOUNCE = "bounce"
    #: Its owner marked an email as spam.
    COMPLAINT = "complaint"
    #: Put there by hand.
    MANUAL = "manual"


@dataclass(frozen=True, slots=True, kw_only=True)
class Suppression:
    """An address CairnPost will not send to from a domain."""

    #: The sending domain it holds for.
    domain: str
    address: str
    #: One of `Reason`.
    reason: str
    #: The email whose bounce or complaint caused it; None when there is
    #: none, or its record has been deleted.
    email_id: str | None
    note: str | None
    created_at: datetime


def _read_suppression(v: object) -> Suppression:
    o = fields(v)
    return Suppression(
        domain=text(o, "domain"),
        address=text(o, "address"),
        reason=text(o, "reason"),
        email_id=maybe_text(o, "email_id"),
        note=maybe_text(o, "note"),
        created_at=time(o, "created_at"),
    )


class Suppressions:
    """The addresses not sent to. Every call needs an admin key."""

    __slots__ = ("_t",)

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def list(
        self, *, domain: str | None = None, limit: int | None = None, after: str | None = None
    ) -> Page[Suppression]:
        """Answers one page of the addresses not sent to, in order of domain and address.

        `domain` narrows to one sending domain. `limit` is the page's
        size: the server's own (50) when left out, 200 at most. `after` is
        the `next` of the page before.
        """
        query = {**paging(limit, after), "domain": domain or None}
        answer = self._t.read_json(Call(method="GET", path=("suppressions",), query=query))
        return reading(answer, lambda v: read_page(v, _read_suppression))

    def all(self, domain: str | None = None) -> Iterator[Suppression]:
        """Walks every suppression of a sending domain (left out for all), a page at a time.

        It ends at the first error, which it raises.
        """
        # The largest page the server gives: fewer calls for a long list.
        return walk(lambda after: self.list(domain=domain, limit=LARGEST_PAGE, after=after))

    def add(self, domain: str, address: str, note: str | None = None) -> bool:
        """Stops sending to an address from a sending domain.

        The note is optional. It answers False when the address was
        suppressed already, in which case nothing changed.
        """
        body = {"domain": domain, "address": address}
        if note:
            body["note"] = note
        answer = self._t.read_json(Call(method="POST", path=("suppressions",), body=body))
        return reading(answer, lambda v: flag(has(fields(v), "added"), "added"))

    def lift(self, domain: str, address: str) -> None:
        """Lets an address be sent to again from a sending domain.

        `is_not_found` says it was not suppressed.
        """
        k = Call(method="POST", path=("suppressions", "lift"), body={"domain": domain, "address": address})
        reading(self._t.read_json(k), lambda v: has(fields(v), "lifted"))

    def lift_all(self, domain: str, reason: str | None = None) -> int:
        """Lifts every suppression of a sending domain, and answers how many.

        With a `reason` (one of `Reason`), only those of that reason.
        """
        body: dict[str, object] = {"domain": domain, "all": True}
        if reason:
            body["reason"] = str(reason)
        answer = self._t.read_json(Call(method="POST", path=("suppressions", "lift"), body=body))
        return reading(answer, lambda v: count(has(fields(v), "lifted"), "lifted"))
