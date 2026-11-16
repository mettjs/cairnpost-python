from __future__ import annotations

import hashlib
import hmac
import http.client
import threading
import time
import unittest
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from cairnpost import (
    CairnPost,
    CairnPostError,
    DeliveryState,
    ErrorCode,
    EventType,
    NotCapturingError,
    TransportError,
    Verifier,
    WebhookError,
    WebhookEvent,
    WebhookTest,
    is_not_found,
    is_wrong_address,
)

from .server import INBOUND_SECRET, RUN, URL, admin, code, need, until


class Receiver:
    """A receiver on this machine: it keeps each request it was sent."""

    def __init__(self, case: unittest.TestCase) -> None:
        self.got: list[tuple[dict[str, str], bytes]] = []
        self.answer = 204
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                receiver.got.append((dict(self.headers.items()), body))
                self.send_response(receiver.answer)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()
        case.addCleanup(self.server.server_close)
        case.addCleanup(self.server.shutdown)
        self.at = f"http://127.0.0.1:{self.server.server_address[1]}/hook/{RUN}"


def hand_over(raw: bytes, to: str, from_: str) -> int:
    """Hands an email to the server as the Worker it ships does, signed."""
    timestamp = str(int(time.time()))
    digest = hashlib.sha256(raw).hexdigest()
    mac = hmac.new(INBOUND_SECRET.encode(), digestmod=hashlib.sha256)
    for part in (timestamp, to, from_, digest):
        mac.update(len(part.encode()).to_bytes(8, "big") + part.encode())
    url = urlsplit(URL)
    conn = http.client.HTTPConnection(url.hostname or "", url.port, timeout=30)
    try:
        conn.request(
            "POST",
            url.path + "/inbound",
            body=raw,
            headers={
                "Content-Type": "message/rfc822",
                "X-CairnPost-Timestamp": timestamp,
                "X-CairnPost-To": to,
                "X-CairnPost-From": from_,
                "X-CairnPost-Digest": digest,
                "X-CairnPost-Signature": "v1=" + mac.hexdigest(),
            },
        )
        return conn.getresponse().status
    finally:
        conn.close()


class WebhooksAgainstARealServer(unittest.TestCase):
    def test_webhooks_and_received_mail(self) -> None:
        r = Receiver(self)
        made = admin.webhooks.create(r.at, events=[EventType.RECEIVED], description=RUN)
        self.addCleanup(lambda: code(lambda: admin.webhooks.delete(made.id)))
        assert made.secret is not None
        self.assertTrue(made.secret.startswith("whsec_") and made.enabled and made.paused_at is None)
        self.assertIsNone(admin.webhooks.get(made.id).secret, "the secret is said once")
        self.assertTrue(any(w.id == made.id and w.description == RUN for w in admin.webhooks.list()))

        # A webhook sent to try it out arrives signed, and the verifier takes it.
        self.assertEqual(admin.webhooks.test(made.id), WebhookTest(delivered=True, status=204, failure=None))
        verifier = Verifier(made.secret)
        tried = verifier.verify(*r.got[0])
        self.assertEqual((tried.type, tried.email), (EventType.TEST, None))
        self.assertLess(abs(tried.at - datetime.now(UTC)), timedelta(minutes=1))
        with self.assertRaises(WebhookError):
            verifier.verify(r.got[0][0], r.got[0][1] + b" ")
        r.answer = 500
        self.assertEqual(
            admin.webhooks.test(made.id), WebhookTest(delivered=False, status=500, failure="status")
        )
        r.answer = 204

        # A new secret: the old one still signs for a time, so both verify.
        rotated = admin.webhooks.rotate_secret(made.id)
        assert rotated.secret is not None and rotated.previous_secret_until is not None
        self.assertNotEqual(rotated.secret, made.secret)
        self.assertGreater(rotated.previous_secret_until, datetime.now(UTC))
        admin.webhooks.test(made.id)
        self.assertEqual(verifier.verify(*r.got[-1]).type, EventType.TEST)
        newer = Verifier(rotated.secret)
        self.assertEqual(newer.verify(*r.got[-1]).type, EventType.TEST)

        off = admin.webhooks.update(made.id, enabled=False, events=[])
        self.assertEqual((off.enabled, off.events, off.url, off.description), (False, [], r.at, RUN))
        on = admin.webhooks.update(made.id, enabled=True, events=[EventType.RECEIVED], description="")
        self.assertEqual((on.enabled, on.events, on.description), (True, [EventType.RECEIVED], None))
        self.assertIsNone(
            admin.webhooks.resume(made.id).paused_at, "one that is not paused is answered as it is"
        )

        # An email that comes for an address is told to the endpoint, and read.
        to = f"help@{RUN}.example.com"
        raw = (
            f"From: Ana <ana@example.org>\r\nTo: {to}\r\nSubject: =?utf-8?q?H=C3=A9llo?= {RUN}\r\n"
            "Date: Tue, 01 Jan 2030 00:00:00 +0000\r\nMessage-ID: <1@example.org>\r\nMIME-Version: 1.0\r\n"
            "Content-Type: multipart/mixed; boundary=b\r\n\r\n--b\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nhello\r\n"
            "--b\r\nContent-Type: application/octet-stream\r\nContent-Disposition: attachment; filename=a.bin\r\n"
            "Content-Transfer-Encoding: base64\r\n\r\nAAH/\r\n--b--\r\n"
        ).encode()
        r.answer = 500  # the first try fails, so that there is one to try again
        took = hand_over(raw, to, "ana@example.org")
        self.assertTrue(200 <= took <= 299, f"the server answered {took} to an email handed over")

        def about_it() -> WebhookEvent | None:
            events = [newer.verify(*g) for g in r.got[3:]]
            return next((e for e in events if e.type == EventType.RECEIVED), None)

        told = until("the webhook about the email that came", about_it)
        assert told.received is not None
        self.assertEqual((told.email, told.received.from_, told.received.to), (None, "ana@example.org", [to]))
        id = told.received.id
        self.addCleanup(lambda: code(lambda: admin.received.delete(id)))
        got = admin.received.get(id)
        c = got.content
        assert c is not None
        self.assertEqual(
            (
                got.to,
                got.from_,
                got.size,
                c.subject,
                c.from_,
                (c.text or "").strip(),
                c.message_id,
                c.date,
                c.partial,
            ),
            (
                to,
                "ana@example.org",
                len(raw),
                f"Héllo {RUN}",
                "Ana <ana@example.org>",
                "hello",
                "<1@example.org>",
                datetime(2030, 1, 1, tzinfo=UTC),
                False,
            ),
        )
        self.assertEqual([(f.filename, f.size) for f in c.attachments], [("a.bin", 3)])
        self.assertEqual(admin.received.raw(id), raw)
        self.assertEqual(admin.received.file(id, 1), bytes([0, 1, 255]))
        self.assertIn(id, [item.id for item in admin.received.all()])
        self.assertEqual(len(admin.received.list(limit=1).data), 1)

        # The try that failed is on record, is tried again when asked, and then delivered.
        owed = until(
            "the failed try on record",
            lambda: next(
                (
                    d
                    for d in admin.webhooks.deliveries(made.id, state=DeliveryState.PENDING).data
                    if d.inbound_id == id and d.attempts > 0
                ),
                None,
            ),
        )
        self.assertEqual(
            (
                owed.id,
                owed.type,
                owed.email_id,
                owed.last_status,
                owed.last_failure,
                owed.next_attempt_at is not None,
            ),
            (told.id, EventType.RECEIVED, None, 500, "status", True),
        )
        r.answer = 204
        admin.webhooks.retry_delivery(made.id, owed.id)
        delivered = until(
            "the delivery, once taken",
            lambda: next(
                (
                    d
                    for d in admin.webhooks.all_deliveries(made.id, DeliveryState.DELIVERED)
                    if d.id == owed.id
                ),
                None,
            ),
        )
        self.assertEqual(
            (delivered.attempts, delivered.last_status, delivered.delivered_at is not None), (2, 204, True)
        )
        ids = [next(v for k, v in g[0].items() if k.lower() == "webhook-id") for g in r.got]
        self.assertEqual(ids.count(told.id), 2, "the same webhook, under the same id, twice")
        self.assertEqual(
            code(lambda: admin.webhooks.retry_delivery(made.id, "0199-none")), ErrorCode.NOT_FOUND
        )

        admin.received.delete(id)
        self.assertEqual(code(lambda: admin.received.get(id)), ErrorCode.NOT_FOUND)
        admin.webhooks.delete(made.id)
        self.assertEqual(code(lambda: admin.webhooks.get(made.id)), ErrorCode.NOT_FOUND)

    def test_a_wrong_address_is_said_to_be_one(self) -> None:
        astray = CairnPost(URL + "/not-the-server", need("CAIRNPOST_ADMIN_KEY"))
        for call in (astray.health, lambda: astray.emails.get("0199"), astray.captured, astray.webhooks.list):
            with self.assertRaises((CairnPostError, TransportError, NotCapturingError)) as raised:
                call()
            err = raised.exception
            self.assertTrue(is_wrong_address(err) and not is_not_found(err), repr(err))
        self.assertEqual(code(lambda: astray.emails.get("0199")), ErrorCode.ROUTE_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
