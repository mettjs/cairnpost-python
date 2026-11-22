from __future__ import annotations

import traceback
import unittest
from pathlib import Path

import cairnpost
from cairnpost import CairnPost

from .asking import ask
from .cases import cases, listed, saying

#: Where the client's own code is: its frames are the ones looked at.
OURS = str(Path(cairnpost.__file__).parent)


class AKey(unittest.TestCase):
    # A key is taken when it could be one: what a server gives, with at
    # most a space, a tab or a line break around it, and it is sent
    # without them. Any other is refused when the client is made, before
    # a call, by an error that does not repeat it.
    def test_it_is_taken_only_when_it_could_be_one(self) -> None:
        file = cases("keys.json", ["taken", "refused"])
        described = listed(
            cases("calls.json", ["calls"]), "calls", ["name", "route", "key", "sends", "answer"]
        )
        # Any call that needs a key shows what is sent for one.
        call = next(c for c in described if c["key"] != "none")
        for k in listed(file, "taken", ["given", "sends"]):
            given = k["given"]
            s = saying(self, call["answer"])
            try:
                client = CairnPost(s.url, given)
            except ValueError:
                self.fail(f"{given!r} was refused as a key")
            ask(call["name"])(client)
            self.assertEqual(len(s.seen), 1, f"{call['name']} with the key {given!r}")
            self.assertEqual(s.seen[0].auth, "Bearer " + k["sends"], f"what {given!r} was sent as")
            # Each case had a server of its own: closed now, not at the end.
            self.doCleanups()
        refused = file["refused"]
        self.assertTrue(isinstance(refused, list) and refused, "the file holds no key to refuse")
        for key in refused:
            # Caught by hand: assertRaises drops the frames, which are looked at.
            try:
                CairnPost("https://mail.example.com", key)
            except ValueError as err:
                # With the values of the client's own frames, as an error
                # reporter may show them. (Not this test's, which holds the key.)
                frames = traceback.TracebackException.from_exception(err, capture_locals=True).stack
                ours = [f for f in frames if f.filename.startswith(OURS)]
                shown = str(err) + repr(err) + "".join(str(f.locals) for f in ours)
            else:
                self.fail(f"{key!r} was taken as a key")
            self.assertTrue(ours, "the refusal passed through no frame of the client's")
            for i in range(len(key) - 7):
                self.assertNotIn(key[i : i + 8], shown, f"the refusal of {key!r} repeats part of it")
