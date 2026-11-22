from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qsl

from .asking import ASKING, WALKS, ask
from .cases import cases, instants, listed, only, saying
from .stand import KEY, serve


class EachCall(unittest.TestCase):
    # The table is held to every call there is, so that a new call is put
    # in front of the shared cases, or this fails.
    def test_it_is_in_the_table(self) -> None:
        c = serve(self, 200, "{}").client
        # The client, and each part of it: whatever it holds that has
        # calls of its own.
        parts: dict[str, object] = {"": c}
        for name in dir(c):
            part = getattr(c, name)
            if not name.startswith("_") and not callable(part):
                parts[name + "."] = part
        self.assertEqual(
            sorted(parts), ["", "emails.", "received.", "suppressions.", "templates.", "webhooks."]
        )
        there = {
            prefix + name
            for prefix, part in parts.items()
            for name, value in vars(type(part)).items()
            if callable(value) and not name.startswith("_")
        }
        self.assertEqual(there, set(ASKING) | WALKS)

    # Each call sends what every client sends for it, and takes the
    # answer the server gives.
    def test_it_sends_what_it_should_and_takes_the_servers_answer(self) -> None:
        described = listed(
            cases("calls.json", ["calls"]), "calls", ["name", "route", "key", "sends", "answer"]
        )
        for c in described:
            name, sends = c["name"], c["sends"]
            only(f"what {name} sends", sends, ["method", "path", "query", "idempotency_key", "body"])
            s = saying(self, c["answer"])
            ask(name)(s.client)
            self.assertEqual(len(s.seen), 1, f"{name} made {len(s.seen)} requests")
            got = s.seen[0]
            query = parse_qsl(got.query, keep_blank_values=True)
            self.assertEqual(len(dict(query)), len(query), f"{name} says a thing twice in {got.query}")
            self.assertEqual(
                (got.method, got.path, dict(query), got.auth, got.idem),
                (
                    sends["method"],
                    sends["path"],
                    sends.get("query", {}),
                    "" if c["key"] == "none" else f"Bearer {KEY}",
                    sends.get("idempotency_key", ""),
                ),
                f"what {name} sent",
            )
            # Each stand is closed as soon as its call is made, not all at the end.
            self.doCleanups()
            if "body" not in sends:
                self.assertEqual(
                    (got.body, got.content_type), ("", ""), f"{name} sent a body where none is sent"
                )
            else:
                self.assertEqual(got.content_type, "application/json", name)
                self.assertEqual(
                    instants(json.loads(got.body)), instants(sends["body"]), f"the body {name} sent"
                )
        self.assertEqual(
            sorted(ASKING),
            sorted(c["name"] for c in described),
            "the calls of this client, and those calls.json describes",
        )


if __name__ == "__main__":
    unittest.main()
