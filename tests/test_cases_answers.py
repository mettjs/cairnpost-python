from __future__ import annotations

import unittest

from cairnpost import CairnPostError, TransportError

from .asking import ask, calls_of
from .cases import cases, listed, saying


class AnAnswer(unittest.TestCase):
    # Something else at the address, or between, can answer 200 to
    # anything, and an answer can be of CairnPost's kind and still not be
    # the answer to what was asked. None of it may read as "done", "no" or
    # "none"; and what CairnPost does say is taken.
    def test_it_is_taken_only_when_it_is_cairnposts(self) -> None:
        file = cases("answers.json", ["refused", "taken"])
        wrong: list[str] = []
        for want in ["refused", "taken"]:
            for c in listed(file, want, ["name", "calls", "answer"]):
                # One server for the case, closed before the next is started.
                client = saying(self, c["answer"]).client
                for name in calls_of(c["name"], c["calls"]):
                    got = "taken"
                    try:
                        ask(name)(client)
                    except TransportError as err:
                        got = "refused" if err.reason == "not_cairnpost" else repr(err)
                    except CairnPostError as err:
                        got = repr(err)
                    if got != want:
                        wrong.append(f"{name}, answered {c['name']}: {got}, not {want}")
                self.doCleanups()
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
