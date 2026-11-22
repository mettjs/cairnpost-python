from __future__ import annotations

import unittest

from cairnpost import CairnPostError, is_not_found, is_wrong_address, may_have_sent

from .asking import ask
from .cases import cases, listed, only, saying


class AnError(unittest.TestCase):
    # An error says what to do: whether to try again, whether the email
    # may have gone, whether a record is missing or the address is wrong.
    # Only under a name of CairnPost's is anything but the status
    # believed: what any other answer says is not repeated.
    def test_it_says_what_to_do(self) -> None:
        file = cases("errors.json", ["cases"])
        for c in listed(file, "cases", ["name", "call", "answer", "want"]):
            with self.assertRaises(CairnPostError, msg=c["name"]) as raised:
                ask(c["call"])(saying(self, c["answer"]).client)
            err = raised.exception
            got = {
                "status": err.status,
                "code": None if err.code is None else err.code.value,
                "detail": err.detail,
                "email_id": err.email_id,
                "retry_after": err.retry_after,
                "retryable": err.retryable,
                "may_have_sent": may_have_sent(err),
                "not_found": is_not_found(err),
                "wrong_address": is_wrong_address(err),
            }
            only(f"what {c['name']} wants", c["want"], list(got))
            self.assertEqual(got, c["want"], c["name"])
            answer = c["answer"].get("json")
            message = answer.get("message") if isinstance(answer, dict) else None
            if got["code"] is None and isinstance(message, str) and message:
                self.assertNotIn(
                    message, f"{err}{err!r}{vars(err)}", f"{c['name']}: the error repeats the answer"
                )
            self.doCleanups()


if __name__ == "__main__":
    unittest.main()
