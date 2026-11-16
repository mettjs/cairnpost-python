from __future__ import annotations

import json
import socket
import threading
import traceback
import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from cairnpost import (
    Attachment,
    CairnPost,
    CairnPostError,
    Email,
    ErrorCode,
    TransportError,
    is_not_found,
    is_wrong_address,
    may_have_sent,
)

from .stand import EMAIL, KEY, Seen, Stand, serve


def everything(err: BaseException) -> str:
    """All an error shows: its words, its fields, and what lies underneath."""
    seen = ""
    at: BaseException | None = err
    while at is not None:
        # With the values of the client's own frames, as an error reporter
        # may show them. (Not the caller's, which hold the email it made.)
        shown = traceback.TracebackException.from_exception(at, capture_locals=True)
        seen += "".join(
            str(f.locals)
            for f in shown.stack
            if "/src/cairnpost/_transport" in f.filename or "/src/cairnpost/_answer" in f.filename
        )
        seen += repr(at) + str(at) + repr(at.args)
        seen += repr({name: getattr(at, name, None) for name in dir(at) if not name.startswith("__")})
        at = at.__cause__ or at.__context__
    return seen


class AnError(unittest.TestCase):
    def test_it_says_what_to_do(self) -> None:
        cases: list[tuple[int, str, str, str | None, str | None, bool, bool]] = [
            (
                422,
                '{"statusCode":422,"name":"validation_error","message":"The subject is missing."}',
                "",
                "validation_error",
                None,
                False,
                False,
            ),
            (
                422,
                '{"statusCode":422,"name":"sender_domain_not_ready","message":"Not set up.","id":"msg-9"}',
                "",
                "sender_domain_not_ready",
                "msg-9",
                False,
                False,
            ),
            (
                422,
                '{"name":"recipient_suppressed","message":"Suppressed.","id":"msg-9"}',
                "",
                "recipient_suppressed",
                "msg-9",
                False,
                True,
            ),
            (
                409,
                '{"name":"invalid_idempotent_request","message":"Used."}',
                "",
                "invalid_idempotent_request",
                None,
                False,
                False,
            ),
            (
                409,
                '{"name":"concurrent_idempotent_requests","message":"In flight."}',
                "7",
                "concurrent_idempotent_requests",
                None,
                True,
                False,
            ),
            (
                408,
                '{"name":"request_incomplete","message":"Not whole."}',
                "",
                "request_incomplete",
                None,
                True,
                False,
            ),
            (
                429,
                '{"name":"rate_limit_exceeded","message":"Limit.","id":"msg-2"}',
                "30",
                "rate_limit_exceeded",
                "msg-2",
                True,
                False,
            ),
            (
                502,
                '{"name":"upstream_unknown","message":"Lost.","id":"msg-3"}',
                "",
                "upstream_unknown",
                "msg-3",
                True,
                True,
            ),
            (
                503,
                '{"name":"upstream_unavailable","message":"Down."}',
                "",
                "upstream_unavailable",
                None,
                True,
                False,
            ),
            (503, '{"name":"schedule_full","message":"Full."}', "", "schedule_full", None, True, False),
            (401, '{"name":"invalid_api_key","message":"No."}', "", "invalid_api_key", None, False, False),
            # Changed by others meanwhile: read it and try again.
            (
                409,
                '{"name":"changed_meanwhile","message":"Changed."}',
                "",
                "changed_meanwhile",
                None,
                True,
                False,
            ),
            (503, '{"name":"unavailable","message":"Down."}', "", "unavailable", None, True, False),
            (500, '{"name":"internal_error","message":"Failed."}', "", "internal_error", None, True, True),
            # Something in between answered: the server may have sent all the same.
            (502, "<html>bad gateway</html>", "", None, None, True, True),
            (504, '{"name":"GatewayTimeout","message":"SUBJECTMARK"}', "", None, None, True, True),
            (500, '["not", "an object"]', "", None, None, True, True),
            (500, '{"name":["validation_error"],"message":"SUBJECTMARK"}', "", None, None, True, True),
            # Without an id, a suppression means nothing went.
            (
                422,
                '{"name":"recipient_suppressed","message":"Suppressed."}',
                "",
                "recipient_suppressed",
                None,
                False,
                False,
            ),
        ]
        for status, body, after, code, email_id, retry, may_be_out in cases:

            def answer(
                n: int, seen: Seen, a: tuple[int, str, str] = (status, body, after)
            ) -> tuple[int, str, dict[str, str]]:
                return a[0], a[1], {"Retry-After": a[2]} if a[2] else {}

            s = Stand(self, answer)
            with self.assertRaises(CairnPostError, msg=body) as raised:
                s.client.emails.send(EMAIL)
            err = raised.exception
            got = (err.status, err.code, err.email_id, err.retry_after, err.retryable, may_have_sent(err))
            self.assertEqual(
                got, (status, code, email_id, float(after) if after else None, retry, may_be_out), body
            )
            self.assertNotIn("SUBJECTMARK", str(err))
            self.assertEqual(err.detail is None, code is None)
            self.assertTrue(code is None or isinstance(err.code, ErrorCode))

    # An error never repeats what the email said or the key that sent it,
    # whatever went wrong and whatever the server answered.
    def test_no_error_holds_the_emails_words_or_the_key(self) -> None:
        marked = Email(
            from_="NAMEMARK <app@example.com>",
            to=["ana@example.org"],
            subject="SUBJECTMARK",
            text="TEXTMARK",
            html="<p>HTMLMARK</p>",
            headers={"X-Trace": "HEADERMARK"},
            attachments=[Attachment(filename="FILEMARK.txt", content=b"BYTESMARK")],
            idempotency_key="IDEMMARK",
        )
        # The last but one is the file's bytes as they travel.
        marks = [
            "NAMEMARK",
            "SUBJECTMARK",
            "TEXTMARK",
            "HTMLMARK",
            "HEADERMARK",
            "KEYMARK",
            "FILEMARK",
            "BYTESMARK",
            "QllURVNNQVJL",
            "IDEMMARK",
        ]

        def check(why: str, run: object) -> BaseException:
            try:
                run()  # type: ignore[operator]
            except Exception as err:
                for mark in marks:
                    self.assertNotIn(mark, everything(err), f"{why}: the error holds {mark}")
                return err
            self.fail(f"{why}: no error")

        def echo(status: int, field: str) -> CairnPost:
            """A server that echoes the request in a body that is not CairnPost's."""

            def answer(n: int, seen: Seen) -> tuple[int, str]:
                return status, json.dumps(
                    {"name": "BadRequestError", field: seen.body + seen.auth + seen.idem}
                )

            return Stand(self, answer).client

        check("an answer that echoes the request", lambda: echo(500, "error").emails.send(marked))
        # The same, in the shape of CairnPost's own error under another name.
        shaped = check(
            "an error of CairnPost's shape that is not CairnPost's",
            lambda: echo(400, "message").emails.send(marked),
        )
        assert isinstance(shaped, CairnPostError)
        self.assertEqual((shaped.code, shaped.detail), (None, None))
        s = serve(self, 200, "SUBJECTMARK is not JSON, KEYMARK")
        not_json = check("an answer that is not JSON", lambda: s.client.emails.send(marked))
        assert isinstance(not_json, TransportError)
        self.assertEqual(not_json.reason, "not_cairnpost")
        # Something that is not a web server at all, and says back what it
        # was sent: the standard library's own error holds those bytes.
        parrot = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(parrot.close)

        def say_back() -> None:
            conn, _ = parrot.accept()
            with conn:
                conn.sendall(conn.recv(65536))

        threading.Thread(target=say_back, daemon=True).start()
        there = f"http://127.0.0.1:{parrot.getsockname()[1]}"
        echoed = check("a peer that echoes the request", lambda: CairnPost(there, KEY).emails.send(marked))
        assert isinstance(echoed, TransportError)
        self.assertEqual(
            (echoed.reason, echoed.cause_kind, echoed.__cause__, echoed.__context__),
            ("network", "BadStatusLine", None, None),
        )
        # A server that is not there.
        closed = socket.create_server(("127.0.0.1", 0))
        free = closed.getsockname()[1]
        closed.close()
        none = check("no server", lambda: CairnPost(f"http://127.0.0.1:{free}", KEY).emails.send(marked))
        assert isinstance(none, TransportError)
        self.assertEqual(none.cause_kind, "ConnectionRefusedError")
        self.assertTrue(may_have_sent(none), "a send with no answer was said not to have gone")
        # A call that runs out of time.
        wait = threading.Event()
        self.addCleanup(wait.set)

        def late(n: int, seen: Seen) -> tuple[int, str]:
            wait.wait(5)
            return 200, "{}"

        slow = Stand(self, late, timeout=0.1)
        check("a timeout", lambda: slow.client.emails.send(marked))
        # What the caller gave wrongly is not repeated either.
        # (Made up here, not in the call: a traceback shows the line that failed.)
        bad_key = Email(from_="a@example.com", to=["b@example.org"], idempotency_key=marks[-1] + "\n2")
        alone = Email(from_="a@example.com", to=marks[0] + "@example.org")
        check("a key no header carries", lambda: s.client.emails.send(bad_key))
        check("an address alone", lambda: s.client.emails.send(alone))

    def test_retry_after_as_a_date_is_read_and_anything_else_is_not(self) -> None:
        now = datetime.now(UTC)
        afters = [
            format_datetime(now + timedelta(seconds=90), usegmt=True),
            "soon",
            "-5",
            "2030",
            format_datetime(now - timedelta(seconds=90), usegmt=True),
            "1.5",
        ]
        s = Stand(self, lambda n, seen: (503, "", {"Retry-After": afters[n - 1]}))
        with self.assertRaises(CairnPostError) as first:
            s.client.emails.send(EMAIL)
        wait = first.exception.retry_after
        self.assertTrue(wait is not None and 80 <= wait <= 91, wait)
        for odd in afters[1:]:
            with self.assertRaises(CairnPostError) as raised:
                s.client.emails.send(EMAIL)
            self.assertEqual(raised.exception.retry_after, 2030.0 if odd == "2030" else None, odd)

    # A path the server does not have is not a missing record: a client
    # pointed at a wrong address must not read every email as gone. Nor is
    # a 404 from something else at that address.
    def test_a_wrong_address_is_not_a_missing_record(self) -> None:
        cases = [
            (
                "a record that is not there",
                404,
                '{"statusCode":404,"name":"not_found","message":"No email has this id."}',
                True,
                False,
            ),
            (
                "a path that is not there",
                404,
                '{"statusCode":404,"name":"route_not_found","message":"There is nothing at this path."}',
                False,
                True,
            ),
            (
                "a method the path refuses",
                405,
                '{"statusCode":405,"name":"method_not_allowed","message":"This path does not take PUT."}',
                False,
                True,
            ),
            ("a proxy's own 404", 404, "<html>not here</html>", False, True),
            ("a refusal", 422, '{"statusCode":422,"name":"validation_error","message":"no"}', False, False),
        ]
        for why, status, body, missing, off in cases:
            with self.assertRaises(CairnPostError) as raised:
                serve(self, status, body).client.emails.get("0199")
            self.assertEqual(
                (is_not_found(raised.exception), is_wrong_address(raised.exception)), (missing, off), why
            )
        # The server's own sentence is kept, so the error says what to check.
        with self.assertRaises(CairnPostError) as said:
            serve(
                self,
                404,
                '{"statusCode":404,"name":"route_not_found","message":"Check the path and the server\'s address."}',
            ).client.emails.get("0199")
        self.assertIn("Check the path and the server's address", str(said.exception))
        self.assertEqual(said.exception.detail, "Check the path and the server's address.")
        # A redirect is something else answering at that address too.
        with self.assertRaises(CairnPostError) as moved:
            Stand(self, lambda n, seen: (308, "", {"Location": "/elsewhere"})).client.emails.get("0199")
        self.assertTrue(is_wrong_address(moved.exception) and not is_not_found(moved.exception))
        self.assertFalse(
            is_wrong_address(None) or is_wrong_address(TransportError("network")),
            "no answer at all is not a wrong address",
        )


if __name__ == "__main__":
    unittest.main()
