"""What is dropped around a value before it is read."""

from __future__ import annotations

#: What is dropped around an API key, a signing secret and the value of a
#: signature header: what a file or a header puts there, and no more. A
#: bare `strip()` drops more (a no-break space, the separators below the
#: space), other languages drop other things, and one value must read the
#: same in every client.
AROUND = " \t\r\n"


def bare(value: str) -> str:
    """A value without the space, tabs and line breaks around it."""
    return value.strip(AROUND)
