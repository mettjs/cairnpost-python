from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ._read import Misshapen, fields, maybe_time, text, texts
from ._transport import header_safe


@dataclass(frozen=True, slots=True, kw_only=True)
class Attachment:
    """A file sent with an email."""

    #: The name its reader sees: a name, not a path.
    filename: str
    #: The file's bytes.
    content: bytes | bytearray | memoryview
    #: Its media type ("application/pdf"); left out, the server tells it
    #: from the filename.
    content_type: str | None = None
    #: Makes the file part of the HTML body, which shows it as "cid:" and
    #: this name; left out, it is a file beside the email.
    content_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class UseTemplate:
    """Names a template to make an email from, and gives its variables their values.

    A variable the template has a default for may be left out; one it has
    none for must be given, and a value for a variable it does not name is
    refused. A value is written as it is in the subject and the text, and
    escaped in the HTML.
    """

    name: str
    variables: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class Email:
    """One email, to one address or several."""

    #: The sender: "app@example.com" or "App <app@example.com>". (`from`
    #: is a word of Python's own.)
    from_: str
    #: Who the email is for: one address at least. `cc` are copied in the
    #: open, `bcc` without the others seeing them. No address twice; the
    #: server says how many an email may name in all (50 by default).
    to: Sequence[str]
    cc: Sequence[str] = ()
    bcc: Sequence[str] = ()
    reply_to: str | None = None
    #: Required, unless a `template` gives one.
    subject: str | None = None
    #: The bodies; at least one is required, unless a `template` gives them.
    html: str | None = None
    text: str | None = None
    #: Extra headers.
    headers: Mapping[str, str] = field(default_factory=dict)
    #: Files to send with it.
    attachments: Sequence[Attachment] = ()
    #: Makes the email from a template the server keeps, in place of
    #: `html` and `text`, which must then be left out. A `subject` given
    #: with it is used instead of the template's.
    template: UseTemplate | None = None
    #: Has the email sent at that time and not now: the server keeps it
    #: until then. It must have a zone, be a time to come, and be as far
    #: ahead as the server allows (30 days by default).
    scheduled_at: datetime | None = None
    #: Makes a repeated send one email: the same key with the same content
    #: answers the first one's id. Use one for anything that may be
    #: retried. It is remembered for a day by default. Printable ASCII,
    #: with no space at either end.
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Sent:
    """The server's answer to a send."""

    #: The email's id: one, however many addresses it went to.
    id: str
    #: The addresses it was not sent to, because they are on the sending
    #: domain's suppression list. Empty when it went to all. An email with
    #: nobody left in `to` or `cc` is an error instead
    #: (`recipient_suppressed`): a `bcc` alone is not sent.
    suppressed: list[str]
    #: When the email will be sent, for one asked for with `scheduled_at`:
    #: it waits, and nothing was sent yet. None for an email that was sent.
    scheduled_at: datetime | None = None


def _addresses(name: str, value: object) -> list[str]:
    # A lone address would otherwise be sent letter by letter.
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"cairnpost: {name} must be a list of addresses; nothing was sent")
    return list(value)


def wire_of(e: Email) -> dict[str, Any]:
    """An email as the server takes it.

    Only the fields it names, since it refuses any other. A field that
    holds nothing is left out.
    """
    w: dict[str, Any] = {"from": e.from_, "to": _addresses("to", e.to)}
    if e.cc:
        w["cc"] = _addresses("cc", e.cc)
    if e.bcc:
        w["bcc"] = _addresses("bcc", e.bcc)
    if e.reply_to:
        w["reply_to"] = e.reply_to
    w["subject"] = e.subject or ""
    if e.html:
        w["html"] = e.html
    if e.text:
        w["text"] = e.text
    if e.headers:
        w["headers"] = dict(e.headers)
    if e.attachments:
        w["attachments"] = [_file(f) for f in e.attachments]
    if e.scheduled_at is not None:
        w["scheduled_at"] = instant(e.scheduled_at)
    if e.template is not None:
        w["template"] = {"name": e.template.name}
        if e.template.variables:
            w["template"]["variables"] = dict(e.template.variables)
    return w


def _file(f: Attachment) -> dict[str, str]:
    if not isinstance(f.content, bytes | bytearray | memoryview):
        raise ValueError("cairnpost: an attachment's content must be bytes; nothing was sent")
    w = {"filename": f.filename, "content": base64.b64encode(f.content).decode("ascii")}
    if f.content_type:
        w["content_type"] = f.content_type
    if f.content_id:
        w["content_id"] = f.content_id
    return w


def instant(at: datetime) -> str:
    """A time as the server reads one."""
    # A time with no zone means one thing here and another on the server.
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("cairnpost: a time to send the email at must have a zone (tzinfo); nothing was sent")
    return at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def idempotency(key: str | None) -> dict[str, str]:
    """The header that makes a send safe to repeat; none for no key."""
    if key is None:
        return {}
    # A key a header cannot carry as it is would be dropped or changed on
    # the way, and the send would quietly not be idempotent. An empty one
    # is no key at all, where one was meant.
    if not header_safe(key):
        raise ValueError(
            "cairnpost: the idempotency_key must be printable ASCII, not empty, with no space at either end; "
            "nothing was sent"
        )
    return {"Idempotency-Key": key}


def read_sent(v: object, later: bool) -> Sent:
    """Reads the answer to one send.

    One with no id is not CairnPost's: whatever is at that address, the
    email is not known to have been sent. Nor is one that does not say an
    email asked for later waits: a server too old to know the field would
    have refused it.
    """
    o = fields(v)
    sent = Sent(
        id=text(o, "id"), suppressed=texts(o, "suppressed"), scheduled_at=maybe_time(o, "scheduled_at")
    )
    if sent.id == "" or (sent.scheduled_at is not None) != later:
        raise Misshapen
    return sent
