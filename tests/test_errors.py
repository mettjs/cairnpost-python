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
    TransportError,
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
    # What an error says to do is in the shared cases (test_cases_errors.py).

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

    # The server's own sentence is kept, so the error says what to check;
    # and no answer at all is not a wrong address.
    def test_a_wrong_address_says_what_to_check(self) -> None:
        with self.assertRaises(CairnPostError) as said:
            serve(
                self,
                404,
                '{"statusCode":404,"name":"route_not_found","message":"Check the path and the server\'s address."}',
            ).client.emails.get("0199")
        self.assertIn("Check the path and the server's address", str(said.exception))
        self.assertEqual(said.exception.detail, "Check the path and the server's address.")
        self.assertFalse(
            is_wrong_address(None) or is_wrong_address(TransportError("network")),
            "no answer at all is not a wrong address",
        )


if __name__ == "__main__":
    unittest.main()
