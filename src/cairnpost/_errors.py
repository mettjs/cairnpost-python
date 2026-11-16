from __future__ import annotations

from typing import Literal

from ._codes import ErrorCode


class CairnPostError(Exception):
    """CairnPost saying no. `status` and `code` say what to do:

    - 422: the request is at fault and will never succeed. Do not retry.
      Under `sender_domain_not_ready` no email from that domain will be
      sent until the domain is set up with the mail provider.
    - 409 `invalid_idempotent_request`: the key was used for another
      email, which was sent. Do not retry.
    - 409 `concurrent_idempotent_requests`, 408 `request_incomplete`, 429,
      503: nothing was sent. Try again, after `retry_after` when it is set.
    - 502 `upstream_unknown`, and any 5xx or 408 that is not CairnPost's own: the
      email may have gone. Try again with the same idempotency key, and
      only with it. `may_have_sent` says which errors these are.
    """

    #: The HTTP status of the answer.
    status: int
    #: One of `ErrorCode`; None when the answer was not CairnPost's own (a
    #: proxy in between, say).
    code: ErrorCode | None
    #: CairnPost's sentence for a person: what is wrong and what to do. It
    #: never holds the email's subject or body; it may name the field, or
    #: the header, that was refused. None when the answer was not
    #: CairnPost's own, whatever that answer said.
    detail: str | None
    #: The email's id when the send got far enough to have one:
    #: `emails.get` then says what became of it. With
    #: `recipient_suppressed` it is an earlier try under the same
    #: idempotency key that may have gone.
    email_id: str | None
    #: How long the server asked to wait, in seconds; None when it did not
    #: say.
    retry_after: float | None

    def __init__(
        self,
        status: int,
        code: ErrorCode | None = None,
        detail: str | None = None,
        email_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.status = status
        self.code = code
        self.detail = detail or None
        self.email_id = email_id or None
        self.retry_after = retry_after or None
        super().__init__(self._sentence())

    def __reduce__(self) -> tuple[object, ...]:
        # So that it can be copied, and handed from one process to another.
        return (type(self), (self.status, self.code, self.detail, self.email_id, self.retry_after))

    def _sentence(self) -> str:
        if self.code is None and 300 <= self.status < 400:
            return (
                f"cairnpost: the server answered {self.status}, a redirect: "
                "the base URL must be the server's own address"
            )
        if self.code is None:
            return f"cairnpost: the server answered {self.status}, and not as CairnPost does"
        return f"cairnpost: {self.code.value} ({self.status}): {self.detail or ''}"

    @property
    def retryable(self) -> bool:
        """Says that the same request may succeed later.

        It does not say that nothing was sent: ask `may_have_sent` first,
        and when that is true retry only with the same idempotency key.
        """
        # A 408 is a request that did not arrive whole in time; may_have_sent
        # says what one from something in between leaves open.
        if self.code is ErrorCode.IDEMPOTENT_IN_FLIGHT or self.status in (408, 429):
            return True
        # Changed by others at the same time: read it and try again.
        if self.code is ErrorCode.CHANGED_MEANWHILE:
            return True
        if self.status == 409:
            return False
        return self.status >= 500


#: Why a call got no answer it could read.
TransportReason = Literal["network", "timeout", "too_large", "not_cairnpost"]

_REASONS: dict[TransportReason, str] = {
    "network": "the server was not reached, or the connection broke",
    "timeout": "the time given to the call ran out",
    "too_large": "the answer is larger than the client reads; see max_answer_bytes",
    "not_cairnpost": "the answer was not the JSON a CairnPost server gives",
}


class TransportError(Exception):
    """A call that got no answer it could read.

    The server was not reached, the connection broke, or the time ran
    out; `reason` says which. For a send it leaves open whether the email
    went.
    """

    reason: TransportReason
    #: The kind of error underneath, such as "ConnectionRefusedError";
    #: None when there was none. Only its name is kept. The error itself
    #: is not, as a cause or otherwise: it can hold the bytes the other
    #: side answered, and a peer that says back what it was sent would
    #: put the key and the email in it.
    cause_kind: str | None

    def __init__(self, reason: TransportReason, cause_kind: str | None = None) -> None:
        self.reason = reason
        self.cause_kind = cause_kind
        super().__init__(f"cairnpost: no answer from the server: {_REASONS[reason]}")

    def __reduce__(self) -> tuple[object, ...]:
        return (type(self), (self.reason, self.cause_kind))


class NotCapturingError(Exception):
    """`captured` asked of a server that delivers for real: it keeps no emails to show."""

    def __init__(self) -> None:
        super().__init__("cairnpost: the server delivers for real and keeps no captured emails")

    def __reduce__(self) -> tuple[object, ...]:
        return (type(self), ())


def may_have_sent(err: BaseException | None) -> bool:
    """Says whether, after a failed send, the email may have gone all the same.

    That is: the mail provider's answer was lost (`upstream_unknown`), the
    server's own answer never came or came from something in between (a
    proxy's 502), or the server failed after it began. Then the only safe
    retry is one with the same idempotency key. It is also true of a
    `recipient_suppressed` that carries an `email_id`: nothing was sent
    now, but that earlier try may have gone. That one is not to be
    retried, since the address is suppressed: read the `email_id` with
    `emails.get` instead. After any other error nothing was sent.
    """
    if isinstance(err, TransportError):
        return True
    if not isinstance(err, CairnPostError):
        return False
    # Refused now; but an id with it is an earlier try under the same key
    # whose answer never came.
    if err.code is ErrorCode.RECIPIENT_SUPPRESSED:
        return err.email_id is not None
    # CairnPost's own 408 is a request it never had whole. One from
    # something in between may come after the server took the email.
    if err.status == 408:
        return err.code is not ErrorCode.REQUEST_INCOMPLETE
    if err.status < 500:
        return False
    # The server's send does not stop when its answer is lost on the way,
    # so only its own word that nothing went counts.
    return err.code not in (
        ErrorCode.UPSTREAM_DOWN,
        ErrorCode.UNAVAILABLE,
        ErrorCode.NOT_STARTED,
        ErrorCode.SCHEDULE_FULL,
    )


def is_not_found(err: BaseException | None) -> bool:
    """Says that what was asked for is not there.

    No such email, endpoint, delivery or suppression, or not one this key
    may see. It is CairnPost's own word for it: a path the server does not
    have, or a 404 from something else at that address, is not this.
    `is_wrong_address` says those.

    It needs the server's own answer to arrive. Behind a proxy that puts
    its own page in place of every 404, no record is ever said to be
    missing and every such answer reads as a wrong address: have the proxy
    pass the server's error answers through.
    """
    return isinstance(err, CairnPostError) and err.status == 404 and err.code is ErrorCode.NOT_FOUND


def is_wrong_address(err: BaseException | None) -> bool:
    """Says that the request did not reach a route of CairnPost's.

    The server has nothing at that path or does not take that method
    there, or something else answered in its place with a 404, a 405 or a
    redirect. The base URL given to the client is most likely wrong;
    nothing was sent, and no record is known to be missing.
    """
    if not isinstance(err, CairnPostError):
        return False
    if err.code in (ErrorCode.ROUTE_NOT_FOUND, ErrorCode.METHOD_NOT_ALLOWED):
        return True
    if err.code is not None:
        return False
    return err.status in (404, 405) or 300 <= err.status < 400
