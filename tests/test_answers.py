from __future__ import annotations

import unittest

from cairnpost import TransportError

from .stand import serve

# The answers every client must take or refuse are the shared cases
# (test_cases_answers.py). What follows is this client's own: a batch of
# no email, and what a call reads out of an answer that says "none".


class AnAnswer(unittest.TestCase):
    # A batch says its list also when no email was asked.
    def test_a_batch_of_none_is_held_to_its_answer_too(self) -> None:
        for body in ["{}", '{"data":null}']:
            with self.assertRaises(TransportError, msg=f"a batch of none took {body}") as raised:
                serve(self, 200, body).client.emails.send_batch([])
            self.assertEqual(raised.exception.reason, "not_cairnpost")
        self.assertEqual(serve(self, 200, '{"data":[]}').client.emails.send_batch([]), [])

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
