from __future__ import annotations

from builtins import list as List  # a method here is named list
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime

from ._answer import reading
from ._deliveries import Delivery, read_delivery
from ._pages import LARGEST_PAGE, Page, paging, read_page, walk
from ._read import (
    Misshapen,
    count,
    fields,
    flag,
    has,
    items,
    maybe_text,
    maybe_time,
    named,
    text,
    texts,
    time,
)
from ._transport import Call, Transport


@dataclass(frozen=True, slots=True, kw_only=True)
class Webhook:
    """An endpoint: a URL CairnPost tells what becomes of emails."""

    id: str
    url: str
    #: The sending domain it hears about; None for every domain.
    domain: str | None
    #: The types it hears about (see `EventType`); empty for every type.
    events: List[str]
    description: str | None
    enabled: bool
    created_at: datetime
    #: Set while every try since then has failed.
    failing_since: datetime | None
    #: Set while the endpoint is paused: it failed every try for longer
    #: than the server allows. It is still owed everything that happens,
    #: and nothing is sent to it until `resume`.
    paused_at: datetime | None
    #: Set after `rotate_secret`: until then the server signs with the
    #: secret before as well as the new one. None when no older secret
    #: signs: none was changed lately, or the server is set to end an old
    #: secret at once.
    previous_secret_until: datetime | None
    #: The signing secret, for a `Verifier`. It is set only on the answers
    #: to `create` and `rotate_secret` and is never said again: keep it.
    secret: str | None

    def __repr__(self) -> str:
        # Without the secret: an endpoint printed or logged does not show it.
        return f"Webhook(id={self.id!r}, url={self.url!r}, enabled={self.enabled!r})"


@dataclass(frozen=True, slots=True, kw_only=True)
class WebhookTest:
    """How an endpoint answered a webhook sent to try it out."""

    #: Says the endpoint took it.
    delivered: bool
    #: The endpoint's HTTP status; None when it gave none.
    status: int | None
    #: Why it was not delivered: "timeout", "refused", "dns", "tls",
    #: "blocked", "status" or "other".
    failure: str | None


def _read_webhook(v: object) -> Webhook:
    o = fields(v)
    w = Webhook(
        id=text(o, "id"),
        url=text(o, "url"),
        domain=maybe_text(o, "domain"),
        events=texts(o, "events"),
        description=maybe_text(o, "description"),
        enabled=flag(o, "enabled"),
        created_at=time(o, "created_at"),
        failing_since=maybe_time(o, "failing_since"),
        paused_at=maybe_time(o, "paused_at"),
        previous_secret_until=maybe_time(o, "previous_secret_until"),
        secret=maybe_text(o, "secret"),
    )
    if w.id == "":
        raise Misshapen
    return w


def _read_test(v: object) -> WebhookTest:
    o = has(fields(v), "delivered")
    return WebhookTest(
        delivered=flag(o, "delivered"), status=count(o, "status") or None, failure=maybe_text(o, "failure")
    )


def _types(events: Sequence[str]) -> List[str]:
    # A lone type would otherwise be sent letter by letter.
    if isinstance(events, str):
        raise ValueError("cairnpost: events must be a list of types")
    return [str(e) for e in events]


class Webhooks:
    """The URLs told what becomes of emails. Every call needs an admin key."""

    __slots__ = ("_t",)

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def _one(self, k: Call) -> Webhook:
        return reading(self._t.read_json(k), _read_webhook)

    def create(
        self,
        url: str,
        *,
        domain: str | None = None,
        events: Sequence[str] = (),
        description: str | None = None,
    ) -> Webhook:
        """Has a URL told what becomes of emails.

        The answer carries the endpoint's signing `secret`, the only time
        it is said. `domain` narrows it to one sending domain, `events` to
        some types (see `EventType`); left out, it hears about all.
        """
        body: dict[str, object] = {"url": url}
        if domain:
            body["domain"] = domain
        if events:
            body["events"] = _types(events)
        if description:
            body["description"] = description
        return self._one(Call(method="POST", path=("webhooks",), body=body))

    def list(self) -> List[Webhook]:
        """Answers every endpoint."""
        answer = self._t.read_json(Call(method="GET", path=("webhooks",)))
        return reading(answer, lambda v: items(has(fields(v), "data"), "data", _read_webhook))

    def get(self, id: str) -> Webhook:
        """Answers one endpoint."""
        return self._one(Call(method="GET", path=("webhooks", id)))

    def update(
        self,
        id: str,
        *,
        url: str | None = None,
        events: Sequence[str] | None = None,
        description: str | None = None,
        enabled: bool | None = None,
    ) -> Webhook:
        """Changes an endpoint and answers it as it now is.

        What is left out is left as it is; what is given is changed to
        exactly that, so `enabled=False` disables it, `events=[]` makes it
        hear about every type and `description=""` leaves it none. A
        disabled endpoint is owed nothing new, and what it was owed waits.
        It does not resume a paused endpoint: `resume` does.
        """
        body: dict[str, object] = {}
        if url is not None:
            body["url"] = url
        if events is not None:
            body["events"] = _types(events)
        if description is not None:
            body["description"] = description
        if enabled is not None:
            body["enabled"] = enabled
        return self._one(Call(method="PATCH", path=("webhooks", id), body=body))

    def delete(self, id: str) -> None:
        """Removes an endpoint and all it was owed."""
        self._t.empty(Call(method="DELETE", path=("webhooks", id)))

    def test(self, id: str) -> WebhookTest:
        """Sends the endpoint a signed webhook of type `webhook.test` now, and answers how it went."""
        return reading(self._t.read_json(Call(method="POST", path=("webhooks", id, "test"))), _read_test)

    def rotate_secret(self, id: str) -> Webhook:
        """Gives the endpoint a new signing secret and answers the endpoint with it.

        It is the only time the secret is said. Until the
        `previous_secret_until` it answers (a day later, unless the server
        is set otherwise) the server signs each webhook with the old
        secret as well, so a `Verifier` made with either accepts it:
        change the application's secret within that time. No
        `previous_secret_until` means the old secret has already stopped
        signing: put the new one in place at once.

        If the call fails with no answer (a `TransportError`), the secret
        may have been changed and its new value lost. Call it again: that
        gives another new secret, and the one the application holds goes
        on signing for its own time meanwhile.
        """
        return self._one(Call(method="POST", path=("webhooks", id, "secret")))

    def resume(self, id: str) -> Webhook:
        """Ends an endpoint's pause and answers the endpoint.

        What it is owed is sent then, with what was given up while it was
        failing. One that is not paused is answered as it is.
        """
        return self._one(Call(method="POST", path=("webhooks", id, "resume")))

    def deliveries(
        self, id: str, *, state: str | None = None, limit: int | None = None, after: str | None = None
    ) -> Page[Delivery]:
        """Answers one page of what an endpoint was sent, newest first.

        `state` narrows to one state (one of `DeliveryState`). `limit` is
        the page's size: the server's own (50) when left out, 200 at most.
        `after` is the `next` of the page before.
        """
        query = {**paging(limit, after), "state": str(state) if state else None}
        answer = self._t.read_json(Call(method="GET", path=("webhooks", id, "deliveries"), query=query))
        return reading(answer, lambda v: read_page(v, read_delivery))

    def all_deliveries(self, id: str, state: str | None = None) -> Iterator[Delivery]:
        """Walks an endpoint's deliveries of one state (left out for all), newest first.

        A page at a time. It ends at the first error, which it raises.
        """
        return walk(lambda after: self.deliveries(id, state=state, limit=LARGEST_PAGE, after=after))

    def retry_delivery(self, id: str, delivery_id: str) -> None:
        """Has a webhook tried now.

        Once more if it was given up, or without waiting for its next try
        if it is pending.
        """
        k = Call(method="POST", path=("webhooks", id, "deliveries", delivery_id, "retry"))
        reading(self._t.read_json(k), lambda v: named(v, "state"))
