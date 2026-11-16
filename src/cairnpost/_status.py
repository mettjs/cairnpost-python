from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._message import FileInfo, read_file
from ._read import (
    Fields,
    Misshapen,
    count,
    fields,
    flag,
    has,
    items,
    maybe_text,
    maybe_time,
    part,
    text,
    text_map,
    texts,
    time,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Quota:
    """The mail provider's sending allowance and how much is used."""

    limit: int
    #: The span the limit counts over, such as "day".
    per: str
    used: int
    #: Says the allowance is used up.
    over: bool
    resets_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Limits:
    """What the server knows of how much more it may send."""

    #: The mail provider in use.
    driver: str
    #: None for a provider that has no allowance to tell.
    quota: Quota | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Health:
    """Whether the server can do its work."""

    #: "ok", or "unavailable" when its database does not answer.
    status: str
    driver: str
    version: str
    #: Whether delivery events are being read: "reading", "failing" or
    #: "off". Mail still goes while any part is failing.
    events: str
    #: Whether webhooks are being sent: "sending", "failing" or "off".
    webhooks: str
    #: Whether old records are being deleted: "running", "failing" or "off".
    pruning: str
    #: Whether the emails asked for ahead of time are being sent:
    #: "sending", "failing" or "off".
    scheduled: str
    #: Whether the server takes the emails that come for its domains'
    #: addresses: "on" or "off".
    inbound: str

    @property
    def ok(self) -> bool:
        """Says the server is up and its database answers."""
        return self.status == "ok"


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedEmail:
    """An email a development server kept instead of sending."""

    id: str
    at: datetime
    from_: str
    from_name: str | None
    to: list[str]
    cc: list[str]
    bcc: list[str]
    reply_to: str | None
    subject: str
    html: str | None
    text: str | None
    headers: dict[str, str]
    #: What files it had; a captured email holds no file's bytes.
    attachments: list[FileInfo]


def _read_quota(q: Fields) -> Quota:
    return Quota(
        limit=count(q, "limit"),
        per=text(q, "per"),
        used=count(q, "used"),
        over=flag(q, "over"),
        resets_at=maybe_time(q, "resets_at"),
    )


def read_limits(v: object) -> Limits:
    o = has(fields(v), "driver")
    return Limits(driver=text(o, "driver"), quota=part(o, "quota", _read_quota))


def read_health(v: object) -> Health:
    o = fields(v)
    h = Health(
        status=text(o, "status"),
        driver=text(o, "driver"),
        version=text(o, "version"),
        events=text(o, "events"),
        webhooks=text(o, "webhooks"),
        pruning=text(o, "pruning"),
        scheduled=text(o, "scheduled"),
        inbound=text(o, "inbound"),
    )
    # Anything that does not say how it is is not a CairnPost server.
    if h.status == "":
        raise Misshapen
    return h


def _read_one(v: object) -> CapturedEmail:
    o = fields(v)
    return CapturedEmail(
        id=text(o, "id"),
        at=time(o, "at"),
        from_=text(o, "from"),
        from_name=maybe_text(o, "from_name"),
        to=texts(o, "to"),
        cc=texts(o, "cc"),
        bcc=texts(o, "bcc"),
        reply_to=maybe_text(o, "reply_to"),
        subject=text(o, "subject"),
        html=maybe_text(o, "html"),
        text=maybe_text(o, "text"),
        headers=text_map(o, "headers") or {},
        attachments=items(o, "attachments", read_file),
    )


def read_captured(v: object) -> list[CapturedEmail]:
    return items(has(fields(v), "data"), "data", _read_one)
