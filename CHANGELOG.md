# Changelog

Every change a user of this client can notice is written here. The format is
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `Verifier` drops only a space, a tab or a line break around a signing
  secret, and so do the Go and Node.js clients now. Each dropped what
  its own language calls blank space, and the three sets differ: a
  secret with one of the separators U+001C to U+001F around it was taken
  here and refused by the other two. A secret with any other character
  around it, a no-break space or a form feed among them, is now refused
  with a `WebhookError` whose `reason` is `"secret"`.
- One value is now read the same way by this client and by the Go and
  Node.js ones. Around an API key, and around the id, the timestamp and
  the signatures of a webhook, a space, a tab or a line break is dropped
  and nothing else is.
  - `CairnPost` refuses a key with any other character around it. It
    dropped other blank characters (a no-break space, a form feed, the
    separators below the space) and took what was left.
  - `verify` no longer drops those characters around a webhook's id,
    timestamp or signature, nor takes them for the gap between two
    signatures. Such a webhook is refused, as the other clients refuse
    it. A webhook as CairnPost sends it has none of them.
- `verify` refuses a webhook whose id holds half a character (a lone
  surrogate) with a `WebhookError`, as it does any forged one. It raised
  `UnicodeEncodeError`.
- When `CairnPost` or `Verifier` refuses what it was given (a key, a
  secret, a base URL, a timeout), the error no longer passes through a
  frame of this client that holds the key or the secret. An error
  reporter that records the values of every frame recorded it. A client
  that was refused can also be shown by one: its `repr` raised an error
  of its own, which on Python 3.11 took the place of the refusal.
- A `timeout` too large to be a number of seconds at all (`10**400`) is
  a `ValueError`, as any other bad timeout is. It raised `OverflowError`.

## [0.1.0] - 2026-11-17

### Added

- The client, for CairnPost 0.1.1: `CairnPost(base_url, api_key)`, on the
  standard library alone, typed, for Python 3.11 and later.
- `emails.send` and `emails.get`: send an `Email` to one address or several
  (`to`, `cc`, `bcc`), with files (`attachments`), from a template
  (`template`) or at a later time (`scheduled_at`), and read what became of
  it at each address. An `idempotency_key` makes a repeated send one email.
- `emails.send_batch`: several emails in one request, each with its own
  result; `failed` counts those that did not go.
- `emails.cancel` and `emails.reschedule` for an email that waits, and
  `emails.file` to read back a file the server keeps.
- `CairnPostError`, with the server's `code` and `detail`, `retryable` and
  `retry_after`; `TransportError` for a call that got no answer;
  `may_have_sent`, `is_not_found` and `is_wrong_address` to ask what an
  error means. The client never retries by itself and follows no redirect.
- `Verifier`: checks a webhook's signature and timestamp and reads it,
  every type the server sends.
- With an admin key: `suppressions`, `webhooks` (with deliveries, a test,
  secret rotation and resume), `templates`, `received` (the emails that
  come in) and `captured`.
- `health` and `limits`.

[Unreleased]: https://github.com/mettjs/cairnpost-python/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mettjs/cairnpost-python/releases/tag/v0.1.0
