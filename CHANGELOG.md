# Changelog

Every change a user of this client can notice is written here. The format is
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/mettjs/cairnpost-python/commits/main
