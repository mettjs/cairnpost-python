from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ._read import count, fields, maybe_text, maybe_time, text, time


class DeliveryState(StrEnum):
    """States of a webhook delivery."""

    #: Owed; it will be tried, or tried again.
    PENDING = "pending"
    #: The endpoint took it.
    DELIVERED = "delivered"
    #: Every try was used up.
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class Delivery:
    """One webhook owed to one endpoint, and how it went."""

    #: Also the webhook's id as its receiver sees it (`WebhookEvent.id`).
    id: str
    #: The email the webhook is about; None for one about no email sent
    #: (`address.suppressed`, `email.received`).
    email_id: str | None
    #: The received email the webhook is about, for an `email.received`.
    inbound_id: str | None
    #: The webhook's type (see `EventType`).
    type: str
    #: One of `DeliveryState`.
    state: str
    attempts: int
    #: The endpoint's status at the last try; None for none.
    last_status: int | None
    #: Why the last try failed; None if it did not.
    last_failure: str | None
    created_at: datetime
    attempted_at: datetime | None
    delivered_at: datetime | None
    next_attempt_at: datetime | None


def read_delivery(v: object) -> Delivery:
    o = fields(v)
    return Delivery(
        id=text(o, "id"),
        email_id=maybe_text(o, "email_id"),
        inbound_id=maybe_text(o, "inbound_id"),
        type=text(o, "type"),
        state=text(o, "state"),
        attempts=count(o, "attempts"),
        last_status=count(o, "last_status") or None,
        last_failure=maybe_text(o, "last_failure"),
        created_at=time(o, "created_at"),
        attempted_at=maybe_time(o, "attempted_at"),
        delivered_at=maybe_time(o, "delivered_at"),
        next_attempt_at=maybe_time(o, "next_attempt_at"),
    )
