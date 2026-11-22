"""How long an answer asks to wait before the call is tried again."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime

from ._bare import bare

#: The longest wait an answer is believed to ask for, in seconds: about 31
#: years. No server means more, and it is the most the Retry-After header
#: can say in the nine digits read of it.
LONGEST_WAIT = 999_999_999

_SECONDS = re.compile(r"[0-9]{1,9}", re.ASCII)
_A_SECOND = timedelta(seconds=1)


def wait_of(retry_after: str | None, now: datetime | None = None) -> float | None:
    """How long a Retry-After header asks to wait, in seconds; None when it does not say.

    It is a wait in two forms only: 1 to 9 digits, which are seconds and
    what CairnPost writes, and a date exactly as HTTP writes one now
    ("Sun, 06 Nov 1994 08:49:37 GMT"), which a proxy may write and is the
    time to wait until. A sign, a fraction, an older form of a date or a
    date that never comes is no wait: the Go and Node clients read the
    same.
    """
    after = bare(retry_after or "")
    if _SECONDS.fullmatch(after):
        return believed(int(after))
    # The parser alone takes much else: a date is one when the time it
    # names is written back the same.
    try:
        at = parsedate_to_datetime(after)
        if at.tzinfo is None or format_datetime(at.astimezone(UTC), usegmt=True) != after:
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    # A part of a second is a whole one: a caller never comes back early.
    return believed(-(((now or datetime.now(UTC)) - at) // _A_SECOND))


def believed(seconds: object) -> float | None:
    """A wait said in seconds, when it is one.

    That is a whole number from 1 to the longest, however it was written
    (30, 30.0, 3e1). Anything else is no wait.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        return None
    return float(seconds) if 1 <= seconds <= LONGEST_WAIT and seconds == int(seconds) else None
