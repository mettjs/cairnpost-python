from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

from cairnpost import CairnPostError, Email, TransportError, may_have_sent
from cairnpost._wait import wait_of

from .stand import Stand

EMAIL = Email(from_="app@example.com", to=["ana@example.org"], subject="Welcome", text="Hello.")


class ARetryAfterSaidTwice(unittest.TestCase):
    # A header said more than once is handed over as one value with a
    # comma between: so two waits are none, and a date cut in two at its
    # comma is that date. The Go client reads it the same.
    def test_it_is_read_as_one_value(self) -> None:
        date = format_datetime(datetime.now(UTC) + timedelta(seconds=90), usegmt=True)
        said = [["7", "9"], ["7", "7"], ["soon", "9"], [date[:3], date[5:]]]
        s = Stand(self, lambda n, seen: (503, "", {"Retry-After": said[n - 1]}))
        for values in said:
            with self.assertRaises(CairnPostError) as raised:
                s.client.emails.get("x")
            wait = raised.exception.retry_after
            self.assertEqual(raised.exception.status, 503)
            if values is said[-1]:
                self.assertTrue(wait is not None and 80 < wait <= 91, wait)
            else:
                self.assertIsNone(wait, values)

    def test_no_header_at_all_is_no_wait(self) -> None:
        self.assertIsNone(wait_of(None))
        self.assertIsNone(wait_of(""))


class AWaitNoOtherClientCouldBeGiven(unittest.TestCase):
    # A date at the end of the calendar, an hour west of it, is past what
    # Python can count to: no wait, and no error of Python's own.
    def test_a_date_past_the_calendar_is_no_wait(self) -> None:
        self.assertIsNone(wait_of("Fri, 31 Dec 9999 23:59:59 -0100"))
        self.assertIsNone(wait_of("Mon, 01 Jan 0001 00:00:00 +0100"))

    # Python reads no int of more than some 4300 digits. Such a number is
    # still JSON, so the answer is read, and the wait is none.
    def test_a_number_too_long_for_an_int_is_still_read(self) -> None:
        later = '{"data":[{"error":{"statusCode":429,"name":"rate_limit_exceeded","message":"Later.","retry_after":%s}}]}'
        s = Stand(self, lambda n, seen: (207, later % ("9" * [4300, 4301, 20000][n - 1])))
        for digits in (4300, 4301, 20000):
            err = s.client.emails.send_batch([EMAIL])[0].error
            assert err is not None, digits
            self.assertEqual(
                (err.code, err.retry_after, may_have_sent(err)), ("rate_limit_exceeded", None, False)
            )

    # NaN and Infinity are not JSON: the other clients cannot read an
    # answer that holds one, so this one does not either.
    def test_what_is_not_json_is_not_read(self) -> None:
        later = '{"data":[{"error":{"statusCode":429,"name":"rate_limit_exceeded","message":"Later.","retry_after":%s}}]}'
        odd = ["NaN", "Infinity", "-Infinity"]
        s = Stand(self, lambda n, seen: (207, later % odd[n - 1]))
        for token in odd:
            with self.assertRaises(TransportError, msg=token):
                s.client.emails.send_batch([EMAIL])
