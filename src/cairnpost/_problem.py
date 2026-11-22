from __future__ import annotations

from ._codes import known
from ._errors import CairnPostError
from ._parse import parse
from ._wait import wait_of


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
