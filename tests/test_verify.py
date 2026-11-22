from __future__ import annotations

import base64
import hashlib
import hmac
import unittest
from datetime import UTC, datetime
from email.message import Message

from cairnpost import BounceType, EventEmail, EventType, Verifier, WebhookError, WebhookEvent

# Which webhooks are read and which refused is in the shared cases
# (test_cases_webhooks.py). What follows is this client's own: the shapes
# a body and its headers come in here, a call that is itself wrong, and a
# secret that is not text.

BOUNCE = (
    '{"type":"email.bounced","created_at":"2030-01-01T00:00:05Z","data":{"email_id":"m1","from":"app@example.com",'
    '"to":["gone@example.org"],"created_at":"2030-01-01T00:00:00Z","code":"5.1.1","reason":"permanent_failure",'
    '"bounce":{"type":"Permanent"},"suppressed":true}}'
)
SIGNING_KEY = b"a signing key of thirty-two bytes"
SECRET = "whsec_" + base64.b64encode(SIGNING_KEY).decode()
AT = int(datetime(2030, 1, 1, 0, 0, 10, tzinfo=UTC).timestamp())


def signature(key: bytes, id: str, when: int, body: str) -> str:
    """What a sender holding the key would put in the header."""
    return (
        "v1,"
        + base64.b64encode(hmac.new(key, f"{id}.{when}.{body}".encode(), hashlib.sha256).digest()).decode()
    )


def headers(prefix: str, id: str, when: int, sig: str) -> dict[str, str]:
    return {prefix + "id": id, prefix + "timestamp": str(when), prefix + "signature": sig}


GOOD = signature(SIGNING_KEY, "dlv-1", AT, BOUNCE)
OURS = headers("webhook-", "dlv-1", AT, GOOD)


class AWebhook(unittest.TestCase):
    def test_a_body_is_read_as_bytes_and_headers_as_the_standard_librarys_servers_give_them(self) -> None:
        v = Verifier(SECRET, now=lambda: float(AT))
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
        self.assertEqual(v.verify(OURS, BOUNCE), want)
        self.assertEqual(
            v.verify(
                {"Webhook-Id": "dlv-1", "WEBHOOK-TIMESTAMP": str(AT), "webhook-signature": f" {GOOD} "},
                BOUNCE.encode(),
            ),
            want,
        )
        message = Message()
        for name, value in OURS.items():
            message[name.title()] = value
        self.assertEqual(v.verify(message, bytearray(BOUNCE.encode())), want)
        self.assertNotIn("whsec", repr(v) + str(vars(v) if hasattr(v, "__dict__") else ""))

    # A body is read as JSON the way the other clients read it: what is
    # not JSON is not read, though Python's own decoder takes it, and a
    # number longer than Python reads as an int is still a number.
    def test_a_body_is_json_as_every_client_reads_it(self) -> None:
        v = Verifier(SECRET, now=lambda: float(AT))

        def given(extra: str) -> tuple[dict[str, str], str]:
            body = BOUNCE[:-1] + ',"extra":' + extra + "}"
            return headers("webhook-", "dlv-1", AT, signature(SIGNING_KEY, "dlv-1", AT, body)), body

        for token in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaises(WebhookError, msg=token) as refused:
                v.verify(*given(token))
            self.assertEqual(refused.exception.reason, "payload", token)
        for token in ("30", "9" * 4300, "9" * 4301, "-" + "9" * 20000, "1e400"):
            self.assertEqual(v.verify(*given(token)).type, EventType.BOUNCED, token[:12])

    # A call that is itself wrong is said as that, not as a forged webhook.
    def test_a_call_that_is_wrong_is_a_type_error(self) -> None:
        v = Verifier(SECRET, now=lambda: float(AT))
        for wrong in [None, {"type": "email.bounced"}, 7]:
            with self.assertRaises(TypeError):
                v.verify(OURS, wrong)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            v.verify(None, BOUNCE)  # type: ignore[arg-type]

    # No secret, no verifier: nothing signed with no key at all is ever taken.
    def test_a_secret_that_is_not_text_or_holds_a_line_break_is_refused(self) -> None:
        for bad in ["whsec_c2VjcmV0\n=", None, b"whsec_c2VjcmV0"]:
            with self.assertRaises(WebhookError, msg=repr(bad)) as raised:
                Verifier(bad)  # type: ignore[arg-type]
            self.assertEqual(raised.exception.reason, "secret", bad)


if __name__ == "__main__":
    unittest.main()
