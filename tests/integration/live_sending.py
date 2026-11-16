from __future__ import annotations

import contextlib
import unittest
from datetime import UTC, datetime, timedelta

from cairnpost import (
    Attachment,
    CairnPost,
    CairnPostError,
    Email,
    ErrorCode,
    Limits,
    State,
    TransportError,
    UseTemplate,
    failed,
    is_not_found,
    may_have_sent,
)

from .server import FROM, RUN, URL, admin, code, send


class AgainstARealServer(unittest.TestCase):
    def test_sending(self) -> None:
        h = send.health()
        self.assertEqual(
            (h.ok, h.driver), (True, "capture"), "the server must be up and on the capture driver"
        )
        self.assertEqual(send.limits(), Limits(driver="capture", quota=None))
        email = Email(
            from_=FROM,
            to=["ana@example.org"],
            subject=f"Hello {RUN}",
            text="Body",
            html="<p>Body & more</p>",
            reply_to="help@example.com",
            headers={"X-Run": RUN},
            idempotency_key=RUN,
        )
        first = send.emails.send(email)
        # The same request again is the same email; another under its key is refused.
        self.assertEqual(send.emails.send(email).id, first.id)
        other = Email(from_=FROM, to=["ana@example.org"], subject="Another", text="Body", idempotency_key=RUN)
        self.assertEqual(code(lambda: send.emails.send(other)), ErrorCode.IDEMPOTENT_MISMATCH)
        m = send.emails.get(first.id)
        self.assertEqual(
            (m.id, m.state, m.from_, m.to, len(m.recipients), m.events),
            (first.id, State.SENT, f"app@{RUN}.example.com", "ana@example.org", 1, []),
        )
        self.assertLess(
            abs(m.created_at - datetime.now(UTC)), timedelta(minutes=1), "the time it was made is now"
        )
        # A send key is not shown what an email said; an admin key is.
        self.assertIsNone(m.content)
        whole = admin.emails.get(first.id).content
        assert whole is not None
        self.assertEqual(
            (whole.subject, whole.from_name, whole.html, whole.headers["X-Run"]),
            (email.subject, "App", email.html, RUN),
        )
        self.assertGreater(whole.kept_until, datetime.now(UTC))

        held = admin.captured()
        self.assertTrue(
            any(
                c.subject == email.subject
                and c.from_name == "App"
                and c.html == email.html
                and c.headers["X-Run"] == RUN
                and c.reply_to == "help@example.com"
                for c in held
            ),
            "the email is among the captured",
        )
        self.assertEqual(code(send.captured), ErrorCode.ADMIN_KEY_REQUIRED)
        self.assertEqual(
            code(lambda: CairnPost(URL, "cp_00000000_not-a-key").emails.get(first.id)), ErrorCode.INVALID_KEY
        )
        with self.assertRaises(CairnPostError) as missing:
            send.emails.get("0199-none")
        self.assertTrue(is_not_found(missing.exception))

    def test_several_addresses_a_batch_and_an_email_asked_for_later(self) -> None:
        several = send.emails.send(
            Email(
                from_=FROM,
                to=["ana@example.org", "ben@example.org"],
                cc=["cy@example.org"],
                bcc=["dee@example.org"],
                subject=f"Several {RUN}",
                text="Body",
            )
        )
        m = send.emails.get(several.id)
        self.assertEqual(
            [f"{r.kind}:{r.address}:{r.state}" for r in m.recipients],
            [
                "to:ana@example.org:sent",
                "to:ben@example.org:sent",
                "cc:cy@example.org:sent",
                "bcc:dee@example.org:sent",
            ],
        )
        # A batch: each email has its own id, and the batch again is the same.
        batch = [
            Email(from_=FROM, to=["ben@example.org"], subject=f"One {RUN}", text="Body"),
            Email(from_=FROM, to=["cy@example.org"], subject=f"Two {RUN}", text="Body"),
        ]
        sent = send.emails.send_batch(batch, idempotency_key=f"{RUN}-batch")
        ids = [r.sent.id if r.sent else None for r in sent]
        self.assertEqual((len(sent), failed(sent), len(set(ids))), (2, 0, 2))
        again = send.emails.send_batch(batch, idempotency_key=f"{RUN}-batch")
        self.assertEqual([r.sent.id if r.sent else None for r in again], ids)
        with self.assertRaises(CairnPostError) as broken:
            send.emails.send_batch(
                [batch[0], Email(from_=FROM, to=[], subject="s", text="t")], idempotency_key=f"{RUN}-batch"
            )
        self.assertEqual(
            (broken.exception.code, may_have_sent(broken.exception)), (ErrorCode.VALIDATION, False)
        )
        # An email asked for later waits, is moved and is cancelled.
        when = datetime.now().astimezone() + timedelta(hours=1)
        waits = send.emails.send(
            Email(from_=FROM, to=["dee@example.org"], subject=f"Later {RUN}", text="Body", scheduled_at=when)
        )
        assert waits.scheduled_at is not None
        self.assertLess(abs(waits.scheduled_at - when), timedelta(seconds=1))
        # Whatever fails below, it is not left waiting on the server.
        self.addCleanup(lambda: code(lambda: send.emails.cancel(waits.id)))
        waiting = send.emails.get(waits.id)
        self.assertEqual((waiting.state, waiting.scheduled_at is not None), (State.SCHEDULED, True))
        send.emails.reschedule(waits.id, datetime.now(UTC) + timedelta(hours=2))
        send.emails.cancel(waits.id)
        self.assertEqual(code(lambda: send.emails.cancel(waits.id)), ErrorCode.NOT_SCHEDULED)
        self.assertEqual(send.emails.get(waits.id).state, State.CANCELLED)
        past = Email(
            from_=FROM,
            to=["dee@example.org"],
            subject="s",
            text="t",
            scheduled_at=datetime.now(UTC) - timedelta(hours=1),
        )
        self.assertEqual(code(lambda: send.emails.send(past)), ErrorCode.VALIDATION)

    def test_files_templates_and_suppressions(self) -> None:
        # Whatever fails below, nothing of this run is left on the server.
        def tidy() -> None:
            with contextlib.suppress(CairnPostError, TransportError):
                admin.suppressions.lift_all(f"{RUN}.example.com")
                for t in admin.templates.list().data:
                    if t.name == f"welcome-{RUN}":
                        admin.templates.delete(t.id)

        self.addCleanup(tidy)
        raw = bytes([0, 1, 2, 255, 254, 10, 13])
        filed = send.emails.send(
            Email(
                from_=FROM,
                to=["ana@example.org"],
                subject=f"Filed {RUN}",
                html='<img src="cid:dot">',
                attachments=[
                    Attachment(filename="data.bin", content=raw),
                    Attachment(filename="dot.png", content=b"png", content_id="dot"),
                ],
            )
        )
        content = admin.emails.get(filed.id).content
        assert content is not None
        self.assertEqual(
            [(f.filename, f.content_type, f.content_id, f.size, f.kept) for f in content.attachments],
            [
                ("data.bin", "application/octet-stream", None, 7, True),
                ("dot.png", "image/png", "dot", 3, True),
            ],
        )
        self.assertEqual(admin.emails.file(filed.id, 1), raw)
        self.assertEqual(code(lambda: send.emails.file(filed.id, 1)), ErrorCode.ADMIN_KEY_REQUIRED)
        self.assertEqual(code(lambda: admin.emails.file(filed.id, 3)), ErrorCode.NOT_FOUND)

        name = f"welcome-{RUN}"
        made = admin.templates.create(
            name=name,
            subject="Code for {{name}} " + RUN,
            html="<b>{{code}}</b>",
            text="{{code}}",
            defaults={"name": "you"},
        )
        self.assertEqual(
            sorted((v.name, v.default, v.required) for v in made.variables),
            [("code", None, True), ("name", "you", False)],
        )
        self.assertEqual(
            code(lambda: admin.templates.create(name=name, subject="s", text="t")), ErrorCode.NAME_TAKEN
        )
        send.emails.send(
            Email(
                from_=FROM, to=["ana@example.org"], template=UseTemplate(name=name, variables={"code": "<1>"})
            )
        )
        filled = next(c for c in admin.captured() if c.subject == f"Code for you {RUN}")
        self.assertEqual((filled.html, filled.text), ("<b>&lt;1&gt;</b>", "<1>"))
        self.assertEqual(
            code(
                lambda: send.emails.send(
                    Email(from_=FROM, to=["ana@example.org"], template=UseTemplate(name=name))
                )
            ),
            ErrorCode.VALIDATION,
        )
        changed = admin.templates.update(made.id, subject="Changed " + RUN, defaults={})
        self.assertEqual(
            (changed.subject, changed.html, all(v.required for v in changed.variables)),
            ("Changed " + RUN, "<b>{{code}}</b>", True),
        )
        self.assertTrue(any(t.id == made.id and t.html is None for t in admin.templates.list().data))
        admin.templates.delete(made.id)
        self.assertEqual(code(lambda: admin.templates.get(made.id)), ErrorCode.NOT_FOUND)

        domain = f"{RUN}.example.com"
        self.assertIs(admin.suppressions.add(domain, "Gone@Example.org", "asked"), True)
        self.assertIs(admin.suppressions.add(domain, "gone@example.org"), False)
        admin.suppressions.add(domain, "also@example.org")
        self.assertEqual(
            [f"{s.address}:{s.reason}:{s.note or ''}" for s in admin.suppressions.all(domain)],
            ["also@example.org:manual:", "gone@example.org:manual:asked"],
        )
        page = admin.suppressions.list(domain=domain, limit=1)
        self.assertEqual((len(page.data), isinstance(page.next, str)), (1, True))
        # An email to a suppressed address and another goes to the other, and says so.
        part = send.emails.send(
            Email(from_=FROM, to=["gone@example.org", "ana@example.org"], subject=f"Part {RUN}", text="Body")
        )
        self.assertEqual(part.suppressed, ["gone@example.org"])
        self.assertEqual(send.emails.get(part.id).suppressed, ["gone@example.org"])
        with self.assertRaises(CairnPostError) as none:
            send.emails.send(
                Email(from_=FROM, to=["gone@example.org"], subject="SUBJECTMARKQ", text="TEXTMARKQ")
            )
        err = none.exception
        self.assertEqual(
            (err.code, err.retryable, may_have_sent(err)), (ErrorCode.RECIPIENT_SUPPRESSED, False, False)
        )
        self.assertNotRegex(repr(err) + str(err) + repr(vars(err)), "SUBJECTMARKQ|TEXTMARKQ")
        admin.suppressions.lift(domain, "gone@example.org")
        self.assertEqual(
            code(lambda: admin.suppressions.lift(domain, "gone@example.org")), ErrorCode.NOT_FOUND
        )
        self.assertEqual(admin.suppressions.lift_all(domain), 1)


if __name__ == "__main__":
    unittest.main()
