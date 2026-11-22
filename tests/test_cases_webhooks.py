from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any

from cairnpost import Verifier, WebhookError, WebhookEvent

from .cases import cases, listed, only


def _stamp(at: datetime | None) -> str:
    return "" if at is None else at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def plain(e: WebhookEvent) -> dict[str, Any]:
    """A verified event in the form the shared cases write one.

    Every field said, a time as its instant in UTC, "" for what is not there.
    """
    out: dict[str, Any] = {"id": e.id, "type": e.type, "at": _stamp(e.at)}
    if e.email is not None:
        m = e.email
        out["email"] = {
            "id": m.id,
            "from": m.from_,
            "to": m.to,
            "created_at": _stamp(m.created_at),
            "code": m.code or "",
            "reason": m.reason or "",
            "bounce": m.bounce_type or "",
            "suppressed": m.suppressed,
        }
    if e.suppression is not None:
        s = e.suppression
        out["suppression"] = {"domain": s.domain, "address": s.address, "reason": s.reason}
    if e.received is not None:
        r = e.received
        out["received"] = {"id": r.id, "from": r.from_, "to": r.to, "received_at": _stamp(r.received_at)}
    return out


class AWebhook(unittest.TestCase):
    # A webhook is read when the endpoint's secret signed it and it says
    # what it is about, and refused otherwise, each for its own reason.
    def test_it_is_read_only_when_it_is_the_endpoints(self) -> None:
        file = cases("webhooks.json", ["secret", "now", "secrets", "cases"])
        only("the secrets", file["secrets"], ["taken", "refused"])
        self.assertTrue(
            file["secrets"]["taken"] and file["secrets"]["refused"], "no secret to take, or to refuse"
        )
        for secret in file["secrets"]["taken"]:
            Verifier(secret)
        for secret in file["secrets"]["refused"]:
            with self.assertRaises(WebhookError, msg=repr(secret)) as bad:
                Verifier(secret)
            self.assertEqual(bad.exception.reason, "secret", repr(secret))
        for c in listed(file, "cases", ["name", "headers", "body", "tolerance", "want"]):
            name, want = c["name"], c["want"]
            only(f"what {name} wants", want, ["refused", "event"])
            self.assertNotEqual("refused" in want, "event" in want, f"{name} wants an event or a refusal")
            v = Verifier(
                file["secret"], now=lambda: float(file["now"]), tolerance=float(c.get("tolerance", 0))
            )
            if "refused" in want:
                self.assertIn(want["refused"], ["unsigned", "signature", "stale", "payload"], name)
                with self.assertRaises(WebhookError, msg=name) as refused:
                    v.verify(c["headers"], c["body"])
                self.assertEqual(refused.exception.reason, want["refused"], name)
            else:
                self.assertEqual(plain(v.verify(c["headers"], c["body"])), want["event"], name)


if __name__ == "__main__":
    unittest.main()
