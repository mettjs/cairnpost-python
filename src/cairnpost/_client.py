from __future__ import annotations

import math
import re
import ssl
from urllib.parse import urlsplit

from ._answer import reading
from ._codes import ErrorCode
from ._emails import Emails
from ._errors import CairnPostError, NotCapturingError, is_wrong_address
from ._received import ReceivedEmails
from ._status import CapturedEmail, Health, Limits, read_captured, read_health, read_limits
from ._suppressions import Suppressions
from ._templates import Templates
from ._transport import Call, Transport, header_safe
from ._version import __version__
from ._webhooks import Webhooks

#: How long a call may take, in seconds. It is longer than the server gives
#: its slowest answer, a batch: by the server's own settings that is 30
#: seconds for the request to arrive, a minute of starting emails, and the
#: last send and its record (10 and 20 seconds), two minutes in all. A
#: client that gave up sooner would not know whether its emails went. A
#: server set to give a send or a batch longer wants a client given longer.
DEFAULT_TIMEOUT = 150.0

#: How much of an answer is read unless `max_answer_bytes` says otherwise.
#: Only a development server's list of captured emails comes near it.
DEFAULT_MAX_ANSWER_BYTES = 64 * 1024 * 1024

_PATH = re.compile(r"[\x21-\x7e]*", re.ASCII)
_BAD_URL = "cairnpost: the base URL must be http:// or https:// and name a host"


class CairnPost:
    """Calls one CairnPost server with one API key.

    It never retries by itself: an error says what happened and whether
    trying again is right (see `CairnPostError`); the application decides.
    It may be used from several threads at once.
    """

    __slots__ = ("_t", "emails", "received", "suppressions", "templates", "webhooks")

    #: Sending emails and reading what became of them.
    emails: Emails
    #: The addresses not sent to. Admin key.
    suppressions: Suppressions
    #: The URLs told what becomes of emails. Admin key.
    webhooks: Webhooks
    #: The templates emails are sent from. Admin key.
    templates: Templates
    #: The emails that came for the server's addresses. Admin key.
    received: ReceivedEmails

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_answer_bytes: int = DEFAULT_MAX_ANSWER_BYTES,
        user_agent: str | None = None,
        tls: ssl.SSLContext | None = None,
    ) -> None:
        """Makes a client for the server at `base_url` ("https://mail.example.com") using `api_key`.

        A send key may send and read its own emails; the calls marked
        "admin key" need an admin key.

        `timeout` is how long a call may take, in seconds: keep it above
        the server's send and batch timeouts. `max_answer_bytes` is how
        much of an answer is read; a larger one is an error that says so.
        A refusal is not counted: 64 KiB of one are read whatever this
        says, and a longer one is its status alone.
        `user_agent` is the application's name, put before the client's
        own in the User-Agent header; a name a header cannot carry is
        ignored. `tls` is how an https server is trusted; the system's own
        certificates when left out.
        """
        try:
            url = urlsplit(base_url if isinstance(base_url, str) else "")
            host, port = url.hostname, url.port
        except ValueError:
            raise ValueError(_BAD_URL) from None
        if (
            url.scheme not in ("http", "https")
            or not host
            or url.username is not None
            or url.password is not None
        ):
            raise ValueError(_BAD_URL)
        # A path is sent as it is written: one that cannot be is said
        # here, not at every call.
        if not _PATH.fullmatch(url.path):
            raise ValueError("cairnpost: the base URL's path must be written as a URL carries it (no spaces)")
        # A key read from a file often ends in a newline; one with anything
        # else a header cannot carry is refused here, not at the first call.
        key = api_key.strip() if isinstance(api_key, str) else ""
        if not header_safe(key) or " " in key:
            raise ValueError("cairnpost: an API key is required, and holds no spaces or control characters")
        if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not 0 < timeout < math.inf:
            raise ValueError("cairnpost: timeout must be a number of seconds above 0")
        if (
            isinstance(max_answer_bytes, bool)
            or not isinstance(max_answer_bytes, int)
            or max_answer_bytes < 1
        ):
            raise ValueError("cairnpost: max_answer_bytes must be a whole number above 0")
        agent = "cairnpost-python/" + __version__
        if user_agent and header_safe(user_agent):
            agent = user_agent + " " + agent
        secure = url.scheme == "https"
        self._t = Transport(
            secure=secure,
            host=host,
            # Always said: a host with colons in it (IPv6) is not then read as "host:port".
            port=port or (443 if secure else 80),
            prefix=url.path.rstrip("/"),
            key=key,
            agent=agent,
            timeout=float(timeout),
            max_answer_bytes=max_answer_bytes,
            tls=(tls or ssl.create_default_context()) if secure else None,
        )
        self.emails = Emails(self._t)
        self.suppressions = Suppressions(self._t)
        self.webhooks = Webhooks(self._t)
        self.templates = Templates(self._t)
        self.received = ReceivedEmails(self._t)

    def __repr__(self) -> str:
        # Never the key.
        return f"<CairnPost client, {self._t!r}>"

    def health(self) -> Health:
        """Asks the server how it is. It needs no key.

        A server that is up but cannot reach its database is answered, not
        an error: see `Health.ok`. With a base URL that is wrong it fails
        as any call does, and `is_wrong_address` says so: it is the call
        to check a configuration with.
        """
        return reading(self._t.read_json(Call(method="GET", path=("health",), plain=True)), read_health)

    def limits(self) -> Limits:
        """Answers the mail provider's sending allowance, so an application knows before it runs out."""
        return reading(self._t.read_json(Call(method="GET", path=("limits",))), read_limits)

    def captured(self) -> list[CapturedEmail]:
        """Answers the emails a server running the capture driver holds, newest first.

        That is what would have been sent. For development and tests. A
        server that delivers for real has no such list: the error is then
        a `NotCapturingError`, unless `health` fails too, in which case
        the base URL is what is wrong. Admin key.
        """
        try:
            return reading(self._t.read_json(Call(method="GET", path=("capture", "emails"))), read_captured)
        except CairnPostError as err:
            if err.code is not ErrorCode.ROUTE_NOT_FOUND:
                raise
            wrong = err
        # The path is not there. If the server is, it is one that does not
        # capture; if nothing of CairnPost's is at that address, the first
        # error says so. Health failing any other way is its own error.
        try:
            self.health()
        except CairnPostError as down:
            if not is_wrong_address(down):
                raise
        else:
            raise NotCapturingError
        raise wrong
