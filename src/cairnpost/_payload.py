from __future__ import annotations

from ._events import EventEmail, EventReceived, EventSuppression, EventType, WebhookEvent
from ._read import Fields, Misshapen, fields, flag, maybe_text, maybe_time, part, text, texts, time

# The types that are about an email that was sent.
_ABOUT_AN_EMAIL = frozenset(
    {
        EventType.DELIVERED,
        EventType.DELIVERY_DELAYED,
        EventType.BOUNCED,
        EventType.COMPLAINED,
        EventType.FAILED,
    }
)


def _read_email(o: Fields) -> EventEmail:
    return EventEmail(
        id=text(o, "email_id"),
        from_=text(o, "from"),
        to=texts(o, "to"),
        created_at=maybe_time(o, "created_at"),
        code=maybe_text(o, "code"),
        reason=maybe_text(o, "reason"),
        bounce_type=part(o, "bounce", lambda b: maybe_text(b, "type")),
        suppressed=flag(o, "suppressed"),
    )


def read_event(id: str, body: object) -> WebhookEvent:
    """Reads a signed body. Misshapen is a body that cannot be read."""
    if not isinstance(body, dict):
        raise Misshapen
    kind, at = text(body, "type"), time(body, "created_at")
    if kind == "":
        raise Misshapen
    data = fields(body.get("data"))
    if kind == EventType.RECEIVED:
        # It is about an email that came, and must say which and for whom.
        received = EventReceived(
            id=text(data, "inbound_id"),
            from_=text(data, "from"),
            to=texts(data, "to"),
            received_at=maybe_time(data, "received_at"),
        )
        if received.id == "" or not received.to:
            raise Misshapen
        return WebhookEvent(id=id, type=kind, at=at, received=received)
    email: EventEmail | None
    try:
        email = _read_email(data)
    except Misshapen:
        email = None
    if email is not None and (email.id == "" or not email.to):
        email = None
    # An event about an email must say which: one that does not is
    # refused here, not handed on with nothing in it. A type this client
    # does not know is passed on with what could be read of it.
    if email is None and kind in _ABOUT_AN_EMAIL:
        raise Misshapen
    if kind == EventType.BOUNCED and (email is None or not email.bounce_type):
        raise Misshapen
    suppression: EventSuppression | None = None
    if kind == EventType.ADDRESS_SUPPRESSED:
        # It must say which address and why, as an email's event must say
        # which email.
        suppression = EventSuppression(
            domain=text(data, "domain"), address=text(data, "address"), reason=text(data, "reason")
        )
        if not (suppression.domain and suppression.address and suppression.reason):
            raise Misshapen
    return WebhookEvent(id=id, type=kind, at=at, email=email, suppression=suppression)
