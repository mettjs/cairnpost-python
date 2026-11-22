from __future__ import annotations

import math
import re
import ssl
from urllib.parse import urlsplit

from ._answer import reading
from ._bare import bare
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
#: What an API key holds: printable ASCII, with no space.
_KEY = re.compile(r"[\x21-\x7e]+", re.ASCII)
_BAD_URL = "cairnpost: the base URL must be http:// or https:// and name a host"


def _address(base_url: object) -> tuple[bool, str, int, str] | str:
    """Where the server is (https or not, host, port, path), or what is wrong with the base URL."""
    try:
        url = urlsplit(base_url if isinstance(base_url, str) else "")
        host, port = url.hostname, url.port
    except ValueError:
        return _BAD_URL
    if (
        url.scheme not in ("http", "https")
        or not host
        or url.username is not None
        or url.password is not None
    ):
        return _BAD_URL
    # A path is sent as it is written: one that cannot be is said here,
    # not at every call.
    if not _PATH.fullmatch(url.path):
        return "cairnpost: the base URL's path must be written as a URL carries it (no spaces)"
    secure = url.scheme == "https"
    # The port is always said: a host with colons in it (IPv6) is not then read as "host:port".
    return secure, host, port or (443 if secure else 80), url.path.rstrip("/")


def _settled(
    base_url: object,
    api_key: object,
    *,
    timeout: object,
    max_answer_bytes: object,
    user_agent: str | None,
    tls: ssl.SSLContext | None,
) -> Transport | str:
    """What a client calls through, or what is wrong with what it was given."""
    address = _address(base_url)
    if isinstance(address, str):
        return address
    secure, host, port, prefix = address
    # A key read from a file often ends in a newline; one with anything
    # else in it that no key has is refused here, not at the first call.
    key = bare(api_key) if isinstance(api_key, str) else ""
    if not _KEY.fullmatch(key):
        return "cairnpost: an API key is required, and holds only printable ASCII characters, with no spaces"
    try:
        seconds = (
            float(timeout) if isinstance(timeout, int | float) and not isinstance(timeout, bool) else 0.0
        )
    except OverflowError:
        # A whole number too large to be a time at all.
        seconds = math.inf
    if not 0 < seconds < math.inf:
        return "cairnpost: timeout must be a number of seconds above 0"
    if isinstance(max_answer_bytes, bool) or not isinstance(max_answer_bytes, int) or max_answer_bytes < 1:
        return "cairnpost: max_answer_bytes must be a whole number above 0"
    agent = "cairnpost-python/" + __version__
    if user_agent and header_safe(user_agent):
        agent = user_agent + " " + agent
    return Transport(
        secure=secure,
        host=host,
        port=port,
        prefix=prefix,
        key=key,
        agent=agent,
        timeout=seconds,
        max_answer_bytes=max_answer_bytes,
        tls=(tls or ssl.create_default_context()) if secure else None,
    )


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
        "admin key" need an admin key. A space, a tab or a line break
        around the key is dropped, as a value read from a file ends in a
        line break; a key with anything else in it that no key has is
        refused.

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
        # What is wrong is found in a frame of its own and said from this
        # one with the key gone from it: an error reporter shows the values
        # of every frame an error passed through.
        try:
            made = _settled(
                base_url,
                api_key,
                timeout=timeout,
                max_answer_bytes=max_answer_bytes,
                user_agent=user_agent,
                tls=tls,
            )
        finally:
            del api_key
        if isinstance(made, str):
            raise ValueError(made)
        self._t = made
        self.emails = Emails(self._t)
        self.suppressions = Suppressions(self._t)
        self.webhooks = Webhooks(self._t)
        self.templates = Templates(self._t)
        self.received = ReceivedEmails(self._t)

    def __repr__(self) -> str:
        # Never the key. And never an error of its own: a client that was
        # refused while it was made is shown by whatever reports that.
        return f"<CairnPost client, {getattr(self, '_t', 'not made')!r}>"

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
