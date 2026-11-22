from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import hmac
import re
import time
from collections.abc import Callable, Iterable
from typing import Any, Literal, Protocol

from ._bare import AROUND, bare
from ._events import WebhookEvent
from ._parse import parse
from ._payload import read_event
from ._read import Misshapen

#: How far a webhook's timestamp may be from now, in seconds.
DEFAULT_TOLERANCE = 300.0

#: Why a webhook was refused.
#:
#: - "secret": the signing secret is not one CairnPost gives.
#: - "unsigned": the request lacks the webhook's id, timestamp or
#:   signature headers.
#: - "signature": no signature matches. The request is not from CairnPost,
#:   was changed on the way, was signed for another endpoint, or the
#:   endpoint's secret was changed and this one no longer signs.
#: - "stale": the timestamp is too far from now. A webhook caught on the
#:   way and replayed later is refused by this.
#: - "payload": signed by CairnPost, but not a webhook this client can read.
WebhookRefusal = Literal["secret", "unsigned", "signature", "stale", "payload"]

_REFUSALS: dict[WebhookRefusal, str] = {
    "secret": "the signing secret must be the whsec_ value the server gave for the endpoint",
    "unsigned": "the webhook's signature headers are missing",
    "signature": "the webhook's signature does not match",
    "stale": "the webhook's timestamp is too far from now",
    "payload": "the webhook's body could not be read",
}


class RequestHeaders(Protocol):
    """A request's headers: a dict, or what a web framework or `http.server` gives."""

    def items(self) -> Iterable[tuple[str, Any]]: ...


class WebhookError(Exception):
    """A webhook that must not be trusted: answer it 400 or 401."""

    reason: WebhookRefusal

    def __init__(self, reason: WebhookRefusal) -> None:
        self.reason = reason
        super().__init__("cairnpost: " + _REFUSALS[reason])

    def __reduce__(self) -> tuple[object, ...]:
        return (type(self), (self.reason,))


# Base64 as the standard writes it: the decoder alone takes much else.
_BASE64 = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?", re.ASCII)
_SECONDS = re.compile(r"[0-9]{1,15}", re.ASCII)
#: What stands between two signatures.
_BETWEEN = re.compile(f"[{AROUND}]+")


def _decode(encoded: str) -> bytes | None:
    if encoded == "" or not _BASE64.fullmatch(encoded):
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


def _key_of(secret: object) -> bytes | None:
    """The key a signing secret holds; None when it is not one."""
    trimmed = bare(secret) if isinstance(secret, str) else ""
    return _decode(trimmed.removeprefix("whsec_")) if trimmed.startswith("whsec_") else None


class Verifier:
    """Checks that a webhook is CairnPost's."""

    __slots__ = ("_key", "_now", "_tolerance")

    def __init__(
        self, secret: str, *, tolerance: float = DEFAULT_TOLERANCE, now: Callable[[], float] | None = None
    ) -> None:
        """Makes a verifier for an endpoint's signing secret.

        That is the "whsec_..." value `webhooks.create` answered or, once
        the secret was changed, the one `webhooks.rotate_secret` did. Each
        is said only once. A space, a tab or a line break around it is
        dropped, as a value read from a file ends in a line break. Nothing
        else is: one with any other character around it (a byte order
        mark, say) is refused. `tolerance` is how far the timestamp may be
        from now, either way, in seconds; `now` is the clock.
        """
        # Read in a frame of its own, and refused from this one with the
        # secret gone from it: an error reporter shows the values of every
        # frame an error passed through.
        key = _key_of(secret)
        del secret
        if key is None:
            raise WebhookError("secret")
        self._key = key
        del key
        self._tolerance = tolerance if tolerance > 0 else DEFAULT_TOLERANCE
        self._now = now

    def __repr__(self) -> str:
        # Never the secret.
        return "<cairnpost Verifier>"

    def verify(self, headers: RequestHeaders, body: bytes | bytearray | memoryview | str) -> WebhookEvent:
        """Checks a webhook and reads it.

        `body` must be the request's body exactly as it arrived, as bytes
        or as the text they are: read it once, verify, and only then use
        it. A `WebhookError` means the request must not be trusted. A
        `TypeError` means the call itself is wrong (a body already parsed,
        say), whatever the request was.

        In the event answered, `email` is set for `email.delivered`,
        `email.delivery_delayed`, `email.bounced`, `email.complained` and
        `email.failed`, and `email.bounce_type` for `email.bounced`;
        `suppression` is set for `address.suppressed` and `received` for
        `email.received`. A type this client does not know
        is passed on with what could be read of it, which may be no `email`.

        CairnPost signs as Standard Webhooks and Svix do, and sends the
        headers under both names; either set is accepted.
        """
        # A mistake of the caller's is said as one, not as a forged webhook.
        if not callable(getattr(headers, "items", None)):
            raise TypeError("cairnpost: verify takes the request's headers as its first argument")
        if not isinstance(body, bytes | bytearray | memoryview | str):
            raise TypeError(
                "cairnpost: verify takes the request's body as it arrived, as text or bytes: "
                "not parsed, and not left out"
            )
        id, stamp, signatures = _signed(headers)
        if not id or not stamp or not signatures or not _SECONDS.fullmatch(stamp):
            raise WebhookError("unsigned")
        # A text no encoding can carry is not the body that was signed.
        raw = body.encode("utf-8", errors="replace") if isinstance(body, str) else bytes(body)
        try:
            about: bytes | None = f"{id}.{stamp}.".encode()
        except UnicodeEncodeError:
            # An id with half a character in it: no bytes were signed that
            # it could be, so no signature matches.
            about = None
        matched = False
        if about is not None:
            want = hmac.new(self._key, about + raw, hashlib.sha256).digest()
            for candidate in _BETWEEN.split(signatures):
                got = _decode(candidate.removeprefix("v1,")) if candidate.startswith("v1,") else None
                if got is not None and hmac.compare_digest(got, want):
                    matched = True
        if not matched:
            raise WebhookError("signature")
        # The time is checked after the signature: only a signed timestamp
        # means anything.
        # The clock is read now, not when the verifier was made.
        if abs((self._now or time.time)() - int(stamp)) > self._tolerance:
            raise WebhookError("stale")
        fine, wire = parse(raw)
        event: WebhookEvent | None = None
        if fine:
            with contextlib.suppress(Misshapen):
                event = read_event(id, wire)
        if event is None:
            # Raised out here, with nothing behind it: the error of reading
            # it holds the body.
            raise WebhookError("payload")
        return event


def _signed(headers: RequestHeaders) -> tuple[str, str, str]:
    """Reads the signature headers under whichever names they came.

    Each is read without the space, tabs and line breaks around its value.
    """
    # Whatever the case of the names, and whatever kind of mapping it is.
    given: dict[str, str] = {}
    for name, value in headers.items():
        if isinstance(name, str) and isinstance(value, str):
            given.setdefault(name.lower(), bare(value))
    found = ("", "", "")
    for prefix in ("webhook-", "svix-"):
        found = (
            given.get(prefix + "id", ""),
            given.get(prefix + "timestamp", ""),
            given.get(prefix + "signature", ""),
        )
        if all(found):
            break
    return found
