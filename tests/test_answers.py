from __future__ import annotations

import json
import unittest
from collections.abc import Callable
from datetime import UTC, datetime

from cairnpost import CairnPost, Email, TransportError

from .stand import UP, serve

TO = Email(from_="app@example.com", to=["ana@example.org"], text="t")

#: Every call that reads an answer, each to be made against a server that
#: says something CairnPost never does.
ANSWERING: dict[str, Callable[[CairnPost], object]] = {
    "emails.send": lambda c: c.emails.send(TO),
    "emails.send_batch": lambda c: c.emails.send_batch([TO]),
    "emails.get": lambda c: c.emails.get("m"),
    "emails.cancel": lambda c: c.emails.cancel("m"),
    "emails.reschedule": lambda c: c.emails.reschedule("m", datetime(2030, 1, 31, 8, tzinfo=UTC)),
    "emails.file": lambda c: c.emails.file("m", 1),
    "limits": lambda c: c.limits(),
    "health": lambda c: c.health(),
    "captured": lambda c: c.captured(),
    "suppressions.list": lambda c: c.suppressions.list(),
    "suppressions.add": lambda c: c.suppressions.add("example.com", "a@example.org"),
    "suppressions.lift": lambda c: c.suppressions.lift("example.com", "a@example.org"),
    "suppressions.lift_all": lambda c: c.suppressions.lift_all("example.com"),
    "webhooks.create": lambda c: c.webhooks.create("https://app.example.com/hook"),
    "webhooks.list": lambda c: c.webhooks.list(),
    "webhooks.get": lambda c: c.webhooks.get("w"),
    "webhooks.update": lambda c: c.webhooks.update("w"),
    "webhooks.delete": lambda c: c.webhooks.delete("w"),
    "webhooks.rotate_secret": lambda c: c.webhooks.rotate_secret("w"),
    "webhooks.resume": lambda c: c.webhooks.resume("w"),
    "webhooks.test": lambda c: c.webhooks.test("w"),
    "webhooks.deliveries": lambda c: c.webhooks.deliveries("w"),
    "webhooks.retry_delivery": lambda c: c.webhooks.retry_delivery("w", "d"),
    "templates.create": lambda c: c.templates.create(name="n", subject="s"),
    "templates.list": lambda c: c.templates.list(),
    "templates.get": lambda c: c.templates.get("t"),
    "templates.update": lambda c: c.templates.update("t"),
    "templates.delete": lambda c: c.templates.delete("t"),
    "received.list": lambda c: c.received.list(),
    "received.get": lambda c: c.received.get("r"),
    "received.raw": lambda c: c.received.raw("r"),
    "received.file": lambda c: c.received.file("r", 1),
    "received.delete": lambda c: c.received.delete("r"),
}

#: These read no answer of their own: they walk a call that is there.
WALKS = {"suppressions.all", "webhooks.all_deliveries", "received.all"}

AT = (
    '"created_at":"2030-01-01T00:00:00Z","updated_at":"2030-01-01T00:00:00Z",'
    '"received_at":"2030-01-01T00:00:00Z","kept_until":"2030-01-01T00:00:00Z"'
)


class AnAnswer(unittest.TestCase):
    def takes(self, c: CairnPost, name: str) -> bool:
        """Makes a call; says whether its answer was taken for CairnPost's."""
        try:
            ANSWERING[name](c)
        except TransportError as err:
            return err.reason != "not_cairnpost"
        return True

    def taken(self, name: str, status: int, body: str) -> bool:
        """Makes a call against a server that answers `body`; says whether it was taken."""
        return self.takes(serve(self, status, body).client, name)

    # Something else at the address, or between, can answer 200 to
    # anything. None of it may read as "done", "no" or "none".
    def test_no_call_takes_one_that_is_not_cairnposts(self) -> None:
        bodies = {
            "an empty object": "{}",
            "null": "null",
            "a page": "<html>maintenance</html>",
            "nothing": "",
            "every field null": (
                '{"id":null,"state":null,"data":null,"added":null,"lifted":null,"delivered":null,'
                '"driver":null,"status":null,"created_at":null,"updated_at":null,"received_at":null,'
                '"kept_until":null}'
            ),
        }
        for what, body in bodies.items():
            c = serve(self, 200, body).client
            took = [name for name in ANSWERING if self.takes(c, name)]
            self.assertEqual(took, [], f"answered {what}")

    # A record says when it was made: one that does not was not written
    # by CairnPost, alone or in a list.
    def test_a_record_without_its_times_is_refused(self) -> None:
        records = [
            "emails.get",
            "captured",
            "suppressions.list",
            "webhooks.create",
            "webhooks.list",
            "webhooks.get",
            "webhooks.update",
            "webhooks.rotate_secret",
            "webhooks.resume",
            "webhooks.deliveries",
            "templates.create",
            "templates.list",
            "templates.get",
            "templates.update",
            "received.list",
            "received.get",
        ]
        c = serve(self, 200, '{"id":"x","more":false,"data":[{"id":"x"}]}').client
        took = [name for name in records if self.takes(c, name)]
        self.assertEqual(took, [])

    # An answer can be a whole object of CairnPost's kind and still not
    # be the answer to what was asked.
    def test_one_about_something_else_is_refused(self) -> None:
        answers = {
            "emails.cancel": '{"id":"req-123","state":"cancelled"}',
            "emails.reschedule": '{"id":"req-123","scheduled_at":"2030-01-31T08:00:00Z"}',
            "suppressions.lift": '{"lifted":0}',
            "suppressions.lift_all": '{"lifted":-1}',
            "webhooks.retry_delivery": '{"state":"error"}',
            "webhooks.create": '{"id":"w1",' + AT + "}",
            "webhooks.rotate_secret": '{"id":"w1",' + AT + "}",
            "limits": '{"driver":""}',
            "webhooks.list": '{"data":[{' + AT + "}]}",
            "templates.list": '{"more":false,"data":[{' + AT + "}]}",
            "received.list": '{"data":[{' + AT + "}]}",
            "webhooks.deliveries": '{"data":[{' + AT + "}]}",
            "suppressions.list": '{"data":[{' + AT + "}]}",
            "captured": '{"data":[{"at":"2030-01-01T00:00:00Z"}]}',
        }
        took = [f"{name} took {body}" for name, body in answers.items() if self.taken(name, 200, body)]
        self.assertEqual(took, [])
        # Each of these lacks one thing only, or says one thing wrong.
        lacking = [
            ("emails.cancel", '{"id":"m","state":"scheduled"}'),
            ("emails.cancel", '{"id":"m"}'),
            # The email's own record, which is at the path a move is asked
            # at, and says the time it had.
            (
                "emails.reschedule",
                '{"id":"m","state":"scheduled","scheduled_at":"2030-01-01T08:00:00Z",' + AT + "}",
            ),
            ("emails.reschedule", '{"id":"m"}'),
            ("emails.reschedule", '{"id":"m","scheduled_at":"0001-01-01T00:00:00Z"}'),
            ("health", UP.replace('"events":"off"', '"events":""')),
            ("templates.list", '{"data":[]}'),
            ("suppressions.list", '{"data":[{"domain":"example.com","reason":"manual",' + AT + "}]}"),
            ("suppressions.list", '{"data":[{"address":"a@example.org","reason":"manual",' + AT + "}]}"),
            # A time that was never set is not a time.
            (
                "emails.get",
                '{"id":"m","created_at":"0001-01-01T00:00:00Z","updated_at":"2030-01-01T00:00:00Z"}',
            ),
            ("webhooks.get", '{"id":"w","created_at":"0001-01-01T00:00:00Z"}'),
        ]
        took = [f"{name} took {body}" for name, body in lacking if self.taken(name, 200, body)]
        self.assertEqual(took, [])
        # Health says each of its fields.
        said = json.loads(UP)
        self.assertEqual(len(said), 8)
        for field in said:
            less = json.dumps({name: value for name, value in said.items() if name != field})
            self.assertFalse(self.taken("health", 200, less), f"health without its {field}")
        # A batch says its list also when no email was asked.
        for body in ["{}", '{"data":null}']:
            with self.assertRaises(TransportError, msg=f"a batch of none took {body}") as raised:
                serve(self, 200, body).client.emails.send_batch([])
            self.assertEqual(raised.exception.reason, "not_cairnpost")
        self.assertEqual(serve(self, 200, '{"data":[]}').client.emails.send_batch([]), [])

    # The table above is held to every call there is: a new call is put
    # in front of the same answers, or this fails.
    def test_every_call_is_in_the_table(self) -> None:
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
        calls = {
            prefix + name
            for prefix, part in parts.items()
            for name, value in vars(type(part)).items()
            if callable(value) and not name.startswith("_")
        }
        self.assertEqual(calls - WALKS - set(ANSWERING), set())

    # A call that answers nothing is done only on CairnPost's own 204.
    def test_a_call_that_answers_nothing_wants_a_204(self) -> None:
        for name in ["webhooks.delete", "templates.delete", "received.delete"]:
            for status in [200, 202]:
                self.assertFalse(self.taken(name, status, ""), f"{name} took a {status}")
            ANSWERING[name](serve(self, 204, "").client)

    # What CairnPost says of nothing is still read as nothing.
    def test_an_empty_list_and_a_no_are_still_read(self) -> None:
        c = serve(self, 200, '{"data":[],"added":false,"lifted":0,"delivered":false,"more":false}').client
        page = c.suppressions.list()
        self.assertEqual((page.data, page.next), ([], None))
        self.assertEqual(c.webhooks.list(), [])
        templates = c.templates.list()
        self.assertEqual((templates.data, templates.more), ([], False))
        self.assertEqual(c.captured(), [])
        self.assertIs(c.suppressions.add("example.com", "a@example.org"), False)
        self.assertEqual(c.suppressions.lift_all("example.com"), 0)
        self.assertIs(c.webhooks.test("w").delivered, False)


if __name__ == "__main__":
    unittest.main()
