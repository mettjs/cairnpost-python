<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mettjs/cairnpost-python/main/.github/logo-dark.svg">
    <img src="https://raw.githubusercontent.com/mettjs/cairnpost-python/main/.github/logo-light.svg" alt="CairnPost" width="330" height="72">
  </picture>
</p>

# cairnpost-python

The Python client for [CairnPost](https://github.com/mettjs/CairnPost), a
self-hostable gateway for transactional email. It sends email, reads what
became of it, manages suppressions, templates and webhook endpoints, reads
the email that comes in, and verifies the webhooks CairnPost sends.

It uses the standard library only, is fully typed, and needs Python 3.11 or
later.

**Status: early, and not released yet.** It is built for CairnPost 0.1.1 and
is not on PyPI. Until it is, install it from this repository:

```sh
pip install git+https://github.com/mettjs/cairnpost-python
```

## Send an email

```python
import os
from cairnpost import CairnPost, Email

client = CairnPost("https://mail.example.com", os.environ["CAIRNPOST_API_KEY"])

sent = client.emails.send(
    Email(
        from_="Example <hello@example.com>",
        to=["ana@example.org"],
        subject="Welcome",
        text="Glad you are here.",
        idempotency_key="welcome-user-42",
    )
)
```

`sent.id` is the email's id. `html`, `text` or both; `cc`, `bcc`, `reply_to`
and `headers` are optional. The sender is `from_`, since `from` is a word of
Python's own; `to`, `cc` and `bcc` are lists.

Files go with an email as `attachments`:

```python
from cairnpost import Attachment

Email(
    # ...
    attachments=[
        Attachment(filename="invoice.pdf", content=pdf),  # bytes
        # Shown in the HTML body as <img src="cid:logo">.
        Attachment(filename="logo.png", content=logo, content_id="logo"),
    ],
)
```

`content_type` is told from the filename when left out. The server sets how
many files an email may carry and how large they may be in all (10 files and
10 MiB by default). It keeps a file only where it is set to keep what emails
say, for as long, and while an email waits to be sent; `emails.file` reads
one back. Whether a file with a `content_id` can be sent depends on the
server's mail provider.

An email may name several addresses in `to`, `cc` and `bcc` (50 in all,
unless the server is set otherwise). It is still one email with one id. An
address on the sending domain's suppression list is left out and the email
goes to the others: `sent.suppressed` names who was left out, as
`message.suppressed` does when the email is read later. The send is an error
when nobody in `to` or `cc` is left: a `bcc` alone is not sent.

**Use an `idempotency_key` for anything you may retry.** The same key with
the same content, sent again, is the same email: the retry answers the first
one's id and sends nothing. A key is printable ASCII with no space at either
end; an empty one is refused, since it would be no key at all.

Several emails go in one request with `send_batch`:

```python
from cairnpost import failed

results = client.emails.send_batch(emails, idempotency_key="welcome-run-42")
# It raises when the batch was refused whole (one email could never be
# sent, say): nothing was sent then.
for i, r in enumerate(results):
    if r.error:
        # Email i did not go: the same CairnPostError a send would raise.
        continue
    # r.sent.id
```

An answer says the batch was taken, not that every email went: read each
result, or count with `failed(results)`. With an `idempotency_key`, the same
batch sent again (the same emails in the same order) sends only what did not
go. Each failed email's `retry_after` is its own. The server sets how many
emails a batch may hold (100 by default) and how long it may take; a server
given more than its default minute wants a client with a longer `timeout`.

An email can be asked for now and sent later:

```python
from datetime import UTC, datetime, timedelta

sent = client.emails.send(Email(..., scheduled_at=datetime.now(UTC) + timedelta(days=1)))
# sent.scheduled_at is when it goes; nothing was sent yet.

client.emails.reschedule(sent.id, datetime.now(UTC) + timedelta(days=2))
client.emails.cancel(sent.id)
```

A time given to the client must have a zone (`tzinfo`): one without is
refused before anything is sent. Every time the client answers is in UTC.

Until its time the email's `state` is `State.SCHEDULED`; from then on it is
an email like any other, under the same id. `cancel` and `reschedule` raise a
`CairnPostError` with the code `not_scheduled` once the email is being sent,
was sent or was cancelled. The server keeps what a waiting email says, and
its files, until it is sent or cancelled. An address suppressed by the time
the email goes is left out; with nobody left in `to` or `cc`, the email is
cancelled and `message.reason` says `"suppressed"`. Revoking an API key
cancels the emails it asked for that still wait. The emails of a batch may
each have a `scheduled_at`. An `idempotency_key` is remembered for a day from
the asking, not until the email goes.

## Templates

A template is an email the server keeps, written once with variables as
`{{name}}`. An admin key keeps one, and any key sends from it:

```python
from cairnpost import UseTemplate

admin.templates.create(
    name="welcome",
    subject="Welcome, {{name}}",
    html="<p>Your code is <b>{{code}}</b></p>",
    text="Your code is {{code}}",
    defaults={"name": "there"},
)

client.emails.send(
    Email(
        from_="app@example.com",
        to=["ana@example.org"],
        template=UseTemplate(name="welcome", variables={"code": "4821"}),
    )
)
```

Leave `html` and `text` out with a `template`; a `subject` given with it is
used instead of the template's. A value is written as it is in the subject
and the text and escaped in the HTML, so it is never markup there: keep
attributes in quotes (`href="{{link}}"`). A variable with no default must be
given, and a value for a variable the template does not name is refused:
both are a `CairnPostError` with status 422, and nothing is sent. The email
is filled when it is asked for, so one that waits (`scheduled_at`) keeps what
it was filled with whatever becomes of the template. A template belongs to a
sending domain or, with no `domain` and a key bound to none, serves every
domain; a send gets its own domain's template of that name first.

## When a send fails

The client never retries by itself. The error says what happened:

```python
from cairnpost import CairnPostError, ErrorCode, TransportError, may_have_sent

try:
    sent = client.emails.send(email)
    # Sent. Keep sent.id.
except (CairnPostError, TransportError) as err:
    if isinstance(err, CairnPostError) and err.code is ErrorCode.RECIPIENT_SUPPRESSED:
        # The address bounced for good, complained, or was blocked by hand
        # (everyone in to and cc, if the email named several). Nothing was
        # sent now, and nothing will be: stop sending to it, and do not
        # retry. If err.email_id is set, an earlier try under the same key
        # got no answer and may have gone: emails.get(err.email_id) says
        # what became of it.
        ...
    elif may_have_sent(err):
        # It is not known whether the email went. Try again later with the
        # same idempotency_key, and only with it. Ask this before the
        # cases below: they mean "nothing was sent" only after it.
        ...
    elif isinstance(err, CairnPostError) and err.retryable:
        # Nothing was sent. Try again, after err.retry_after if it is set.
        ...
    else:
        # The request is at fault, or the key is. Trying again will not help.
        ...
```

| Error | Meaning |
|---|---|
| `CairnPostError`, status 422 | The request is at fault and will never succeed. `recipient_suppressed` is one of them. |
| `CairnPostError`, 409 `invalid_idempotent_request` | The key was used for a different email, which was sent. |
| `CairnPostError`, 409 `concurrent_idempotent_requests`, 408 `request_incomplete`, 429, 503 | Nothing was sent. Try again, after `retry_after` (seconds) when set. The 408 is a request that did not arrive whole in time, a 503 can be a server busy with other large emails. |
| `CairnPostError`, 502 `upstream_unknown` | The mail provider did not answer. The email may have gone. |
| `CairnPostError`, any other 5xx but the 503s above, or a 408 that is not CairnPost's own | The server failed after it began, or something in between answered for it (a proxy's 502 or 408). The email may have gone. |
| `TransportError` | The server was not reached, its answer never came or was not CairnPost's, or the call ran out of time; `reason` says which, and `cause_kind` names the kind of error underneath (`ConnectionRefusedError`, say). For a send, the email may have gone. |
| `ValueError` | What was given to the client cannot be sent as it is (an `idempotency_key` a header cannot carry, a time with no zone, a lone address where a list belongs). Nothing was sent. |

`may_have_sent` is true for the fourth, fifth and sixth, and for a
`recipient_suppressed` that carries an `email_id`: nothing was sent now, but
an earlier try under the same key got no answer and may have gone. That one
is not retried: the address is suppressed. For the others, the retry that
`may_have_sent` asks for is not a promise of one email: when the mail
provider's answer was lost, the server lets a retry through after a short
wait, because an email that arrives twice is better than one that never
does.

On a `CairnPostError`, `code` is the server's name for the error (an
`ErrorCode`, which is also a `str`), `detail` its sentence for a person, and
`email_id`, when set, the email's id on the server: `emails.get` says what
became of it. `code` and `detail` are `None` when the answer was not
CairnPost's own. No error holds the email's subject or body, or the API key;
an answer that is not CairnPost's own is never quoted, and the standard
library's own error is not kept as a cause, since it can hold what the other
side answered. `retryable` is also true of a 409 `changed_meanwhile`, which
a template change can meet: read the template and try again.

The client does not follow redirects, which would turn a send into a request
with no email in it: give it the server's own address. It makes each call on
a connection of its own, and does not read the proxy settings of the
environment. An API key is sent without the spaces or newline around it, and
is not shown when a client is printed.

A call may take two and a half minutes, longer than the server takes for its
slowest answer: a batch, which may take 30 seconds to arrive, starts emails
for a minute and then waits for the mail provider on the last of them, two
minutes in all. If you set `timeout`, keep it above that (and higher still
if the server's send or batch timeout was raised): a client that gives up
first cannot know whether its emails went.

The client blocks while it calls, and may be used from several threads at
once. In `asyncio` code, call it through `asyncio.to_thread`.

## What became of an email

```python
m = client.emails.get(id)
print(
    m.state
)  # scheduled, cancelled, sending, sent, deferred, delivered, bounced, complained, failed, unknown
for r in m.recipients:
    print(r.address, r.kind, r.state)  # each address has its own outcome
for e in m.events:
    print(e.to, e.type, e.at, e.code, e.reason)
```

`m.to` and `m.state` are the first address and what became of the email
there; for an email to several, read `m.recipients`: `failed` at one address
does not say the email went to nobody.

A send key sees the emails it sent; an admin key sees any, or its sending
domain's if it is bound to one. `is_not_found(err)` says there is no such
email: the id is wrong, another key's, or older than the server keeps
records. `is_wrong_address(err)` says something else: the request reached no
route of CairnPost's, so the base URL given to the client is most likely
wrong, and no record is known to be missing. `client.health()` fails the
same way on a wrong base URL, so it is the call to check a configuration
with. (Both need the server's own error answers to arrive: a proxy that puts
its own page in place of every 404 makes a missing record read as a wrong
address.) `m.content` is what the email said, set only when the server keeps
content and the key is an admin key.

## Webhooks

CairnPost tells your application what becomes of its emails by posting to a
URL of yours. Each webhook is signed; verify it before you trust it:

```python
import os
from http.server import BaseHTTPRequestHandler
from cairnpost import BounceType, EventType, Verifier, WebhookError

verifier = Verifier(os.environ["CAIRNPOST_WEBHOOK_SECRET"])


class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1 << 20))
        try:
            event = verifier.verify(self.headers, body)  # the body exactly as it arrived
        except WebhookError:  # a TypeError is a mistake in this code, not a bad webhook
            self.send_error(401, "not a CairnPost webhook")
            return
        if event.type == EventType.BOUNCED and event.email.bounce_type == BounceType.PERMANENT:
            ...  # The address will never take mail.
        elif event.type == EventType.COMPLAINED:
            ...  # Its owner marked the email as spam.
        self.send_response(204)
        self.end_headers()
```

- `verify` takes the headers as a dict or as a web framework gives them
  (`request.headers` in Flask, Django, FastAPI and Starlette), and the body
  as bytes or as the text they are. Give it the body before anything parses
  it: a body read as JSON and written again is not the body that was signed.
  Limit how much of a body you read (1 MiB is plenty).
- It raises a `WebhookError` whose `reason` is `"signature"` for a wrong
  signature, `"unsigned"` for missing headers, and `"stale"` for a timestamp
  more than five minutes from now, which is what stops a captured webhook
  being replayed.
- `event.id` is the same on every try of a webhook. CairnPost retries one
  that was not answered with a 2xx, and may send one twice: act once per id.
- `event.email` is set for `email.delivered`, `email.delivery_delayed`,
  `email.bounced`, `email.complained` and `email.failed`, and
  `event.email.bounce_type` for `email.bounced`; a webhook of those types
  that lacks them is refused (`"payload"`). `event.email` is `None`
  for `webhook.test`, the webhook sent to try an endpoint out. A type this
  client does not know is passed on as it is, with what could be read of it.
- `event.email.to` holds the one address the event is about, also when the
  email went to several; `event.email.id` is the email's one id.
- `email.received` (`EventType.RECEIVED`) tells of an email that came for
  one of your addresses, where the server takes them. It is about no email
  you sent: `event.received` says who it is from and for, and the id to read
  it by (see "Receiving email"). An endpoint that hears about every event
  gets these too.
- `address.suppressed` (`EventType.ADDRESS_SUPPRESSED`) tells of an address
  suppressed because of a bounce or a complaint about an email the server
  has no record of. It names no email: `event.suppression` holds the sending
  domain, the address and the reason (`Reason.BOUNCE` or
  `Reason.COMPLAINT`). Treat it as you treat an `email.bounced` or an
  `email.complained` with `suppressed` set.
- Of the three bounce types only `BounceType.PERMANENT` says the address is
  at fault. `BounceType.POLICY` is a refusal over the sender (a failed
  signature, a blocklist); the address may be perfectly good.
- `event.email.suppressed` says CairnPost will now refuse to send to that
  address from that sending domain.

The signature is the Standard Webhooks scheme, which Svix also uses, so any
verifier for either works too.

## Receiving email

A server set up to take the emails that come for its domains' addresses
keeps each for a time (7 days by default) and tells your endpoint with an
`email.received` webhook. Read it with an admin key:

```python
if event.type == EventType.RECEIVED:
    got = admin.received.get(event.received.id)
    # got.content.subject, .text, .html, .attachments ...
    pdf = admin.received.file(got.id, 1)  # its first file
    raw = admin.received.raw(got.id)  # every byte, as it came
```

A stranger wrote it: treat every part as untrusted, and never show its HTML
as a page. `got.from_` is what the sending server said and
`got.content.from_` what the email says of itself; either can be made up.
`content.partial` says some of it could not be read as it was written (a
charset the server does not know); `received.raw` always has all of it.
`received.list` and `received.all` list what is kept, and `received.delete`
deletes one before its time. `is_not_found` says an email's time is up.

## With an admin key

```python
from cairnpost import DeliveryState, Reason

# Webhook endpoints. The secret is said only here: keep it.
w = admin.webhooks.create(
    "https://app.example.com/webhooks/cairnpost",
    events=[EventType.BOUNCED, EventType.COMPLAINED],
)
print(w.secret)

res = admin.webhooks.test(w.id)  # sends a webhook.test now

# A new signing secret, said only here. Until w.previous_secret_until the
# server signs with the old one too: change the application's secret
# within that time. If it is None, the old one has stopped already.
w = admin.webhooks.rotate_secret(w.id)

admin.webhooks.update(w.id, enabled=False)

for d in admin.webhooks.all_deliveries(w.id, DeliveryState.FAILED):
    admin.webhooks.retry_delivery(w.id, d.id)

# The suppression list.
for s in admin.suppressions.all("example.com"):
    print(s.address, s.reason)
admin.suppressions.add("example.com", "ana@example.org", "asked to stop")
admin.suppressions.lift("example.com", "ana@example.org")
admin.suppressions.lift_all("example.com", Reason.BOUNCE)
```

| Calls | Do |
|---|---|
| `webhooks.create`, `list`, `get`, `update`, `delete` | Manage the URLs told what becomes of emails. |
| `webhooks.test` | Send an endpoint a signed `webhook.test` and say how it answered. |
| `webhooks.rotate_secret` | Give an endpoint a new signing secret; the old one still signs for a day, unless the server is set otherwise. |
| `webhooks.resume` | End an endpoint's pause, and have what it is owed sent. |
| `webhooks.deliveries`, `all_deliveries`, `retry_delivery` | What an endpoint was sent and how each went; try one again now. |
| `suppressions.list`, `all` | The addresses not sent to, a page at a time or all of them. |
| `suppressions.add`, `lift`, `lift_all` | Block an address for a sending domain, or let it be sent to again. |
| `received.get`, `list`, `all`, `raw`, `file`, `delete` | The emails that came for your addresses, while the server keeps them. |
| `templates.create`, `list`, `get`, `update`, `delete` | Manage the templates emails are sent from. `name_taken` for a name its domain has. |
| `emails.file` | What one of an email's files held, where the server keeps it (`kept` says so). |
| `captured` | The emails a development server (capture driver) kept instead of sending; a `NotCapturingError` from a server that delivers for real. |

In a change (`webhooks.update`, `templates.update`) what is left out is left
as it is, and what is given is changed to exactly that: `enabled=False`
disables the endpoint, `events=[]` makes it hear about every type.

The `all` calls walk a whole list a page at a time, and raise the first
error they meet. A page of `list` or `deliveries` holds `data` and, when
more follow, `next`: pass it back as `after`.

An endpoint that fails every try for days is paused by the server:
`w.paused_at` is set, nothing is sent to it, and it is still owed everything
that happens. `admin.webhooks.resume(w.id)` resumes it, and what it is owed
is sent then; an `update` never does. `w.failing_since` says since when
every try has failed.

## The server itself

```python
h = client.health()  # needs no key
print(h.ok, h.events, h.webhooks, h.pruning)

l = client.limits()  # l.quota is None for a provider with no allowance
```

## Options

Keyword arguments of `CairnPost(base_url, api_key, ...)`:

| Option | Does |
|---|---|
| `timeout` | How long a call may take, in seconds (150 by default). Keep it above the server's send and batch timeouts. |
| `max_answer_bytes` | How much of an answer is read (64 MiB by default). A larger one is an error that says so. |
| `user_agent` | Put your application's name before the client's in `User-Agent`. |
| `tls` | An `ssl.SSLContext`, to trust a server by other certificates than the system's. |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
