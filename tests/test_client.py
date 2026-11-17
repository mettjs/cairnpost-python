from __future__ import annotations

import socket
import threading
import time
import unittest

from cairnpost import (
    CairnPost,
    CairnPostError,
    Email,
    TransportError,
    __version__,
    is_not_found,
    may_have_sent,
)
from cairnpost._client import CairnPost as _Same

from .stand import EMAIL, KEY, UP, Stand, serve

RECORD = '{"id":"m","created_at":"2030-01-01T00:00:00Z","updated_at":"2030-01-01T00:00:00Z"}'


class TheClient(unittest.TestCase):
    def test_it_refuses_what_cannot_work(self) -> None:
        for base in [
            "",
            "mail.example.com",
            "ftp://mail.example.com",
            "https://",
            "https://u:p@mail.example.com",
            "https://[::1",
            "http://h:99999",
            None,
        ]:
            with self.assertRaises(ValueError, msg=f"{base!r} was taken as a base URL"):
                CairnPost(base, "key")  # type: ignore[arg-type]
        for key in ["", " ", "cp_a\nb", "cp_a\x00b", "cp_a b", "cp_é", None, b"cp_bytes"]:
            with self.assertRaises(ValueError, msg=f"{key!r} was taken as a key"):
                CairnPost("https://mail.example.com", key)  # type: ignore[arg-type]
        # What is refused is not repeated.
        with self.assertRaises(ValueError) as refused:
            CairnPost("https://mail.example.com", "cp_KEYMARK\nb")
        self.assertNotIn("KEYMARK", repr(refused.exception) + str(refused.exception))
        self.assertIs(CairnPost, _Same)

    def test_a_base_url_with_a_path_is_kept_and_the_application_named_first(self) -> None:
        s = Stand(self, lambda n, seen: (200, RECORD), base="/mail/", user_agent="billing/2")
        s.client.emails.get("m")
        self.assertEqual(s.seen[0].path, "/mail/emails/m")
        self.assertTrue(s.seen[0].agent.startswith(f"billing/2 cairnpost-python/{__version__}"))
        CairnPost(s.url, KEY, user_agent="bad\nname").emails.get("m")
        self.assertEqual(s.seen[1].agent, f"cairnpost-python/{__version__}")

    def test_a_key_is_sent_without_the_space_around_it_and_is_not_shown(self) -> None:
        s = serve(self, 200, UP)
        client = CairnPost(s.url, " cp_test_KEYMARK\n")
        client.limits()
        self.assertEqual(s.seen[0].auth, "Bearer cp_test_KEYMARK")
        # Health needs no key, and is sent none.
        client.health()
        self.assertEqual(s.seen[1].auth, "")
        self.assertNotIn("KEYMARK", repr(client) + str(client) + repr(client.emails))
        self.assertFalse(hasattr(client, "__dict__"))

    def test_a_redirect_is_not_followed_and_is_said_as_what_it_is(self) -> None:
        s = Stand(self, lambda n, seen: (301, "", {"Location": "/elsewhere"}))
        with self.assertRaises(CairnPostError) as raised:
            s.client.emails.send(EMAIL)
        err = raised.exception
        self.assertEqual((err.status, len(s.seen), is_not_found(err)), (301, 1, False))
        self.assertIn("redirect", str(err))

    def test_an_answer_too_large_says_so(self) -> None:
        body = '{"data":[{"id":"c1","at":"2030-01-01T00:00:00Z","subject":"' + "x" * 4096 + '"}]}'
        s = serve(self, 200, body)
        with self.assertRaises(TransportError) as raised:
            CairnPost(s.url, KEY, max_answer_bytes=1024).captured()
        self.assertEqual(raised.exception.reason, "too_large")
        self.assertIn("larger than the client reads", str(raised.exception))
        self.assertEqual(len(CairnPost(s.url, KEY, max_answer_bytes=1 << 20).captured()), 1)

    def test_a_send_is_made_once_even_when_the_connection_drops(self) -> None:
        for key in [None, "welcome-42"]:
            s = Stand(self, lambda n, seen: (200, UP) if seen.method == "GET" else None)
            s.client.health()
            with self.assertRaises(TransportError) as raised:
                s.client.emails.send(
                    Email(
                        from_="a@example.com",
                        to=["b@example.org"],
                        subject="s",
                        text="t",
                        idempotency_key=key,
                    )
                )
            self.assertEqual(raised.exception.reason, "network")
            self.assertTrue(may_have_sent(raised.exception))
            self.assertEqual([r.method for r in s.seen], ["GET", "POST"])

    def test_a_call_that_runs_out_of_time_says_so(self) -> None:
        wait = threading.Event()
        self.addCleanup(wait.set)

        def slow(n: int, seen: object) -> tuple[int, str]:
            wait.wait(5)
            return 200, "{}"

        s = Stand(self, slow, timeout=0.2)
        began = time.monotonic()
        with self.assertRaises(TransportError) as raised:
            s.client.emails.send(EMAIL)
        self.assertEqual(raised.exception.reason, "timeout")
        self.assertTrue(may_have_sent(raised.exception))
        self.assertLess(time.monotonic() - began, 2)

    def test_the_time_is_for_the_whole_call(self) -> None:
        # An answer that trickles in never lets one read time out; the call does all the same.
        listener = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(listener.close)

        def trickle() -> None:
            conn, _ = listener.accept()
            with conn:
                conn.recv(65536)
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 1000\r\n\r\n"
                )
                try:
                    for _ in range(100):
                        conn.sendall(b" ")
                        time.sleep(0.1)
                except OSError:
                    pass

        threading.Thread(target=trickle, daemon=True).start()
        client = CairnPost(f"http://127.0.0.1:{listener.getsockname()[1]}", KEY, timeout=0.5)
        began = time.monotonic()
        with self.assertRaises(TransportError) as raised:
            client.limits()
        self.assertEqual(raised.exception.reason, "timeout")
        self.assertLess(time.monotonic() - began, 2)

    def test_a_time_or_a_size_that_is_none_is_refused_when_the_client_is_made(self) -> None:
        for timeout in [0, -1, float("inf"), float("nan"), True, "30", None]:
            with self.assertRaisesRegex(ValueError, "timeout", msg=repr(timeout)):
                CairnPost("https://mail.example.com", KEY, timeout=timeout)  # type: ignore[arg-type]
        for most in [0, -1, 1.5, True]:
            with self.assertRaisesRegex(ValueError, "max_answer_bytes"):
                CairnPost("https://mail.example.com", KEY, max_answer_bytes=most)  # type: ignore[arg-type]
        CairnPost("https://mail.example.com", KEY, timeout=600, max_answer_bytes=1)

    # A long page from something that is not CairnPost is not read whole
    # to say that it is not CairnPost's.
    def test_a_refusal_is_read_no_further_than_its_few_fields_need(self) -> None:
        s = serve(self, 502, "<html>" + "x" * (1 << 20))
        with self.assertRaises(CairnPostError) as raised:
            s.client.emails.send(EMAIL)
        self.assertEqual(
            (raised.exception.status, raised.exception.code, may_have_sent(raised.exception)),
            (502, None, True),
        )

    def test_an_id_that_would_name_another_path_is_not_asked_of_the_server(self) -> None:
        s = serve(self, 200, "{}")
        for bad in ["", ".", "..", None]:
            with self.assertRaises(ValueError):
                s.client.emails.get(bad)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                s.client.webhooks.retry_delivery("w", bad)  # type: ignore[arg-type]
        self.assertEqual(s.seen, [])


if __name__ == "__main__":
    unittest.main()
