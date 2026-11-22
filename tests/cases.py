"""The cases every CairnPost client is held to, whatever language it is written in.

The files in tests/cases say what each call sends, the answers a client
must take and those it must refuse, what an error says to do, and which
webhooks are the endpoint's. They are a copy of the server's own
(client-cases in its repository) and are changed there, never here. The
tests in test_cases_*.py run them.
"""

from __future__ import annotations

import json
import re
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

from .stand import Seen, Stand

_A_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)")


def only(where: str, value: Any, known: list[str]) -> None:
    """Says a case holds no field but those named.

    A field this runner does not know fails the read: a case must never
    pass because part of it was not looked at.
    """
    if not isinstance(value, dict):
        raise AssertionError(f"{where} is not an object")
    strange = [name for name in value if name not in known]
    if strange:
        raise AssertionError(f"{where} has a field this runner does not know: {strange}")


def cases(name: str, known: list[str]) -> dict[str, Any]:
    """Reads one of the shared files."""
    file: dict[str, Any] = json.loads((Path(__file__).parent / "cases" / name).read_text("utf-8"))
    only(name, file, known)
    return file


def listed(file: dict[str, Any], name: str, known: list[str]) -> list[dict[str, Any]]:
    """The cases under one name of a file: a list that is not empty, each with only the fields named."""
    found = file.get(name)
    if not isinstance(found, list) or not found:
        raise AssertionError(f"the file holds no {name}")
    for case in found:
        only(str(case.get("name")) if isinstance(case, dict) else name, case, known)
    return found


def saying(case: unittest.TestCase, a: dict[str, Any]) -> Stand:
    """Starts a server that gives one answer to every request, and a client of it."""
    only("an answer", a, ["status", "json", "text", "headers"])
    if ("json" in a) == ("text" in a):
        raise AssertionError(f"an answer has a json or a text, and not both: {a}")
    body: str = json.dumps(a["json"]) if "json" in a else a["text"]
    headers = {**({"Content-Type": "application/json"} if "json" in a else {}), **a.get("headers", {})}

    def answer(n: int, seen: Seen) -> tuple[int, str, dict[str, str]]:
        return a["status"], body, headers

    return Stand(case, answer)


def instants(v: Any) -> Any:
    """Puts every time in a JSON value into one form: a time is the instant it names, however it is written."""
    if isinstance(v, str):
        return ("instant", datetime.fromisoformat(v).timestamp()) if _A_TIME.fullmatch(v) else v
    if isinstance(v, list):
        return [instants(x) for x in v]
    if isinstance(v, dict):
        return {k: instants(x) for k, x in v.items()}
    return v
