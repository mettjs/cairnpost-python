# Contributing to cairnpost-python

This is the Python client for [CairnPost](https://github.com/mettjs/CairnPost),
a small gateway for transactional email. It does what the server's API
does, typed, and verifies the webhooks the server sends. It is small on
purpose.

## What it is not

- It does not retry by itself. It says what happened and whether trying
  again is right; the application decides.
- It has no dependencies at run time, and takes none: the standard library
  only. It is built with hatchling and checked with ruff and mypy.
- It never puts an email's subject or body, or the API key, in an error.

## Setup and tests

It needs Python 3.11 or later, and [uv](https://docs.astral.sh/uv/) to run
the tools at the versions `pyproject.toml` names.

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run python -m unittest discover -s tests -t .
```

The integration tests run against a real CairnPost server. Start one with
the capture driver, so nothing is sent to anybody, and with
`CAIRNPOST_WEBHOOK_ALLOW_PRIVATE=on`, a `CAIRNPOST_CONTENT_RETENTION` and a
`CAIRNPOST_INBOUND_SECRET`, so that its webhooks can reach your machine and
what it keeps can be read back; make a send key and an admin key; then:

```sh
export CAIRNPOST_URL=http://localhost:8025
export CAIRNPOST_SEND_KEY=...
export CAIRNPOST_ADMIN_KEY=...
export CAIRNPOST_INBOUND_SECRET=...   # the server's own
uv run python -m unittest discover -s tests/integration -t . -p 'live_*.py'
```

Without those variables they fail rather than skip. CI runs all of the
above, the integration tests against the server's published image.

## Conventions

- **One file per part of the API**, small, with its tests in `tests/`.
- **The standard library only** at run time.
- **Everything is typed**, and `mypy --strict` passes.
- **An answer is read field by field** (`src/cairnpost/_read.py`), never
  trusted to have its shape.
- **Errors say what to do**, and never echo the server's raw answer.
- **Documentation is true now.** A change to what the client does updates
  the README and the changelog with it.
- **Commits** follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/),
  one concern each, and say why. Versions follow
  [Semantic Versioning](https://semver.org/spec/v2.0.0.html), and the
  changelog follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
