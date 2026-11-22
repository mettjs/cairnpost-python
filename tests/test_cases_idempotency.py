from __future__ import annotations

import unittest
from collections.abc import Callable
from dataclasses import replace

from cairnpost import CairnPost, Email

from .cases import cases, listed, saying

EMAIL = Email(from_="app@example.com", to=["ana@example.org"], subject="Welcome", text="Hello.")

#: The two calls that take a key, under the names the cases know them by.
SENDS: dict[str, Callable[[CairnPost, str, int], object]] = {
    "emails.send": lambda c, key, _: c.emails.send(replace(EMAIL, idempotency_key=key)),
    "emails.send_batch": lambda c, key, emails: c.emails.send_batch([EMAIL] * emails, idempotency_key=key),
}


class AnIdempotencyKey(unittest.TestCase):
    # An idempotency key goes out as it was given, or the send is not
    # made: a key a header cannot carry as it is would be changed on the
    # way, and the send would quietly not be idempotent. So for a send and
    # for a batch alike, and the refusal does not repeat the key.
    def test_it_is_sent_as_it_is_or_not_at_all(self) -> None:
        file = cases("idempotency.json", ["taken", "refused"])
        for name in ("taken", "refused"):
            self.assertTrue(
                isinstance(file[name], list) and file[name], f"the file holds no key under {name}"
            )
        described = {
            c["name"]: c
            for c in listed(
                cases("calls.json", ["calls"]), "calls", ["name", "route", "key", "sends", "answer"]
            )
        }
        for name, send in SENDS.items():
            self.assertIn(name, described, "the cases describe no call of that name")
            answer = described[name]["answer"]
            # As many emails as the batch's answer in the cases tells of.
            data = answer["json"].get("data")
            emails = len(data) if isinstance(data, list) else 1
            for key in file["taken"]:
                s = saying(self, answer)
                send(s.client, key, emails)
                self.assertEqual(len(s.seen), 1, f"{name} with the key {key!r}")
                self.assertEqual(s.seen[0].idem, key, f"what {name} sent the key {key!r} as")
                # Each case had a server of its own: closed now, not at the end.
                self.doCleanups()
            s = saying(self, answer)
            for key in file["refused"]:
                with self.assertRaises(ValueError, msg=f"{name} with the key {key!r}") as bad:
                    send(s.client, key, emails)
                self.assertEqual(len(s.seen), 0, f"{name} with the key {key!r} made a request")
                shown = str(bad.exception) + repr(bad.exception)
                for i in range(len(key) - 5):
                    self.assertNotIn(
                        key[i : i + 6], shown, f"the refusal of the key {key!r} repeats part of it"
                    )
            self.doCleanups()
