from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from ._codes import known
from ._errors import CairnPostError
from ._parse import parse

_SECONDS = re.compile(r"[0-9]{1,9}", re.ASCII)
# Only the form HTTP writes a date in.
_HTTP_DATE = re.compile(r"[A-Za-z]{3}, \d{2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2} GMT", re.ASCII)


def problem_of(status: int, raw: bytes, retry_after: str | None) -> CairnPostError:
    """Reads an error answer."""
    _, body = parse(raw)
    return problem_from(status, body, wait_of(retry_after))


def problem_from(status: int, body: object, retry_after: float | None) -> CairnPostError:
    """A problem from an error as CairnPost writes one, wherever it was said.

    Only CairnPost's own fields are kept, and only under a name of
    CairnPost's: anything else at that address could say back what it was
    sent.
    """
    code = known(body.get("name")) if isinstance(body, dict) else None
    if code is None or not isinstance(body, dict):
        return CairnPostError(status, retry_after=retry_after)

    def said(key: str) -> str | None:
        value = body.get(key)
        return value if isinstance(value, str) else None

    return CairnPostError(status, code, said("message"), said("id"), retry_after)


def wait_of(retry_after: str | None) -> float | None:
    """How long an answer asks to wait, in seconds; None when it does not say.

    Retry-After is seconds from CairnPost, and may be a date from a proxy.
    """
    after = (retry_after or "").strip()
    if _SECONDS.fullmatch(after):
        return float(after) if int(after) > 0 else None
    if not _HTTP_DATE.fullmatch(after):
        return None
    try:
        at = parsedate_to_datetime(after)
    except (ValueError, TypeError):
        return None
    seconds = round((at.astimezone(UTC) - datetime.now(UTC)).total_seconds())
    return float(seconds) if seconds > 0 else None
