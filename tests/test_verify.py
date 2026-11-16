from __future__ import annotations

import base64
import hashlib
import hmac
import unittest
from datetime import UTC, datetime
from email.message import Message

from cairnpost import (
    DEFAULT_TOLERANCE,
    BounceType,
    EventEmail,
    EventReceived,
    EventSuppression,
    EventType,
    Reason,
    Verifier,
    WebhookError,
    WebhookEvent,
)

BOUNCE = (
    '{"type":"email.bounced","created_at":"2030-01-01T00:00:05Z","data":{"email_id":"m1","from":"app@example.com",'
    '"to":["gone@example.org"],"created_at":"2030-01-01T00:00:00Z","code":"5.1.1","reason":"permanent_failure",'
    '"bounce":{"type":"Permanent"},"suppressed":true}}'
)
SIGNING_KEY = b"a signing key of thirty-two bytes"
SECRET = "whsec_" + base64.b64encode(SIGNING_KEY).decode()
AT = int(datetime(2030, 1, 1, 0, 0, 10, tzinfo=UTC).timestamp())
STAMP = '"created_at":"2030-01-01T00:00:05Z"'


def signature(key: bytes, id: str, when: int, body: str) -> str:
    """What a sender holding the key would put in the header."""
    return (
        "v1,"
        + base64.b64encode(hmac.new(key, f"{id}.{when}.{body}".encode(), hashlib.sha256).digest()).decode()
    )


def headers(prefix: str, id: str, when: int, sig: str) -> dict[str, str]:
    return {prefix + "id": id, prefix + "timestamp": str(when), prefix + "signature": sig}


def verifier(tolerance: float = DEFAULT_TOLERANCE) -> Verifier:
    return Verifier(SECRET, now=lambda: float(AT), tolerance=tolerance)


def signed(v: Verifier, id: str, body: str) -> WebhookEvent:
    return v.verify(headers("webhook-", id, AT, signature(SIGNING_KEY, id, AT, body)), body)


class AWebhook(unittest.TestCase):
    def refused(self, why: str, run: object) -> str:
        with self.assertRaises(WebhookError, msg=why) as raised:
            run()  # type: ignore[operator]
        return raised.exception.reason

    def test_one_signed_by_the_endpoints_secret_is_read(self) -> None:
        v = verifier()
        want = WebhookEvent(
            id="dlv-1",
            type=EventType.BOUNCED,
            at=datetime(2030, 1, 1, 0, 0, 5, tzinfo=UTC),
            email=EventEmail(
                id="m1",
                from_="app@example.com",
                to=["gone@example.org"],
                created_at=datetime(2030, 1, 1, tzinfo=UTC),
                code="5.1.1",
                reason="permanent_failure",
                bounce_type=BounceType.PERMANENT,
                suppressed=True,
            ),
        )
        good = signature(SIGNING_KEY, "dlv-1", AT, BOUNCE)
        for prefix in ["webhook-", "svix-"]:
            self.assertEqual(v.verify(headers(prefix, "dlv-1", AT, good), BOUNCE), want)
        # The body as bytes; the headers in any case, and as the standard library's servers give them.
        self.assertEqual(
            v.verify(
                {"Webhook-Id": "dlv-1", "WEBHOOK-TIMESTAMP": str(AT), "webhook-signature": f" {good} "},
                BOUNCE.encode(),
            ),
            want,
        )
        message = Message()
        for name, value in headers("Webhook-", "dlv-1", AT, good).items():
            message[name] = value
        self.assertEqual(v.verify(message, bytearray(BOUNCE.encode())), want)
        self.assertNotIn("whsec", repr(v) + str(vars(v) if hasattr(v, "__dict__") else ""))
        # One of several signatures is enough: a secret being changed over is signed with both.
        other = signature(b"another key", "dlv-1", AT, BOUNCE)
        for both in [f"{other} v2,zzz {good}", f"{good} {other}"]:
            v.verify(headers("svix-", "dlv-1", AT, both), BOUNCE)
        # The test webhook is about no email, and a type not known is passed on.
        tried = signed(v, "t", '{"type":"webhook.test",%s,"data":{}}' % STAMP)
        self.assertEqual(
            tried, WebhookEvent(id="t", type=EventType.TEST, at=datetime(2030, 1, 1, 0, 0, 5, tzinfo=UTC))
        )
        passed = signed(
            v, "t", '{"type":"email.opened",%s,"data":{"email_id":"m","to":["a@example.org"]}}' % STAMP
        )
        self.assertEqual((passed.type, passed.email.id if passed.email else None), ("email.opened", "m"))
        # Also one that starts with "email." and is about no email that was sent.
        forwarded = signed(v, "t", '{"type":"email.forwarded",%s,"data":{"inbound_id":"in-1"}}' % STAMP)
        self.assertEqual(
            forwarded,
            WebhookEvent(id="t", type="email.forwarded", at=datetime(2030, 1, 1, 0, 0, 5, tzinfo=UTC)),
        )
        # A call that is itself wrong is said as that, not as a forged webhook.
        ours = headers("webhook-", "dlv-1", AT, good)
        for wrong in [None, {"type": "email.bounced"}, 7]:
            with self.assertRaises(TypeError):
                v.verify(ours, wrong)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            v.verify(None, BOUNCE)  # type: ignore[arg-type]

    def test_what_is_not_the_endpoints_is_refused(self) -> None:
        v = verifier()
        good = signature(SIGNING_KEY, "dlv-1", AT, BOUNCE)
        late, early = AT - int(DEFAULT_TOLERANCE) - 1, AT + int(DEFAULT_TOLERANCE) + 1
        cases: list[tuple[str, dict[str, str], str, str]] = [
            (
                "another key",
                headers("webhook-", "dlv-1", AT, signature(b"another key", "dlv-1", AT, BOUNCE)),
                BOUNCE,
                "signature",
            ),
            ("a changed body", headers("webhook-", "dlv-1", AT, good), BOUNCE + " ", "signature"),
            ("another id", headers("webhook-", "dlv-2", AT, good), BOUNCE, "signature"),
            ("a moved timestamp", headers("webhook-", "dlv-1", AT + 1, good), BOUNCE, "signature"),
            (
                "an old webhook",
                headers("webhook-", "dlv-1", late, signature(SIGNING_KEY, "dlv-1", late, BOUNCE)),
                BOUNCE,
                "stale",
            ),
            (
                "one from the future",
                headers("webhook-", "dlv-1", early, signature(SIGNING_KEY, "dlv-1", early, BOUNCE)),
                BOUNCE,
                "stale",
            ),
            ("no headers", {}, BOUNCE, "unsigned"),
            (
                "a time that is none",
                {"webhook-id": "a", "webhook-timestamp": "now", "webhook-signature": good},
                BOUNCE,
                "unsigned",
            ),
            (
                "a time in another form",
                {"webhook-id": "a", "webhook-timestamp": "1.89e9", "webhook-signature": good},
                BOUNCE,
                "unsigned",
            ),
            (
                "a time in other digits",
                {"webhook-id": "a", "webhook-timestamp": "١٨٩٣٤٥٦٠١٠", "webhook-signature": good},
                BOUNCE,
                "unsigned",
            ),
            (
                "a signature of no use",
                headers("webhook-", "dlv-1", AT, "v1,not base64!"),
                BOUNCE,
                "signature",
            ),
            ("a signature cut short", headers("webhook-", "dlv-1", AT, good[:-5]), BOUNCE, "signature"),
            (
                "a signature with more after it",
                headers("webhook-", "dlv-1", AT, good + "!!"),
                BOUNCE,
                "signature",
            ),
            (
                "a signature under another version",
                headers("webhook-", "dlv-1", AT, good.replace("v1,", "v2,")),
                BOUNCE,
                "signature",
            ),
            (
                "signed, not a webhook",
                headers("webhook-", "x", AT, signature(SIGNING_KEY, "x", AT, "hello")),
                "hello",
                "payload",
            ),
            (
                "signed, a list",
                headers("webhook-", "x", AT, signature(SIGNING_KEY, "x", AT, "[]")),
                "[]",
                "payload",
            ),
        ]
        for why, h, body, want in cases:
            self.assertEqual(self.refused(why, lambda h=h, body=body: v.verify(h, body)), want, why)
        # Within the tolerance either way is taken, and the tolerance can be set.
        edge = AT - int(DEFAULT_TOLERANCE)
        at_edge = headers("webhook-", "e", edge, signature(SIGNING_KEY, "e", edge, BOUNCE))
        v.verify(at_edge, BOUNCE)
        self.assertEqual(
            self.refused("a tolerance of a second", lambda: verifier(1).verify(at_edge, BOUNCE)), "stale"
        )
        # Signed, about an email, and not saying which: refused, not handed on with nothing in it.
        for body in [
            '{"type":"email.bounced",%s}' % STAMP,
            '{"type":"email.bounced",%s,"data":{"email_id":"m","to":"a@example.org","bounce":{"type":"Permanent"}}}'
            % STAMP,
            '{"type":"email.bounced",%s,"data":{"email_id":"m","to":["a@example.org"]}}' % STAMP,
            '{"type":"email.bounced",%s,"data":{"email_id":"m","to":["a@example.org"],"bounce":{}}}' % STAMP,
            '{"type":"email.delivered",%s,"data":{"email_id":"m","to":[]}}' % STAMP,
            '{"type":"email.delivered","data":{"email_id":"m","to":["a@example.org"]}}',
            '{%s,"data":{"email_id":"m","to":["a@example.org"]}}' % STAMP,
        ]:
            self.assertEqual(self.refused(body, lambda body=body: signed(v, "p", body)), "payload", body)
        # No secret, no verifier: nothing signed with no key at all is ever taken.
        for bad in [
            "",
            "c2VjcmV0",
            "whsec_",
            "whsec_not base64!",
            "whsec_c2VjcmV0!",
            "whsec_c2VjcmV0\n=",
            None,
            b"whsec_c2VjcmV0",
        ]:
            self.assertEqual(self.refused(repr(bad), lambda bad=bad: Verifier(bad)), "secret", bad)
        Verifier(f" {SECRET}\n")

    def test_a_suppression_told_on_its_own_is_read(self) -> None:
        v = verifier()
        e = signed(
            v,
            "dlv-1",
            '{"type":"address.suppressed","created_at":"2030-01-01T00:00:00Z","data":{"domain":"example.com","address":"ana@example.org","reason":"bounce"}}',
        )
        self.assertEqual(
            (e.type, e.email, e.suppression),
            (
                EventType.ADDRESS_SUPPRESSED,
                None,
                EventSuppression(domain="example.com", address="ana@example.org", reason=Reason.BOUNCE),
            ),
        )
        for data in [
            "{}",
            '{"domain":"example.com"}',
            '{"domain":"example.com","address":"ana@example.org"}',
        ]:
            without = '{"type":"address.suppressed","created_at":"2030-01-01T00:00:00Z","data":%s}' % data
            self.assertEqual(
                self.refused(data, lambda without=without: signed(v, "dlv-2", without)), "payload"
            )

    def test_an_email_that_came_is_told_by_its_own_event(self) -> None:
        v = verifier()
        e = signed(
            v,
            "dlv-1",
            '{"type":"email.received","created_at":"2030-01-01T00:00:00Z","data":{"inbound_id":"in-1","from":"","to":["help@example.com"],"received_at":"2030-01-01T00:00:00Z"}}',
        )
        self.assertEqual(
            (e.email, e.received),
            (
                None,
                EventReceived(
                    id="in-1", from_="", to=["help@example.com"], received_at=datetime(2030, 1, 1, tzinfo=UTC)
                ),
            ),
        )
        nameless = '{"type":"email.received","created_at":"2030-01-01T00:00:00Z","data":{"from":"a@example.org","to":["help@example.com"]}}'
        self.assertEqual(self.refused("no id", lambda: signed(v, "dlv-1", nameless)), "payload")


if __name__ == "__main__":
    unittest.main()
