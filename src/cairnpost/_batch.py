from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ._codes import known
from ._email import Sent, read_sent
from ._errors import CairnPostError
from ._problem import problem_from
from ._read import Misshapen, fields, has, items
from ._wait import believed


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchResult:
    """What became of one email of a batch: `sent`, or `error`.

    `error` is the `CairnPostError` a send of this email alone would have
    raised: `retryable` and `may_have_sent` read it the same way.
    """

    sent: Sent | None = None
    error: CairnPostError | None = None


def failed(results: Sequence[BatchResult]) -> int:
    """Counts the emails of a batch that did not go."""
    return sum(1 for r in results if r.error is not None)


def read_batch(v: object, later: Sequence[bool]) -> list[BatchResult]:
    """Reads a batch's answer.

    One that does not answer for each email asked is not CairnPost's:
    which emails went is not known.
    """
    results = items(has(fields(v), "data"), "data", fields)
    if len(results) != len(later):
        raise Misshapen
    return [_one(o, waits) for o, waits in zip(results, later, strict=True)]


def _one(o: dict[str, object], later: bool) -> BatchResult:
    if o.get("error") is None:
        return BatchResult(sent=read_sent(o, later))
    e = fields(o["error"])
    status = e.get("statusCode")
    if isinstance(status, bool) or not isinstance(status, int) or not 400 <= status <= 599:
        raise Misshapen
    # Under a name this client does not know, only the status is believed,
    # as for an answer that is not CairnPost's.
    seconds = believed(e.get("retry_after")) if known(e.get("name")) is not None else None
    return BatchResult(error=problem_from(status, e, seconds))
