from __future__ import annotations

import contextlib
import http.client
import json
import re
import socket
import ssl
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

from ._errors import CairnPostError, TransportError
from ._parse import parse
from ._problem import problem_of

#: How much of an answer that is a refusal is read.
_MOST_OF_A_REFUSAL = 64 * 1024

_HEADER_SAFE = re.compile(r"[\x21-\x7e]([\x20-\x7e]*[\x21-\x7e])?", re.ASCII)


def header_safe(v: object) -> bool:
    """Says a value can be sent as a header as it is.

    Printable ASCII, in one line, with no space at either end. Checked
    here, not left to the standard library, whose own error would repeat
    the value.
    """
    return isinstance(v, str) and _HEADER_SAFE.fullmatch(v) is not None


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class Call:
    """One request to make."""

    method: str
    #: The route's segments; each is escaped, so an id is safe.
    path: tuple[str, ...]
    query: Mapping[str, str | None] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    #: Sent as JSON; None for none.
    body: Any = None
    #: A route that needs no key and answers its own body on a 503.
    plain: bool = False

    def __repr__(self) -> str:
        # Never what it carries: a traceback that shows a frame's values
        # would print an email with it.
        return f"<cairnpost call {self.method}>"


class Transport:
    """Makes the calls: each one once, on a connection of its own.

    No retry, no redirect followed, and no connection kept: a kept
    connection that has gone dead is how a request comes to be sent twice.
    """

    __slots__ = ("_agent", "_auth", "_host", "_most", "_port", "_prefix", "_secure", "_timeout", "_tls")

    def __init__(
        self,
        *,
        secure: bool,
        host: str,
        port: int,
        prefix: str,
        key: str,
        agent: str,
        timeout: float,
        max_answer_bytes: int,
        tls: ssl.SSLContext | None,
    ) -> None:
        self._secure, self._host, self._port, self._prefix = secure, host, port, prefix
        self._auth, self._agent = "Bearer " + key, agent
        self._timeout, self._most, self._tls = timeout, max_answer_bytes, tls

    def __repr__(self) -> str:
        # Never the key.
        return f"<cairnpost transport to {self._host}>"

    def read_json(self, k: Call) -> object:
        """Makes a call that answers JSON, and gives the answer as it was read."""
        raw, _, _ = self._answer(k, "application/json")
        fine, answer = parse(raw)
        # Not left in this frame for a traceback to show.
        del raw
        if not fine:
            # The answer's text is not quoted: it could hold an email's words.
            raise TransportError("not_cairnpost")
        return answer

    def empty(self, k: Call) -> None:
        """Makes a call that CairnPost answers with nothing (204).

        Anything else that says "fine" is not CairnPost saying it was done.
        """
        raw, _, status = self._answer(k, "application/json")
        nothing = status == 204 and not raw
        del raw
        if not nothing:
            raise TransportError("not_cairnpost")

    def read_bytes(self, k: Call) -> bytes:
        """Makes a call that answers a file's bytes."""
        raw, kind, _ = self._answer(k, "application/octet-stream, application/json")
        # Anything else that answers 200 here is not a CairnPost server.
        if kind != "application/octet-stream":
            del raw
            raise TransportError("not_cairnpost")
        return raw

    def _answer(self, k: Call, accept: str) -> tuple[bytes, str, int]:
        # Everything is made, sent and read in frames that are gone by the
        # time this one raises, and the error is raised here with nothing
        # behind it: a traceback that shows a frame's values then holds
        # neither the key, nor the email, nor what the other side said.
        outcome = self._settle(k, accept)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _settle(self, k: Call, accept: str) -> tuple[bytes, str, int] | TransportError | CairnPostError:
        failed, status, kind, retry_after, raw = self._exchange(k, accept)
        if failed is not None:
            return failed
        if 200 <= status <= 299:
            return raw, kind, status
        problem = problem_of(status, raw, retry_after)
        # A plain call's 503 is an answer to read (the server is up and
        # says what is not); anything else it is refused with is an error
        # like any other, a path that is not there above all.
        if k.plain and problem.code is None and status == 503:
            return raw, kind, status
        return problem

    def _request(self, k: Call, accept: str) -> tuple[str, bytes | None, dict[str, str]]:
        target = self._prefix
        for segment in k.path:
            # A segment of dots would be resolved away, and name another path.
            if not isinstance(segment, str) or segment in ("", ".", ".."):
                raise ValueError("cairnpost: an id is required")
            target += "/" + quote(segment, safe="")
        query = {name: value for name, value in k.query.items() if value is not None}
        if query:
            target += "?" + urlencode(query)
        headers = {**k.headers, "Accept": accept, "User-Agent": self._agent}
        body: bytes | None = None
        if k.body is not None:
            text = json.dumps(k.body, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            # What no encoding can carry (half of a pair of surrogates) is
            # sent as a mark of that, not raised with the email in the error.
            body = text.encode("utf-8", errors="replace")
            headers["Content-Type"] = "application/json"
        if not k.plain:
            headers["Authorization"] = self._auth
        return target, body, headers

    def _exchange(self, k: Call, accept: str) -> tuple[TransportError | None, int, str, str | None, bytes]:
        """Makes the call; answers what failed, or the status, type, Retry-After and body."""
        target, body, headers = self._request(k, accept)
        ends = time.monotonic() + self._timeout
        conn = self._connect()
        # The time is for the whole call. A wait on the socket is given
        # what is left of it, and when it is up the socket is shut under
        # whatever still waits: an answer that comes a little at a time
        # would otherwise never let one wait run out.
        over = threading.Event()

        def cut() -> None:
            over.set()
            sock = conn.sock
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)

        watch = threading.Timer(self._timeout, cut)
        watch.daemon = True
        watch.start()
        try:
            conn.connect()
            self._wait(conn, ends)
            # The server may have answered and hung up before all of a
            # large request was written: its answer is still there to
            # read, and says more than the broken write does.
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                conn.request(k.method, target, body=body, headers=headers)
            self._wait(conn, ends)
            res = conn.getresponse()
            status, kind = res.status, res.getheader("Content-Type") or ""
            retry_after = res.getheader("Retry-After")
            # Of an answer that is a refusal only its few short fields are
            # kept: no more of it is read than holds them.
            fine = 200 <= status <= 299
            most = self._most if fine else min(self._most, _MOST_OF_A_REFUSAL)
            raw = self._read(conn, res, ends, most, cut=not fine)
        except TransportError as err:
            return err, 0, "", None, b""
        except TimeoutError as err:
            return TransportError("timeout", type(err).__name__), 0, "", None, b""
        except (OSError, http.client.HTTPException) as err:
            return (
                TransportError("timeout" if over.is_set() else "network", type(err).__name__),
                0,
                "",
                None,
                b"",
            )
        finally:
            watch.cancel()
            conn.close()
        if over.is_set():
            return TransportError("timeout"), 0, "", None, b""
        return None, status, kind, retry_after, raw

    def _connect(self) -> http.client.HTTPConnection:
        if self._secure:
            return http.client.HTTPSConnection(
                self._host, self._port, timeout=self._timeout, context=self._tls
            )
        return http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)

    @staticmethod
    def _wait(conn: http.client.HTTPConnection, ends: float) -> None:
        """Gives the next step what is left of the call's time."""
        left = ends - time.monotonic()
        if left <= 0:
            raise TimeoutError
        if conn.sock is not None:
            conn.sock.settimeout(left)

    def _read(
        self,
        conn: http.client.HTTPConnection,
        res: http.client.HTTPResponse,
        ends: float,
        most: int,
        *,
        cut: bool,
    ) -> bytes:
        """Reads an answer's body, and no more of it than `most`.

        A longer one is an error, or with `cut` is read that far and left.
        """
        chunks: list[bytes] = []
        size = 0
        while True:
            self._wait(conn, ends)
            chunk = res.read1(65536)
            if not chunk:
                # An answer that ends before the length it gave is not the
                # answer: half a file must not read as the file.
                if res.length:
                    raise http.client.IncompleteRead(b"")
                break
            if size + len(chunk) > most:
                if not cut:
                    raise TransportError("too_large")
                break
            size += len(chunk)
            chunks.append(chunk)
        return b"".join(chunks)
