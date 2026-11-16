from __future__ import annotations

from builtins import list as List  # a method here is named list
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from ._answer import place_of, reading
from ._message import FileInfo, read_file
from ._pages import LARGEST_PAGE, Page, paging, read_page, walk
from ._read import (
    Fields,
    Misshapen,
    a_strangers_time,
    count,
    fields,
    flag,
    items,
    maybe_text,
    part,
    text,
    texts,
    time,
)
from ._transport import Call, Transport


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceivedHeader:
    """One header of a received email."""

    name: str
    value: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceivedContent:
    """What a received email says.

    A stranger wrote it: treat every part as untrusted, and never show
    `html` as a page.
    """

    subject: str
    from_: str
    to: List[str]
    cc: List[str]
    reply_to: str | None
    message_id: str | None
    #: When the email says it was written; None when it does not say.
    date: datetime | None
    text: str | None
    html: str | None
    headers: List[ReceivedHeader]
    #: Its files in the order they came: a file's place, for `file`,
    #: counts from 1.
    attachments: List[FileInfo]
    #: Says some of it could not be read as it was written (a charset the
    #: server does not know, a broken part): what is here may be
    #: incomplete. `raw` has all of it.
    partial: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Received:
    """An email that came for an address of a sending domain.

    The server keeps it for a time.
    """

    id: str
    #: The address it came for.
    to: str
    #: Who it came from, as the sending server said: None for a mail
    #: server's own notice, such as a bounce. Neither this nor `to` is
    #: what the email says of itself: see `content`.
    from_: str | None
    received_at: datetime
    #: When the server stops showing it, and deletes it soon after.
    kept_until: datetime
    #: How long it is as it came, in bytes.
    size: int
    #: The email as it reads; None in a list.
    content: ReceivedContent | None


def _read_header(v: object) -> ReceivedHeader:
    h = fields(v)
    return ReceivedHeader(name=text(h, "name"), value=text(h, "value"))


def _read_content(o: Fields) -> ReceivedContent:
    return ReceivedContent(
        subject=text(o, "subject"),
        from_=text(o, "from"),
        to=texts(o, "to"),
        cc=texts(o, "cc"),
        reply_to=maybe_text(o, "reply_to"),
        message_id=maybe_text(o, "message_id"),
        date=a_strangers_time(o, "date"),
        text=maybe_text(o, "text"),
        html=maybe_text(o, "html"),
        headers=items(o, "headers", _read_header),
        attachments=items(o, "attachments", read_file),
        partial=flag(o, "partial"),
    )


def _read_received(v: object) -> Received:
    o = fields(v)
    r = Received(
        id=text(o, "id"),
        to=text(o, "to"),
        from_=maybe_text(o, "from"),
        received_at=time(o, "received_at"),
        kept_until=time(o, "kept_until"),
        size=count(o, "size"),
        content=part(o, "content", _read_content),
    )
    if r.id == "":
        raise Misshapen
    return r


class ReceivedEmails:
    """The emails that came for the server's domains' addresses, while it keeps them.

    Every call needs an admin key.
    """

    __slots__ = ("_t",)

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def list(self, *, limit: int | None = None, after: str | None = None) -> Page[Received]:
        """Answers a page of the emails that came and are kept, newest first.

        Each is without its `content`. All of them, or its sending
        domain's for a key bound to one. `limit` is the page's size: the
        server's own (50) when left out, 200 at most. `after` is the
        `next` of the page before.
        """
        answer = self._t.read_json(Call(method="GET", path=("inbound",), query=paging(limit, after)))
        return reading(answer, lambda v: read_page(v, _read_received))

    def all(self) -> Iterator[Received]:
        """Walks every email that came and is kept, newest first, a page at a time.

        It ends at the first error, which it raises.
        """
        return walk(lambda after: self.list(limit=LARGEST_PAGE, after=after))

    def get(self, id: str) -> Received:
        """Answers one email that came, with what it says.

        `is_not_found` says there is none: the id is wrong, it came for
        another sending domain, or its time is up.
        """
        return reading(self._t.read_json(Call(method="GET", path=("inbound", id))), _read_received)

    def raw(self, id: str) -> bytes:
        """Answers a received email as it came, every byte: what a mail program opens."""
        return self._t.read_bytes(Call(method="GET", path=("inbound", id, "raw")))

    def file(self, id: str, place: int) -> bytes:
        """Reads what one of a received email's files holds.

        `place` counts its files from 1, in the order of
        `content.attachments`.
        """
        return self._t.read_bytes(Call(method="GET", path=("inbound", id, "attachments", place_of(place))))

    def delete(self, id: str) -> None:
        """Deletes a received email before its time."""
        self._t.empty(Call(method="DELETE", path=("inbound", id)))
