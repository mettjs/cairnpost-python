from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from cairnpost import CairnPostError, Email, ErrorCode, may_have_sent
from cairnpost._wait import wait_of

from .cases import cases, listed
from .stand import Stand

EMAIL = Email(from_="app@example.com", to=["ana@example.org"], subject="Welcome", text="Hello.")


class AWait(unittest.TestCase):
    # A caller sleeps for the wait an error says, so every client reads
    # the same wait in the same answer: in the Retry-After header of a
    # refusal, in what a batch's answer says of one email, and in a value
    # read at a time that is said.
    def test_it_is_read_as_every_client_reads_it(self) -> None:
        file = cases("waits.json", ["header", "batch", "read"])
        header = listed(file, "header", ["given", "seconds"])
        batch = listed(file, "batch", ["given", "seconds"])
        for k in listed(file, "read", ["now", "given", "seconds"]):
            now = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=k["now"])
            self.assertEqual(
                wait_of(k["given"], now), k["seconds"], f"the wait read in {k['given']!r} at {k['now']}"
            )

        down = '{"statusCode":503,"name":"unavailable","message":"Down."}'
        s = Stand(self, lambda n, seen: (503, down, {"Retry-After": header[n - 1]["given"]}))
        for k in header:
            with self.assertRaises(CairnPostError) as raised:
                s.client.emails.send(EMAIL)
            self.assertEqual(raised.exception.code, ErrorCode.UNAVAILABLE, k["given"])
            self.assertEqual(
                raised.exception.retry_after,
                k["seconds"],
                f"the wait read in a Retry-After of {k['given']!r}",
            )

        # As it is written in the cases, not read and written again.
        later = '{"data":[{"error":{"statusCode":429,"name":"rate_limit_exceeded","message":"Later.","retry_after":%s}}]}'
        s = Stand(self, lambda n, seen: (207, later % batch[n - 1]["given"]))
        for k in batch:
            results = s.client.emails.send_batch([EMAIL])
            self.assertEqual(len(results), 1, k["given"])
            err = results[0].error
            assert err is not None, k["given"]
            self.assertEqual(err.code, ErrorCode.RATE_LIMITED, k["given"])
            self.assertFalse(may_have_sent(err), k["given"])
            self.assertEqual(err.retry_after, k["seconds"], f"the wait read in a retry_after of {k['given']}")
