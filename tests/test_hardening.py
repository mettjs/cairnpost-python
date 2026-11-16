"""What a careless or hostile other side must not get past the client."""

from __future__ import annotations

import contextlib
import copy
import json
import pickle
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from cairnpost import (
    Attachment,
    CairnPost,
    CairnPostError,
    Email,
    ErrorCode,
    NotCapturingError,
    TransportError,
    Verifier,
    WebhookError,
    may_have_sent,
)

from .stand import EMAIL, KEY, serve
from .test_verify import AT, BOUNCE, SECRET, SIGNING_KEY, headers, signature


class ThreadingHTTPServer6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


class TheOtherSide(unittest.TestCase):
    def raw_server(self, answer: bytes, read_all: bool = True) -> str:
        """Something that answers these bytes to one request, and hangs up."""
        listener = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(listener.close)

        def serve_once() -> None:
            conn, _ = listener.accept()
            with conn, contextlib.suppress(OSError):
                conn.recv(65536 if read_all else 1024)
                conn.sendall(answer)
                if not read_all:
                    time.sleep(0.2)

        threading.Thread(target=serve_once, daemon=True).start()
        return f"http://127.0.0.1:{listener.getsockname()[1]}"

    def test_the_time_is_for_the_whole_call_while_the_answer_begins_too(self) -> None:
        listener = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(listener.close)

        def trickle() -> None:
            conn, _ = listener.accept()
            with conn, contextlib.suppress(OSError):
                conn.recv(65536)
                conn.sendall(b"HTTP/1.1 200 OK\r\n")
                for n in range(100):
                    conn.sendall(f"X-Slow-{n}: 1\r\n".encode())
                    time.sleep(0.1)

        threading.Thread(target=trickle, daemon=True).start()
        client = CairnPost(f"http://127.0.0.1:{listener.getsockname()[1]}", KEY, timeout=0.5)
        began = time.monotonic()
        with self.assertRaises(TransportError) as raised:
            client.limits()
        self.assertEqual(raised.exception.reason, "timeout")
        self.assertLess(time.monotonic() - began, 2)

    # Half a file must not read as the file, nor half an answer as an answer.
    def test_an_answer_cut_short_is_not_an_answer(self) -> None:
        head = b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: 100\r\n\r\n"
        with self.assertRaises(TransportError) as raised:
            CairnPost(self.raw_server(head + b"0123456789"), KEY).emails.file("m", 1)
        self.assertEqual(
            (raised.exception.reason, raised.exception.cause_kind), ("network", "IncompleteRead")
        )
        short = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 300\r\n\r\n{"id":"m1"}'
        with self.assertRaises(TransportError) as sent:
            CairnPost(self.raw_server(short), KEY).emails.send(EMAIL)
        self.assertTrue(may_have_sent(sent.exception))

    # A server may refuse a large request and hang up before all of it is
    # written: its refusal is what the error says, not the broken write.
    def test_a_refusal_that_comes_before_the_request_is_all_written_is_read(self) -> None:
        body = b'{"statusCode":413,"name":"request_too_large","message":"Too large."}'
        refusal = (
            b"HTTP/1.1 413 Too Large\r\nContent-Type: application/json\r\nContent-Length: %d\r\n"
            b"Connection: close\r\n\r\n%s" % (len(body), body)
        )
        large = Email(
            from_="a@example.com",
            to=["b@example.org"],
            subject="s",
            attachments=[Attachment(filename="a.bin", content=bytes(24 << 20))],
        )
        with self.assertRaises((CairnPostError, TransportError)) as raised:
            CairnPost(self.raw_server(refusal, read_all=False), KEY).emails.send(large)
        err = raised.exception
        assert isinstance(err, CairnPostError), repr(err)
        self.assertEqual((err.status, err.code, may_have_sent(err)), (413, "request_too_large", False))

    def test_a_server_named_by_its_ipv6_address_is_reached(self) -> None:
        try:
            server = ThreadingHTTPServer6(("::1", 0), BaseHTTPRequestHandler)
        except OSError:
            self.skipTest("this machine has no IPv6 loopback")
        self.addCleanup(server.server_close)
        threading.Thread(target=server.handle_request, daemon=True).start()
        with self.assertRaises(CairnPostError) as raised:
            CairnPost(f"http://[::1]:{server.server_address[1]}", KEY).limits()
        self.assertEqual(raised.exception.status, 501, "the server itself answered, if only to refuse GET")
        # Without a port it is the host that is dialled, not a part of it.
        for base in ["http://[::1]", "https://[2001:db8::1]", "http://[fe80::abcd]"]:
            self.assertRegex(repr(CairnPost(base, KEY)), r"to (::1|2001:db8::1|fe80::abcd)>")
        for base in ["https://mail.example.com/a b", "https://mail.example.com/ä"]:
            with self.assertRaises(ValueError, msg=base):
                CairnPost(base, KEY)

    # Half of a pair of surrogates cannot be written as UTF-8. The email is
    # sent with a mark in its place, not raised with all it says in the error.
    def test_text_that_cannot_be_encoded_is_sent_marked(self) -> None:
        s = serve(self, 200, '{"id":"msg-1"}')
        s.client.emails.send(Email(from_="a@example.com", to=["b@example.org"], subject="x\ud800y", text="t"))
        self.assertEqual(json.loads(s.seen[0].body)["subject"], "x?y")

    def test_a_field_that_is_null_is_not_what_cairnpost_always_says(self) -> None:
        c = serve(self, 200, '{"data":null,"added":null,"lifted":null,"delivered":null,"driver":null}').client
        for call in (
            c.webhooks.list,
            c.suppressions.list,
            c.limits,
            c.captured,
            lambda: c.suppressions.add("example.com", "a@example.org"),
            lambda: c.suppressions.lift("example.com", "a@example.org"),
            lambda: c.webhooks.test("w"),
        ):
            with self.assertRaises(TransportError):
                call()

    def test_a_strangers_date_this_language_has_no_year_for_reads_as_none(self) -> None:
        answer = (
            '{"id":"in-1","to":"help@example.com","received_at":"2030-01-01T00:00:00Z",'
            '"kept_until":"2030-01-08T00:00:00Z","size":5,'
            '"content":{"subject":"Hi","from":"a@example.org","date":"0000-12-31T23:30:00Z"}}'
        )
        content = serve(self, 200, answer).client.received.get("in-1").content
        self.assertTrue(content is not None and content.date is None and content.subject == "Hi")

    def test_the_verifiers_clock_is_read_when_a_webhook_is_verified(self) -> None:
        ours = headers("webhook-", "dlv-1", AT, signature(SIGNING_KEY, "dlv-1", AT, BOUNCE))
        with mock.patch("time.time", return_value=float(AT)):
            Verifier(SECRET).verify(ours, BOUNCE)
        with self.assertRaises(WebhookError) as late:
            Verifier(SECRET).verify(ours, BOUNCE)
        self.assertEqual(late.exception.reason, "stale")
        # A text that cannot be encoded is not the body that was signed.
        with self.assertRaises(WebhookError) as odd:
            Verifier(SECRET, now=lambda: float(AT)).verify(ours, "x\ud800")
        self.assertEqual(odd.exception.reason, "signature")

    def test_an_error_can_be_copied_and_handed_to_another_process(self) -> None:
        errors: list[Exception] = [
            CairnPostError(429, ErrorCode.RATE_LIMITED, "Limit.", "msg-2", 30.0),
            CairnPostError(502),
            TransportError("network", "BadStatusLine"),
            NotCapturingError(),
            WebhookError("stale"),
        ]
        for err in errors:
            for back in (pickle.loads(pickle.dumps(err)), copy.deepcopy(err)):
                self.assertEqual((type(back), str(back), vars(back)), (type(err), str(err), vars(err)))

    # A 408 from something in between may come after the server took the email.
    def test_a_408_that_is_not_cairnposts_own_may_be_a_send_that_went(self) -> None:
        with self.assertRaises(CairnPostError) as raised:
            serve(self, 408, "<html>request timeout</html>").client.emails.send(EMAIL)
        err = raised.exception
        self.assertEqual((err.code, err.retryable, may_have_sent(err)), (None, True, True))


if __name__ == "__main__":
    unittest.main()
