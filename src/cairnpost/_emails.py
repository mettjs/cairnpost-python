from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from ._answer import place_of, reading
from ._batch import BatchResult, read_batch
from ._email import Email, Sent, idempotency, instant, read_sent, wire_of
from ._message import Message, read_message
from ._read import Misshapen, named
from ._transport import Call, Transport


def _a_message(v: object) -> Message:
    m = read_message(v)
    if m.id == "":
        raise Misshapen
    return m


class Emails:
    """Sending emails and reading what became of them."""

    __slots__ = ("_t",)

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def send(self, email: Email) -> Sent:
        """Sends an email and answers its id once the mail provider has taken it.

        On an error, see `CairnPostError` for what to do and
        `may_have_sent` for whether the email may have gone; the error's
        `email_id`, when set, can be read with `get`.
        """
        headers = idempotency(email.idempotency_key)
        answer = self._t.read_json(
            Call(method="POST", path=("emails",), headers=headers, body=wire_of(email))
        )
        return reading(answer, lambda v: read_sent(v, email.scheduled_at is not None))

    def send_batch(self, emails: Iterable[Email], *, idempotency_key: str | None = None) -> list[BatchResult]:
        """Sends several emails in one request and answers what became of each, in their order.

        The server checks every email before it sends any: one that could
        never be sent refuses the batch, and this raises that
        `CairnPostError` with nothing sent. An answer means the batch was
        taken, not that every email went: read each result, or count with
        `failed`.

        `idempotency_key` makes the batch safe to send again as it was:
        the server remembers each email under the key and its place, so a
        second try sends only what did not go. Send the same emails in the
        same order. An email's own `idempotency_key` is not used in a
        batch.

        After a `TransportError` any of the emails may have gone. Send the
        same batch again with the same `idempotency_key`, and only with it.
        """
        emails = list(emails)
        for i, e in enumerate(emails, start=1):
            if e.idempotency_key is not None:
                raise ValueError(
                    f"cairnpost: email {i} has an idempotency_key of its own: "
                    "a batch has one, given to send_batch; nothing was sent"
                )
        headers = idempotency(idempotency_key)
        body = [wire_of(e) for e in emails]
        answer = self._t.read_json(Call(method="POST", path=("emails", "batch"), headers=headers, body=body))
        return reading(answer, lambda v: read_batch(v, [e.scheduled_at is not None for e in emails]))

    def get(self, id: str) -> Message:
        """Answers what became of an email.

        A send key sees the emails it sent; an admin key sees any, or its
        sending domain's if it is bound to one. `is_not_found` says there
        is none: the id is wrong, another key's, or its record was deleted
        after the server's retention.
        """
        return reading(self._t.read_json(Call(method="GET", path=("emails", id))), _a_message)

    def cancel(self, id: str) -> None:
        """Ends the wait of an email that was asked for with `scheduled_at`.

        It will not be sent, and what it said is deleted from the server.
        The key that asked for the email may, and an admin key that may
        read it. An email that no longer waits (it is being sent, was sent
        or was cancelled) is a `CairnPostError` with the code
        `not_scheduled`.
        """
        # Only CairnPost's own word that it is cancelled counts.
        reading(
            self._t.read_json(Call(method="POST", path=("emails", id, "cancel"))), lambda v: named(v, "id")
        )

    def reschedule(self, id: str, at: datetime) -> None:
        """Gives an email that waits another time to be sent at.

        Its errors are those of `cancel`, and `validation_error` for a
        time it cannot be sent at.
        """
        k = Call(method="PATCH", path=("emails", id), body={"scheduled_at": instant(at)})
        reading(self._t.read_json(k), lambda v: named(v, "id"))

    def file(self, id: str, place: int) -> bytes:
        """Reads what one of an email's files held, as it was sent.

        `place` counts the email's files from 1, in the order of
        `content.attachments`. An admin key only. `is_not_found` says
        there is none: no email has this id, it has no file at that place,
        or the server does not keep it (`FileInfo.kept` says whether it
        does).
        """
        return self._t.read_bytes(Call(method="GET", path=("emails", id, "attachments", place_of(place))))
