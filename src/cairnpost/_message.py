from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ._read import (
    Fields,
    count,
    fields,
    flag,
    items,
    maybe_text,
    maybe_time,
    part,
    said,
    text,
    text_map,
    texts,
    time,
)


class State(StrEnum):
    """States of an email."""

    #: It waits to be sent at its time.
    SCHEDULED = "scheduled"
    #: It was to be sent later and was cancelled.
    CANCELLED = "cancelled"
    #: Handed to the provider, no answer yet.
    SENDING = "sending"
    #: The provider took it.
    SENT = "sent"
    #: The receiving server said "not now".
    DEFERRED = "deferred"
    #: The receiving server took it.
    DELIVERED = "delivered"
    #: The receiving server refused it.
    BOUNCED = "bounced"
    #: Its recipient marked it as spam.
    COMPLAINED = "complained"
    #: It was not sent.
    FAILED = "failed"
    #: The provider's answer was lost.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, kw_only=True)
class Recipient:
    """One address of an email and what became of it there."""

    address: str
    #: "to", "cc" or "bcc".
    kind: str
    state: str
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageEvent:
    """One thing that happened to an email."""

    #: "delivered", "deferred", "bounced", "complained" or "failed".
    type: str
    at: datetime
    #: The address it happened at.
    to: str | None
    #: Says, for a bounce, that the address will never take mail.
    permanent: bool
    #: The receiving server's status ("5.1.1").
    code: str | None
    #: The mail provider's short name for what happened.
    reason: str | None
    #: The receiving server's own sentence, kept only where content is.
    detail: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class FileInfo:
    """What an attachment was.

    `kept` says the server still holds what was in it, to be read back:
    while the email waits to be sent, and after that where the server
    keeps emails' files with what they said.
    """

    filename: str
    content_type: str
    content_id: str | None
    size: int
    kept: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Content:
    """What an email said, where the server is set to keep that."""

    from_name: str | None
    reply_to: str | None
    subject: str
    html: str | None
    text: str | None
    headers: dict[str, str]
    #: What files went with it.
    attachments: list[FileInfo]
    kept_until: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class Message:
    """What became of an email."""

    id: str
    from_: str
    #: The first address the email went to, and `state` what became of it
    #: there. `recipients` has every address with its own.
    to: str
    #: One of `State`; a state this client does not know is passed through.
    state: str
    recipients: list[Recipient]
    #: The addresses it was asked to go to and did not, being on the
    #: suppression list when it was sent.
    suppressed: list[str]
    #: When an email that waits will be sent, or would have been, had it
    #: not been cancelled; None for one that was sent.
    scheduled_at: datetime | None
    #: Why it was cancelled when nobody asked: "suppressed" (nobody it
    #: named in `to` or `cc` could be sent to any more), "key_revoked"
    #: (its API key was revoked while it waited) or "failed" (the server
    #: could not send it).
    reason: str | None
    created_at: datetime
    updated_at: datetime
    #: What happened to it after it was sent, oldest first.
    events: list[MessageEvent]
    #: What the email said: None unless the server keeps content, it is
    #: still within its time, and the key is an admin key.
    content: Content | None


def read_file(v: object) -> FileInfo:
    o = fields(v)
    return FileInfo(
        filename=text(o, "filename"),
        content_type=text(o, "content_type"),
        content_id=maybe_text(o, "content_id"),
        size=count(o, "size"),
        kept=flag(o, "kept"),
    )


def _read_content(o: Fields) -> Content:
    return Content(
        from_name=maybe_text(o, "from_name"),
        reply_to=maybe_text(o, "reply_to"),
        subject=text(o, "subject"),
        html=maybe_text(o, "html"),
        text=maybe_text(o, "text"),
        headers=text_map(o, "headers") or {},
        attachments=items(o, "attachments", read_file),
        kept_until=time(o, "kept_until"),
    )


def _read_recipient(v: object) -> Recipient:
    r = fields(v)
    return Recipient(
        address=text(r, "address"),
        kind=text(r, "kind"),
        state=text(r, "state"),
        updated_at=time(r, "updated_at"),
    )


def _read_event(v: object) -> MessageEvent:
    e = fields(v)
    return MessageEvent(
        type=text(e, "type"),
        at=time(e, "at"),
        to=maybe_text(e, "to"),
        permanent=flag(e, "permanent"),
        code=maybe_text(e, "code"),
        reason=maybe_text(e, "reason"),
        detail=maybe_text(e, "detail"),
    )


def read_message(v: object) -> Message:
    o = fields(v)
    return Message(
        id=said(o, "id"),
        from_=text(o, "from"),
        to=text(o, "to"),
        state=text(o, "state"),
        recipients=items(o, "recipients", _read_recipient),
        suppressed=texts(o, "suppressed"),
        scheduled_at=maybe_time(o, "scheduled_at"),
        reason=maybe_text(o, "reason"),
        created_at=time(o, "created_at"),
        updated_at=time(o, "updated_at"),
        events=items(o, "events", _read_event),
        content=part(o, "content", _read_content),
    )
