from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EventType(StrEnum):
    """Types of webhook CairnPost sends."""

    DELIVERED = "email.delivered"
    DELIVERY_DELAYED = "email.delivery_delayed"
    BOUNCED = "email.bounced"
    COMPLAINED = "email.complained"
    FAILED = "email.failed"
    #: Tells of an address put on the suppression list because of a bounce
    #: or a complaint about an email the server has no record of. It is
    #: about no email: `suppression` says which address. An email on
    #: record says the same in its own webhook (`event.email.suppressed`).
    ADDRESS_SUPPRESSED = "address.suppressed"
    #: Tells of an email that came for an address of a sending domain. It
    #: is about no email that was sent: `received` says who from, who for,
    #: and the id to read it by. It never says what the email says.
    RECEIVED = "email.received"
    #: Sent when an endpoint is tried out. It is about no email.
    TEST = "webhook.test"


class BounceType(StrEnum):
    """Types of bounce, in an `email.bounced` webhook."""

    #: The address will never take mail. It is the only one that says the
    #: address is at fault.
    PERMANENT = "Permanent"
    #: The receiving server refused for good, for a reason that is the
    #: sender's (a failed signature, a policy, a blocklist). The address
    #: may be perfectly good.
    POLICY = "Policy"
    #: Refused for now.
    TRANSIENT = "Transient"


@dataclass(frozen=True, slots=True, kw_only=True)
class EventEmail:
    """The email a webhook is about. Never its subject or body."""

    id: str
    from_: str
    #: The one address the event is about, also when the email went to
    #: several.
    to: list[str]
    #: When the email was made. Set for every type this client knows;
    #: only one it does not know can leave it out.
    created_at: datetime | None
    #: The receiving server's status ("5.1.1").
    code: str | None
    #: The mail provider's short name for what happened.
    reason: str | None
    #: Set for `email.bounced`: one of `BounceType`.
    bounce_type: str | None
    #: Says that, with this event, the address is on the sending domain's
    #: suppression list: CairnPost will refuse to send to it from there
    #: until the suppression is lifted.
    suppressed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class EventSuppression:
    """The address an `address.suppressed` webhook is about.

    The server will refuse to send to it from that sending domain until
    the suppression is lifted.
    """

    domain: str
    address: str
    #: "bounce" (the address refused an email for good) or "complaint"
    #: (its owner marked one as spam).
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EventReceived:
    """The email an `email.received` webhook is about.

    Read what it says with `received.get` and an admin key.
    """

    #: The received email's id.
    id: str
    #: Who it came from, as the sending server said: "" for a mail
    #: server's own notice, such as a bounce.
    from_: str
    #: The address it came for.
    to: list[str]
    received_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class WebhookEvent:
    """A webhook from CairnPost, verified."""

    #: Names the webhook. It is the same on every try of it, so a receiver
    #: that may be sent one twice tells by this.
    id: str
    #: One of `EventType`; a type this client does not know is passed
    #: through as it is.
    type: str
    #: When the event happened.
    at: datetime
    #: The email the event is about; None for `webhook.test`,
    #: `address.suppressed` and `email.received`.
    email: EventEmail | None = None
    #: Set for `address.suppressed`.
    suppression: EventSuppression | None = None
    #: Set for `email.received`.
    received: EventReceived | None = None
