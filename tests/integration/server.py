"""What the live tests share.

They run against a real CairnPost server: one started with the capture
driver, CAIRNPOST_WEBHOOK_ALLOW_PRIVATE=on, a CAIRNPOST_CONTENT_RETENTION
and a CAIRNPOST_INBOUND_SECRET, so that nothing is sent to anybody, a
webhook can reach this machine, and content and received mail can be read
back. They need its address, two keys and that secret, and fail without
them rather than skip.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import TypeVar

from cairnpost import CairnPost, CairnPostError

T = TypeVar("T")


def need(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            "set CAIRNPOST_URL, CAIRNPOST_SEND_KEY, CAIRNPOST_ADMIN_KEY and CAIRNPOST_INBOUND_SECRET "
            "to a server running the capture driver"
        )
    return value


URL = need("CAIRNPOST_URL").rstrip("/")
INBOUND_SECRET = need("CAIRNPOST_INBOUND_SECRET")
send = CairnPost(URL, need("CAIRNPOST_SEND_KEY"))
admin = CairnPost(URL, need("CAIRNPOST_ADMIN_KEY"))

#: A name no other run has.
RUN = f"run-{time.time_ns()}-{os.getpid()}"
FROM = f"App <app@{RUN}.example.com>"


def code(run: Callable[[], object]) -> str | None:
    """The error's code; "no error" when there was none."""
    try:
        run()
    except CairnPostError as err:
        return err.code
    return "no error"


def until(what: str, look: Callable[[], T | None]) -> T:
    for _ in range(100):
        found = look()
        if found is not None:
            return found
        time.sleep(0.1)
    raise AssertionError(f"waited ten seconds for {what}")
