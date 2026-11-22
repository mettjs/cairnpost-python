"""Every call the client has, each sending what the shared cases say it sends."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from cairnpost import Attachment, CairnPost, Email

AN_EMAIL = "01a20155-8f2b-76c9-bc68-b2e7bdcd4c56"
AN_ENDPOINT = "01a20155-8f42-7fcf-bf8a-120e8aa42bf6"
A_DELIVERY = "01a20155-8f59-7f5a-ba31-4cfbc0f1e864"
A_TEMPLATE = "01a20155-9b2b-7b2a-8f83-ef332546a80b"
A_RECEIVED = "01a20155-8f58-7e44-b3a0-1fe938616579"

WELCOME = Email(
    from_="App <app@example.com>",
    to=["ana@example.org"],
    cc=["ben@example.org"],
    reply_to="help@example.com",
    subject="Welcome",
    text="Hello.",
    html="<p>Hello.</p>",
    headers={"X-Entity-Ref": "42"},
    attachments=[Attachment(filename="a.txt", content=b"hello", content_type="text/plain")],
    idempotency_key="welcome-42",
)
TWO = [
    Email(from_="app@example.com", to=[to], subject="Welcome", text="Hello.")
    for to in ["ana@example.org", "ben@example.org"]
]

#: The name the shared cases know a call by, and the call that sends what
#: calls.json says it sends. Each name is also the call's own here.
ASKING: dict[str, Callable[[CairnPost], object]] = {
    "health": lambda c: c.health(),
    "limits": lambda c: c.limits(),
    "captured": lambda c: c.captured(),
    "emails.send": lambda c: c.emails.send(WELCOME),
    "emails.send_batch": lambda c: c.emails.send_batch(TWO, idempotency_key="batch-7"),
    "emails.get": lambda c: c.emails.get(AN_EMAIL),
    "emails.cancel": lambda c: c.emails.cancel(AN_EMAIL),
    "emails.reschedule": lambda c: c.emails.reschedule(AN_EMAIL, datetime(2030, 1, 31, 8, tzinfo=UTC)),
    "emails.file": lambda c: c.emails.file(AN_EMAIL, 1),
    "suppressions.list": lambda c: c.suppressions.list(domain="example.com", limit=2),
    "suppressions.add": lambda c: c.suppressions.add("example.com", "gone@example.org", "asked"),
    "suppressions.lift": lambda c: c.suppressions.lift("example.com", "gone@example.org"),
    "suppressions.lift_all": lambda c: c.suppressions.lift_all("example.com", "bounce"),
    "webhooks.create": lambda c: c.webhooks.create(
        "https://app.example.com/hooks/cairnpost",
        events=["email.bounced", "email.complained"],
        description="Bounces",
    ),
    "webhooks.list": lambda c: c.webhooks.list(),
    "webhooks.get": lambda c: c.webhooks.get(AN_ENDPOINT),
    "webhooks.update": lambda c: c.webhooks.update(
        AN_ENDPOINT, description="Bounces and complaints", enabled=False
    ),
    "webhooks.delete": lambda c: c.webhooks.delete(AN_ENDPOINT),
    "webhooks.rotate_secret": lambda c: c.webhooks.rotate_secret(AN_ENDPOINT),
    "webhooks.resume": lambda c: c.webhooks.resume(AN_ENDPOINT),
    "webhooks.test": lambda c: c.webhooks.test(AN_ENDPOINT),
    "webhooks.deliveries": lambda c: c.webhooks.deliveries(AN_ENDPOINT, state="pending", limit=2),
    "webhooks.retry_delivery": lambda c: c.webhooks.retry_delivery(AN_ENDPOINT, A_DELIVERY),
    "templates.create": lambda c: c.templates.create(
        name="welcome", subject="Hello {{name}}", text="Hi {{name}}.", defaults={"name": "there"}
    ),
    "templates.list": lambda c: c.templates.list("example.com"),
    "templates.get": lambda c: c.templates.get(A_TEMPLATE),
    "templates.update": lambda c: c.templates.update(A_TEMPLATE, subject="Welcome {{name}}"),
    "templates.delete": lambda c: c.templates.delete(A_TEMPLATE),
    "received.list": lambda c: c.received.list(limit=2),
    "received.get": lambda c: c.received.get(A_RECEIVED),
    "received.raw": lambda c: c.received.raw(A_RECEIVED),
    "received.file": lambda c: c.received.file(A_RECEIVED, 1),
    "received.delete": lambda c: c.received.delete(A_RECEIVED),
}

#: These read no answer of their own: they walk a call that is there.
WALKS = {"suppressions.all", "webhooks.all_deliveries", "received.all"}


def ask(name: str) -> Callable[[CairnPost], object]:
    """The call the shared cases know by a name."""
    if name not in ASKING:
        raise AssertionError(f'the cases name "{name}", which is no call of this client')
    return ASKING[name]


def calls_of(where: str, calls: Any) -> list[str]:
    """The names of the calls a case is about: those it lists, or every call there is."""
    if calls == "all":
        return list(ASKING)
    if isinstance(calls, list) and calls and all(isinstance(name, str) for name in calls):
        return calls
    raise AssertionError(f"{where}: its calls are {calls!r}")
