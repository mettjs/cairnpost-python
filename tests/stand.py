"""A server that records each request and answers what it is told."""

from __future__ import annotations

import threading
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from cairnpost import CairnPost, Email

KEY = "cp_test_KEYMARK"
EMAIL = Email(from_="a@example.com", to=["b@example.org"], subject="s", text="t")
#: What a server that is up says of itself.
UP = (
    '{"status":"ok","driver":"capture","version":"dev","events":"off","webhooks":"sending",'
    '"pruning":"running","scheduled":"sending","inbound":"off"}'
)


@dataclass(frozen=True)
class Seen:
    """A request as the server got it."""

    method: str
    #: The path as it travelled, still escaped, without its query.
    path: str
    query: str
    auth: str
    idem: str
    agent: str
    content_type: str
    body: str


#: Answers request number n: (status, body, headers), or None to hang up.
#: A header given a list is said once for each value.
Answer = Callable[
    [int, Seen],
    "tuple[int, bytes | str, dict[str, str]] | tuple[int, bytes | str, dict[str, list[str]]] | tuple[int, bytes | str] | None",
]


class Stand:
    def __init__(self, case: unittest.TestCase, answer: Answer, base: str = "", **options: Any) -> None:
        self.seen: list[Seen] = []
        stand = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _serve(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                path, _, query = self.path.partition("?")
                one = self.headers.get
                seen = Seen(
                    self.command,
                    path,
                    query,
                    one("Authorization", ""),
                    one("Idempotency-Key", ""),
                    one("User-Agent", ""),
                    one("Content-Type", ""),
                    body.decode("utf-8"),
                )
                stand.seen.append(seen)
                got = answer(len(stand.seen), seen)
                if got is None:
                    # The request was read; hang up without an answer.
                    self.close_connection = True
                    return
                status, payload, *rest = got
                raw = payload.encode("utf-8") if isinstance(payload, str) else payload
                self.send_response(status)
                for name, value in (rest[0] if rest else {}).items():
                    # A list is the header said once for each value.
                    for one_value in value if isinstance(value, list) else [value]:
                        self.send_header(name, one_value)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PATCH = do_DELETE = _serve

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        # A client that hangs up early is the point of some tests, not news.
        self.server.handle_error = lambda *args: None  # type: ignore[method-assign]
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()
        case.addCleanup(self.server.server_close)
        case.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.client = CairnPost(self.url + base, KEY, **options)


def serve(case: unittest.TestCase, status: int, body: str, **options: Any) -> Stand:
    """A stand that answers every request with one status and body."""
    return Stand(case, lambda n, seen: (status, body), **options)
