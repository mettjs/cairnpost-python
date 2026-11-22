from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta, timezone, tzinfo

from cairnpost import (
    Attachment,
    CairnPostError,
    Email,
    ErrorCode,
    FileInfo,
    Sent,
    State,
    TransportError,
    UseTemplate,
    failed,
    is_not_found,
    may_have_sent,
)

from .stand import EMAIL, Stand, serve

RECORD = """{"id":"msg 1","from":"a@example.com","to":"b@example.org","state":"bounced",
  "recipients":[{"address":"b@example.org","kind":"to","state":"bounced","updated_at":"2030-01-01T00:00:02.123456789Z"},
                {"address":"c@example.org","kind":"cc","state":"delivered","updated_at":"2030-01-01T02:00:03+02:00"}],
  "suppressed":["d@example.org"],"created_at":"2030-01-01T00:00:00Z","updated_at":"2030-01-01T00:00:03Z",
  "events":[{"type":"bounced","at":"2030-01-01T00:00:02Z","to":"b@example.org","permanent":true,"code":"5.1.1","reason":"permanent_failure","detail":"No such user"}],
  "content":{"subject":"s","text":"t","headers":{"X-Run":"7"},"kept_until":"2030-01-02T00:00:00Z",
    "attachments":[{"filename":"a.txt","content_type":"text/plain","size":2,"kept":true},{"filename":"b.png","content_type":"image/png","content_id":"b","size":3}]}}"""


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


class SetBack(tzinfo):
    """A zone in the hour its clock is set back: which offset holds depends on `fold`."""

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=-5 if dt is not None and dt.fold else -4)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "set back"


class Sending(unittest.TestCase):
    def test_a_send_says_only_what_the_server_names(self) -> None:
        s = serve(self, 200, '{"id":"msg-1"}')
        sent = s.client.emails.send(
            Email(
                from_="a@example.com",
                to=("b@example.org",),
                subject="s",
                text="t",
                cc=[],
                headers={},
                html="",
                idempotency_key="welcome 42",
            )
        )
        self.assertEqual(sent, Sent(id="msg-1", suppressed=[]))
        got = s.seen[0]
        self.assertEqual(
            (got.method, got.path, got.idem, got.content_type),
            ("POST", "/emails", "welcome 42", "application/json"),
        )
        self.assertEqual(got.body, '{"from":"a@example.com","to":["b@example.org"],"subject":"s","text":"t"}')
        # Everything an email can say, under the server's names.
        s.client.emails.send(
            Email(
                from_="App <a@example.com>",
                to=["b@example.org", "c@example.org"],
                cc=["d@example.org"],
                bcc=["e@example.org"],
                reply_to="help@example.com",
                subject="sé",
                html="<p>h & more</p>",
                headers={"X-Run": "7"},
                attachments=[
                    Attachment(filename="a.txt", content=b"hi"),
                    Attachment(
                        filename="logo.png",
                        content=bytearray(b"ng"),
                        content_type="image/png",
                        content_id="logo",
                    ),
                ],
            )
        )
        self.assertEqual(
            json.loads(s.seen[1].body),
            {
                "from": "App <a@example.com>",
                "to": ["b@example.org", "c@example.org"],
                "cc": ["d@example.org"],
                "bcc": ["e@example.org"],
                "reply_to": "help@example.com",
                "subject": "sé",
                "html": "<p>h & more</p>",
                "headers": {"X-Run": "7"},
                "attachments": [
                    {"filename": "a.txt", "content": "aGk="},
                    {
                        "filename": "logo.png",
                        "content": "bmc=",
                        "content_type": "image/png",
                        "content_id": "logo",
                    },
                ],
            },
        )
        self.assertEqual(s.seen[1].idem, "")
        # As it is written, not as escapes.
        self.assertIn("sé", s.seen[1].body)

    def test_an_email_to_several_says_who_was_left_out(self) -> None:
        s = serve(self, 200, '{"id":"msg-1","suppressed":["c@example.org"]}')
        self.assertEqual(s.client.emails.send(EMAIL).suppressed, ["c@example.org"])

    def test_an_answer_that_is_not_cairnposts_is_not_a_send(self) -> None:
        for body in [
            "{}",
            '{"id":""}',
            '{"id":7}',
            "[]",
            "null",
            '"msg-1"',
            '{"id":"m","scheduled_at":"2030-01-01T00:00:00Z"}',
            '{"id":"m","suppressed":"all"}',
            '{"id":true}',
            "NaN",
        ]:
            with self.assertRaises(TransportError, msg=body) as raised:
                serve(self, 200, body).client.emails.send(EMAIL)
            self.assertEqual(raised.exception.reason, "not_cairnpost")
            self.assertTrue(may_have_sent(raised.exception))

    def test_what_cannot_be_sent_as_it_is_is_refused_and_nothing_is_sent(self) -> None:
        s = serve(self, 200, '{"id":"msg-1"}')
        for bad in ["a\nb", " a", "a ", "a\x00", "é", ""]:
            with self.assertRaises(ValueError):
                s.client.emails.send(Email(from_="a@example.com", to=["b@example.org"], idempotency_key=bad))
            with self.assertRaises(ValueError):
                s.client.emails.send_batch([EMAIL], idempotency_key=bad)
        odd = [
            Email(from_="a@example.com", to="b@example.org"),  # a lone address, not a list
            Email(from_="a@example.com", to=["b@example.org"], cc="c@example.org"),
            Email(
                from_="a@example.com",
                to=["b@example.org"],
                attachments=[Attachment(filename="a", content="text")],  # type: ignore[arg-type]
            ),
            Email(from_="a@example.com", to=["b@example.org"], scheduled_at=datetime(2030, 1, 1)),  # no zone
        ]
        for email in odd:
            with self.assertRaises(ValueError):
                s.client.emails.send(email)
        with self.assertRaises(ValueError):
            s.client.emails.reschedule("msg-1", datetime(2030, 1, 1))
        self.assertEqual(s.seen, [])

    def test_an_email_asked_for_later_waits_and_is_cancelled_and_moved(self) -> None:
        when = datetime(2030, 1, 2, 5, 4, 5, 678000, tzinfo=timezone(timedelta(hours=2)))
        answers = {
            1: (200, '{"id":"msg-1","scheduled_at":"2030-01-02T03:04:05.678Z"}'),
            4: (409, '{"name":"not_scheduled","message":"It was sent."}'),
        }
        answers[2] = (200, '{"id":"msg-1","state":"cancelled"}')
        s = Stand(
            self,
            lambda n, seen: answers.get(n, (200, '{"id":"msg-1","scheduled_at":"2030-02-01T00:00:00Z"}')),
        )
        sent = s.client.emails.send(
            Email(from_="a@example.com", to=["b@example.org"], subject="s", text="t", scheduled_at=when)
        )
        self.assertEqual(sent.scheduled_at, when)
        self.assertEqual(json.loads(s.seen[0].body)["scheduled_at"], "2030-01-02T03:04:05.678000Z")
        s.client.emails.cancel("msg-1")
        s.client.emails.reschedule("msg-1", datetime(2030, 2, 1, tzinfo=UTC))
        self.assertEqual(
            (s.seen[1].method, s.seen[1].path, s.seen[1].body), ("POST", "/emails/msg-1/cancel", "")
        )
        self.assertEqual(
            (s.seen[2].method, s.seen[2].path, s.seen[2].body),
            ("PATCH", "/emails/msg-1", '{"scheduled_at":"2030-02-01T00:00:00.000000Z"}'),
        )
        with self.assertRaises(CairnPostError) as gone:
            s.client.emails.cancel("msg-1")
        self.assertEqual((gone.exception.code, gone.exception.retryable), (ErrorCode.NOT_SCHEDULED, False))
        # A time in the hour a clock is set back is equal to none in
        # another zone, as the language compares them: the move is known
        # by its instant.
        back = serve(self, 200, '{"id":"msg-1","scheduled_at":"2030-11-03T05:30:00Z"}')
        back.client.emails.reschedule("msg-1", datetime(2030, 11, 3, 1, 30, tzinfo=SetBack()))
        self.assertEqual(back.seen[0].body, '{"scheduled_at":"2030-11-03T05:30:00.000000Z"}')
        # Anything else that says "fine" is not CairnPost saying it was done.
        for body in ["", "{}", "<html>maintenance</html>", '{"state":"cancelled"}']:
            other = serve(self, 200, body)
            with self.assertRaises(TransportError, msg=body):
                other.client.emails.cancel("msg-1")
            with self.assertRaises(TransportError, msg=body):
                other.client.emails.reschedule("msg-1", when)
        # One sent now that is said to wait is not CairnPost's answer.
        with self.assertRaises(TransportError):
            serve(self, 200, '{"id":"msg-1"}').client.emails.send(
                Email(from_="a@example.com", to=["b@example.org"], scheduled_at=when)
            )

    def test_get_reads_a_record_each_address_of_it_and_escapes_the_id(self) -> None:
        s = serve(self, 200, RECORD)
        m = s.client.emails.get("msg 1/../x?y")
        self.assertEqual(s.seen[0].path, "/emails/msg%201%2F..%2Fx%3Fy")
        self.assertEqual((m.state, m.from_, m.to), (State.BOUNCED, "a@example.com", "b@example.org"))
        self.assertEqual(
            [(r.address, r.kind, r.state) for r in m.recipients],
            [("b@example.org", "to", "bounced"), ("c@example.org", "cc", "delivered")],
        )
        # A time with nine digits after the second, and one in another zone: both in UTC.
        self.assertEqual(m.recipients[0].updated_at, datetime(2030, 1, 1, 0, 0, 2, 123456, tzinfo=UTC))
        self.assertEqual(
            (m.recipients[1].updated_at, m.recipients[1].updated_at.utcoffset()),
            (at("2030-01-01T00:00:03Z"), timedelta(0)),
        )
        self.assertEqual(m.suppressed, ["d@example.org"])
        e = m.events[0]
        self.assertEqual(
            (e.type, e.at, e.to, e.permanent, e.code, e.reason, e.detail),
            (
                "bounced",
                at("2030-01-01T00:00:02Z"),
                "b@example.org",
                True,
                "5.1.1",
                "permanent_failure",
                "No such user",
            ),
        )
        self.assertEqual((m.scheduled_at, m.reason), (None, None))
        assert m.content is not None
        self.assertEqual(
            m.content.attachments,
            [
                FileInfo(filename="a.txt", content_type="text/plain", content_id=None, size=2, kept=True),
                FileInfo(filename="b.png", content_type="image/png", content_id="b", size=3, kept=False),
            ],
        )
        self.assertEqual(m.content.headers, {"X-Run": "7"})
        day = '"created_at":"2030-01-01T00:00:00Z","updated_at":"2030-01-01T00:00:00Z"'
        for body in [
            "{}",
            '{"id":"m","created_at":"yesterday","updated_at":"2030-01-01T00:00:00Z"}',
            '{"id":"m","created_at":"2030-01-01","updated_at":"2030-01-01T00:00:00Z"}',
            '{"id":"m","created_at":"2030-01-01T00:00:00","updated_at":"2030-01-01T00:00:00Z"}',
            '{"id":"m","created_at":"2030-13-01T00:00:00Z","updated_at":"2030-01-01T00:00:00Z"}',
            '{"id":"m",%s,"recipients":{}}' % day,
            '{"id":"m",%s,"events":[{"type":"bounced","at":"2030-01-01T00:00:00Z","permanent":1}]}' % day,
        ]:
            with self.assertRaises(TransportError, msg=body):
                serve(self, 200, body).client.emails.get("m")

    def test_a_waiting_email_is_read_as_one(self) -> None:
        s = serve(
            self,
            200,
            '{"id":"m","state":"cancelled","scheduled_at":"2030-01-05T00:00:00Z","reason":"key_revoked","created_at":"2030-01-01T00:00:00Z","updated_at":"2030-01-01T00:00:00Z"}',
        )
        m = s.client.emails.get("m")
        self.assertEqual(
            (m.state, m.reason, m.scheduled_at, m.recipients, m.events, m.content),
            (State.CANCELLED, "key_revoked", at("2030-01-05T00:00:00Z"), [], [], None),
        )

    def test_a_kept_file_is_read_back_and_one_that_is_not_kept_is_not_found(self) -> None:
        raw = bytes([0, 255, 10, 13])
        answers: dict[int, tuple[int, bytes | str, dict[str, str]]] = {
            1: (200, raw, {"Content-Type": "application/octet-stream"}),
            2: (404, '{"name":"not_found","message":"No file."}', {}),
        }
        other: tuple[int, bytes | str, dict[str, str]] = (200, "<html>", {"Content-Type": "text/html"})
        s = Stand(self, lambda n, seen: answers.get(n, other))
        self.assertEqual(s.client.emails.file("m", 2), raw)
        self.assertEqual(s.seen[0].path, "/emails/m/attachments/2")
        with self.assertRaises(CairnPostError) as missing:
            s.client.emails.file("m", 1)
        self.assertTrue(is_not_found(missing.exception))
        # Anything else that answers 200 there is not a CairnPost server.
        with self.assertRaises(TransportError):
            s.client.emails.file("m", 1)
        for place in [0, -1, 1.5, True, "1"]:
            with self.assertRaises(ValueError):
                s.client.emails.file("m", place)  # type: ignore[arg-type]
        self.assertEqual(len(s.seen), 3)


class ABatch(unittest.TestCase):
    def test_it_answers_each_email_in_its_place(self) -> None:
        when = datetime(2030, 1, 2, tzinfo=UTC)
        s = serve(
            self,
            207,
            """{"data":[{"id":"m1","suppressed":["x@example.org"]},
            {"error":{"statusCode":429,"name":"rate_limit_exceeded","message":"Limit.","id":"m2","retry_after":30}},
            {"id":"m3","scheduled_at":"2030-01-02T00:00:00Z"},
            {"error":{"statusCode":503,"name":"not_started","message":"Its turn did not come."}},
            {"error":{"statusCode":502,"name":"SomethingNew","message":"SUBJECTMARK","id":"m5","retry_after":9}}]}""",
        )
        later = Email(from_="a@example.com", to=["b@example.org"], subject="s", text="t", scheduled_at=when)
        results = s.client.emails.send_batch([EMAIL, EMAIL, later, EMAIL, EMAIL], idempotency_key="run-1")
        self.assertEqual(
            (s.seen[0].path, s.seen[0].idem, len(json.loads(s.seen[0].body))), ("/emails/batch", "run-1", 5)
        )
        self.assertEqual(results[0].sent, Sent(id="m1", suppressed=["x@example.org"]))
        self.assertEqual(results[2].sent, Sent(id="m3", suppressed=[], scheduled_at=when))
        limited = results[1].error
        assert limited is not None
        self.assertEqual(
            (limited.status, limited.code, limited.email_id, limited.retry_after, limited.retryable),
            (429, "rate_limit_exceeded", "m2", 30.0, True),
        )
        # An email whose turn did not come was not sent.
        self.assertTrue(
            results[3].error is not None
            and results[3].error.code is ErrorCode.NOT_STARTED
            and not may_have_sent(results[3].error)
        )
        # An error this client does not know is one email's, by its status alone.
        unknown = results[4].error
        assert unknown is not None
        self.assertEqual(
            (unknown.status, unknown.code, unknown.detail, unknown.email_id, may_have_sent(unknown)),
            (502, None, None, None, True),
        )
        self.assertIsNone(unknown.retry_after, "a wait said under a name this client does not know")
        self.assertEqual(failed(results), 3)

    def test_one_refused_whole_is_an_error_and_one_with_a_key_on_an_email_is_not_sent(self) -> None:
        s = serve(
            self, 422, '{"statusCode":422,"name":"validation_error","message":"Email 2 has no subject."}'
        )
        with self.assertRaises(CairnPostError) as raised:
            s.client.emails.send_batch(iter([EMAIL, EMAIL]))
        self.assertEqual((raised.exception.status, may_have_sent(raised.exception)), (422, False))
        own = Email(from_="a@example.com", to=["b@example.org"], idempotency_key="its-own")
        with self.assertRaisesRegex(ValueError, "email 2"):
            s.client.emails.send_batch([EMAIL, own])
        self.assertEqual(len(s.seen), 1)

    def test_an_answer_that_is_not_cairnposts_is_not_trusted(self) -> None:
        for body in [
            '{"data":[{"id":"m1"}]}',
            '{"data":[{"id":"m1"},{}]}',
            '{"data":[{"id":"m1"},{"error":{"statusCode":200,"name":"validation_error"}}]}',
            '{"data":[{"id":"m1"},{"error":{"statusCode":true,"name":"validation_error"}}]}',
            '{"data":[{"id":"m1"},{"error":"no"}]}',
            '{"data":[{"id":"m1"},{"id":"m2","scheduled_at":"2030-01-01T00:00:00Z"}]}',
            "{}",
        ]:
            with self.assertRaises(TransportError, msg=body) as raised:
                serve(self, 200, body).client.emails.send_batch([EMAIL, EMAIL])
            self.assertTrue(may_have_sent(raised.exception))

    def test_an_email_is_sent_from_a_template(self) -> None:
        s = serve(self, 200, '{"id":"msg-1"}')
        s.client.emails.send(
            Email(
                from_="app@example.com",
                to=["ana@example.org"],
                template=UseTemplate(name="welcome", variables={"code": "4821"}),
            )
        )
        self.assertEqual(
            s.seen[0].body,
            '{"from":"app@example.com","to":["ana@example.org"],"subject":"","template":{"name":"welcome","variables":{"code":"4821"}}}',
        )
        b = serve(self, 200, '{"data":[{"id":"msg-1"}]}')
        b.client.emails.send_batch(
            [Email(from_="app@example.com", to=["ana@example.org"], template=UseTemplate(name="welcome"))]
        )
        self.assertEqual(
            b.seen[0].body,
            '[{"from":"app@example.com","to":["ana@example.org"],"subject":"","template":{"name":"welcome"}}]',
        )


if __name__ == "__main__":
    unittest.main()
