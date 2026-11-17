from __future__ import annotations

import unittest
from datetime import UTC, datetime

from cairnpost import (
    CairnPostError,
    DeliveryState,
    ErrorCode,
    Limits,
    NotCapturingError,
    Quota,
    Reason,
    Suppression,
    TemplateVariable,
    TransportError,
    WebhookTest,
    is_wrong_address,
)

from .stand import UP, Seen, Stand, serve

DAY = '"created_at":"2030-01-01T00:00:00Z"'
ENDPOINT = (
    '{"id":"wh-1","url":"https://app.example.com/hook","events":["email.bounced"],"enabled":true,' + DAY
)
TEMPLATE = (
    '{"id":"t-1","name":"welcome","subject":"Hello {{name}}","html":"<p>{{code}}</p>",'
    '"variables":[{"name":"name","default":"there","required":false},{"name":"code","required":true},'
    '{"name":"ps","default":"","required":false}],' + DAY + ',"updated_at":"2030-01-02T00:00:00Z"}'
)


def calls(s: Stand) -> list[str]:
    return [f"{r.method} {r.path}{'?' + r.query if r.query else ''}" for r in s.seen]


class WithAnAdminKey(unittest.TestCase):
    def test_suppressions_are_paged_and_walked(self) -> None:
        pages = {
            1: '{"data":[{"domain":"example.com","address":"a@example.org","reason":"bounce","email_id":"m1",%s}],"next":"cursor 1"}'
            % DAY,
        }
        last = (
            '{"data":[{"domain":"example.com","address":"b@example.org","reason":"manual","note":"asked",%s}]}'
            % DAY
        )
        s = Stand(self, lambda n, seen: (200, pages.get(n, last)))
        self.assertEqual(
            [f"{x.address}:{x.reason}" for x in s.client.suppressions.all("example.com")],
            ["a@example.org:bounce", "b@example.org:manual"],
        )
        self.assertEqual(
            [r.query for r in s.seen],
            ["limit=200&domain=example.com", "limit=200&after=cursor+1&domain=example.com"],
        )
        page = s.client.suppressions.list(limit=5)
        self.assertEqual((len(page.data), page.next, s.seen[2].query), (1, None, "limit=5"))
        self.assertEqual(
            page.data[0],
            Suppression(
                domain="example.com",
                address="b@example.org",
                reason="manual",
                email_id=None,
                note="asked",
                created_at=datetime(2030, 1, 1, tzinfo=UTC),
            ),
        )
        # A walk stops at the first error and says it.
        refused = serve(self, 403, '{"name":"admin_key_required","message":"Admin."}')
        with self.assertRaises(CairnPostError) as raised:
            list(refused.client.suppressions.all())
        self.assertEqual((raised.exception.code, len(refused.seen)), (ErrorCode.ADMIN_KEY_REQUIRED, 1))

    def test_a_walk_stops_at_a_cursor_that_does_not_move(self) -> None:
        s = serve(
            self,
            200,
            '{"data":[{"domain":"example.com","address":"a@example.org","reason":"bounce",%s}],"next":"same"}'
            % DAY,
        )
        self.assertEqual((len(list(s.client.suppressions.all())), len(s.seen)), (2, 2))

    def test_suppress_and_lift(self) -> None:
        answers = {
            1: (201, '{"domain":"example.com","address":"a@example.org","added":true}'),
            2: (200, '{"domain":"example.com","address":"a@example.org","added":false}'),
            3: (200, '{"lifted":1}'),
        }
        s = Stand(self, lambda n, seen: answers.get(n, (200, '{"lifted":3}')))
        self.assertIs(s.client.suppressions.add("example.com", "a@example.org", "asked"), True)
        self.assertIs(s.client.suppressions.add("example.com", "a@example.org"), False)
        s.client.suppressions.lift("example.com", "a@example.org")
        self.assertEqual(s.client.suppressions.lift_all("example.com", Reason.BOUNCE), 3)
        self.assertEqual(
            [r.body for r in s.seen],
            [
                '{"domain":"example.com","address":"a@example.org","note":"asked"}',
                '{"domain":"example.com","address":"a@example.org"}',
                '{"domain":"example.com","address":"a@example.org"}',
                '{"domain":"example.com","all":true,"reason":"bounce"}',
            ],
        )
        self.assertEqual((s.seen[2].path, s.seen[3].path), ("/suppressions/lift", "/suppressions/lift"))

    def test_webhooks_and_deliveries(self) -> None:
        answers: list[tuple[int, str]] = [
            (201, ENDPOINT + ',"secret":"whsec_c2VjcmV0"}'),
            (200, '{"data":[' + ENDPOINT + "}]}"),
            (200, ENDPOINT + "}"),
            (204, ""),
            (200, '{"delivered":false,"status":500,"failure":"status"}'),
            (
                200,
                '{"data":[{"id":"dlv-1","email_id":"m1","type":"email.bounced","state":"failed","attempts":8,"last_status":500,"last_failure":"status",%s,"attempted_at":"2030-01-01T00:00:01Z"}],"next":"c2"}'
                % DAY,
            ),
            (
                200,
                '{"data":[{"id":"dlv-2","inbound_id":"in-1","type":"email.received","state":"failed","attempts":1,%s}]}'
                % DAY,
            ),
            (200, '{"state":"pending"}'),
        ]
        s = Stand(self, lambda n, seen: answers[n - 1])
        w = s.client.webhooks
        made = w.create("https://app.example.com/hook", events=["email.bounced"], description="")
        self.assertEqual(
            (made.id, made.secret, made.enabled, made.events, made.domain),
            ("wh-1", "whsec_c2VjcmV0", True, ["email.bounced"], None),
        )
        self.assertNotIn("whsec_", repr(made) + str(made))
        self.assertEqual(s.seen[0].body, '{"url":"https://app.example.com/hook","events":["email.bounced"]}')
        self.assertEqual(len(w.list()), 1)
        self.assertIsNone(w.get("wh-1").secret)
        w.delete("wh-1")
        self.assertEqual(w.test("wh-1"), WebhookTest(delivered=False, status=500, failure="status"))
        got = [
            f"{d.id}:{d.email_id or d.inbound_id}:{d.last_status}"
            for d in w.all_deliveries("wh-1", DeliveryState.FAILED)
        ]
        self.assertEqual(got, ["dlv-1:m1:500", "dlv-2:in-1:None"])
        w.retry_delivery("wh-1", "dlv 1")
        self.assertEqual(
            calls(s),
            [
                "POST /webhooks",
                "GET /webhooks",
                "GET /webhooks/wh-1",
                "DELETE /webhooks/wh-1",
                "POST /webhooks/wh-1/test",
                "GET /webhooks/wh-1/deliveries?limit=200&state=failed",
                "GET /webhooks/wh-1/deliveries?limit=200&after=c2&state=failed",
                "POST /webhooks/wh-1/deliveries/dlv%201/retry",
            ],
        )
        with self.assertRaises(ValueError):
            w.create("https://app.example.com/hook", events="email.bounced")

    def test_a_webhook_change_can_switch_off_and_clear_and_leaves_the_rest_alone(self) -> None:
        s = serve(self, 200, ENDPOINT + "}")
        s.client.webhooks.update("wh-1", enabled=False, events=[], description="")
        s.client.webhooks.update("wh-1", url="https://app.example.com/new")
        self.assertEqual(
            [f"{r.method} {r.body}" for r in s.seen],
            [
                'PATCH {"events":[],"description":"","enabled":false}',
                'PATCH {"url":"https://app.example.com/new"}',
            ],
        )

    def test_a_secret_is_rotated_an_endpoint_resumed_and_each_says_how_it_stands(self) -> None:
        s = serve(
            self,
            200,
            ENDPOINT
            + ',"secret":"whsec_bmV3","failing_since":"2030-01-02T00:00:00Z","paused_at":"2030-01-07T00:00:00Z","previous_secret_until":"2030-01-08T00:00:00Z"}',
        )
        w = s.client.webhooks.rotate_secret("wh-1")
        assert w.failing_since and w.paused_at and w.previous_secret_until
        self.assertEqual(
            (w.secret, w.failing_since.day, w.paused_at.day, w.previous_secret_until.day),
            ("whsec_bmV3", 2, 7, 8),
        )
        s.client.webhooks.resume("wh-1")
        self.assertEqual(
            [f"{r.method} {r.path} {r.body}" for r in s.seen],
            ["POST /webhooks/wh-1/secret ", "POST /webhooks/wh-1/resume "],
        )
        # An answer that is no endpoint is refused.
        with self.assertRaises(TransportError):
            serve(self, 200, '{"url":"https://app.example.com/hook"}').client.webhooks.get("wh-1")

    def test_templates_are_kept_read_changed_and_deleted(self) -> None:
        s = serve(self, 200, TEMPLATE)
        made = s.client.templates.create(
            name="welcome", subject="Hello {{name}}", html="<p>{{code}}</p>", defaults={"name": "there"}
        )
        self.assertEqual(
            made.variables,
            [
                TemplateVariable(name="name", default="there", required=False),
                TemplateVariable(name="code", default=None, required=True),
                TemplateVariable(name="ps", default="", required=False),
            ],
        )
        self.assertEqual((made.id, made.updated_at.day, made.text, made.domain), ("t-1", 2, None, None))
        self.assertEqual(
            s.seen[0].body,
            '{"name":"welcome","subject":"Hello {{name}}","html":"<p>{{code}}</p>","defaults":{"name":"there"}}',
        )
        s.client.templates.get("a/b")
        s.client.templates.update("t-1", subject="Hi", defaults={})
        self.assertEqual(
            (s.seen[1].path, s.seen[2].method, s.seen[2].body),
            ("/templates/a%2Fb", "PATCH", '{"subject":"Hi","defaults":{}}'),
        )
        listed = serve(self, 200, '{"data":[' + TEMPLATE + '],"more":true}')
        every = listed.client.templates.list()
        self.assertEqual((len(every.data), every.more, listed.seen[0].query), (1, True, ""))
        listed.client.templates.list("shop.example.com")
        self.assertEqual(listed.seen[1].query, "domain=shop.example.com")
        gone = serve(self, 204, "")
        gone.client.templates.delete("t-1")
        self.assertEqual(calls(gone), ["DELETE /templates/t-1"])
        with self.assertRaises(CairnPostError) as taken:
            serve(
                self,
                409,
                '{"statusCode":409,"name":"name_taken","message":"A template of this name is already there."}',
            ).client.templates.create(name="welcome", subject="s", text="t")
        self.assertIs(taken.exception.code, ErrorCode.NAME_TAKEN)
        with self.assertRaises(TransportError, msg="an empty answer was taken for a template"):
            serve(self, 200, "{}").client.templates.get("t-1")

    def test_a_received_email_is_read_with_what_it_says_and_as_it_came(self) -> None:
        one = '{"id":"in-1","to":"help@example.com","from":"ana@example.org","received_at":"2030-01-01T00:00:00Z","kept_until":"2030-01-08T00:00:00Z","size":512'
        raw = b"From: ana@example.org\r\n\r\n\xff"

        def answer(n: int, seen: Seen) -> tuple[int, bytes | str, dict[str, str]]:
            if n == 1:
                return (
                    200,
                    one
                    + ',"content":{"subject":"Hi","from":"Ana <ana@example.org>","to":["help@example.com"],"date":"2029-12-31T23:59:00Z","text":"hello","headers":[{"name":"Received","value":"x"},{"name":"Received","value":"y"}],"attachments":[{"filename":"a.pdf","content_type":"application/pdf","size":9}],"partial":true}}',
                    {},
                )
            if n == 2:
                return (
                    200,
                    '{"data":['
                    + one
                    + '},{"id":"in-0","to":"help@example.com","received_at":"2030-01-01T00:00:00Z","kept_until":"2030-01-08T00:00:00Z","size":1}]}',
                    {},
                )
            if n in (3, 4):
                return 200, raw, {"Content-Type": "application/octet-stream"}
            return 204, "", {}

        s = Stand(self, answer)
        r = s.client.received
        got = r.get("in-1")
        assert got.content is not None
        self.assertEqual(
            (
                got.from_,
                got.size,
                got.kept_until.day,
                got.content.subject,
                got.content.from_,
                got.content.partial,
                got.content.cc,
                got.content.html,
            ),
            ("ana@example.org", 512, 8, "Hi", "Ana <ana@example.org>", True, [], None),
        )
        self.assertEqual([h.value for h in got.content.headers], ["x", "y"])
        self.assertEqual(got.content.attachments[0].filename, "a.pdf")
        self.assertEqual(
            [(item.from_, item.content) for item in r.all()], [("ana@example.org", None), (None, None)]
        )
        self.assertEqual(r.raw("in-1"), raw)
        self.assertEqual(r.file("in-1", 1), raw)
        r.delete("in-1")
        self.assertEqual(
            calls(s),
            [
                "GET /inbound/in-1",
                "GET /inbound?limit=200",
                "GET /inbound/in-1/raw",
                "GET /inbound/in-1/attachments/1",
                "DELETE /inbound/in-1",
            ],
        )

    def test_limits_health_and_captured(self) -> None:
        def answer(n: int, seen: Seen) -> tuple[int, str]:
            if seen.path == "/limits":
                first = '{"driver":"cloudflare","quota":{"limit":200,"per":"day","used":7,"over":false,"resets_at":"2030-01-02T00:00:00Z"}}'
                return 200, first if n == 1 else '{"driver":"capture","quota":null}'
            if seen.path == "/health":
                return (
                    503,
                    '{"status":"unavailable","driver":"capture","version":"0.1.1","events":"off","webhooks":"sending","pruning":"running","scheduled":"sending","inbound":"off"}',
                )
            return (
                200,
                '{"data":[{"id":"c1","at":"2030-01-01T00:00:00Z","from":"a@example.com","to":["b@example.org"],"subject":"s","text":"t","attachments":[{"filename":"a.txt","content_type":"text/plain","size":2}]}]}',
            )

        s = Stand(self, answer)
        self.assertEqual(
            s.client.limits(),
            Limits(
                driver="cloudflare",
                quota=Quota(
                    limit=200, per="day", used=7, over=False, resets_at=datetime(2030, 1, 2, tzinfo=UTC)
                ),
            ),
        )
        self.assertEqual(s.client.limits(), Limits(driver="capture", quota=None))
        # A server that is up and cannot reach its database is answered, not an error.
        h = s.client.health()
        self.assertEqual(
            (h.ok, h.status, h.version, h.webhooks, h.inbound),
            (False, "unavailable", "0.1.1", "sending", "off"),
        )
        held = s.client.captured()
        self.assertEqual(
            (held[0].subject, held[0].from_, held[0].to, held[0].cc, held[0].attachments[0].size),
            ("s", "a@example.com", ["b@example.org"], [], 2),
        )

    def test_health_says_a_wrong_address_and_captured_a_server_that_delivers_for_real(self) -> None:
        nothing = '{"name":"route_not_found","message":"Nothing here."}'
        for status, body in [
            (404, nothing),
            (404, "<html>"),
            (200, '{"ok":true}'),
            (503, "<html>down</html>"),
            (503, '{"name":"unavailable","message":"Down."}'),
        ]:
            with self.assertRaises((CairnPostError, TransportError), msg=body) as raised:
                serve(self, status, body).client.health()
            self.assertEqual(is_wrong_address(raised.exception), status == 404, body)
        real_up = UP.replace("capture", "cloudflare")
        real = Stand(self, lambda n, seen: (200, real_up) if seen.path == "/health" else (404, nothing))
        with self.assertRaises(NotCapturingError):
            real.client.captured()
        # With no server of CairnPost's there at all, the address is what is wrong.
        with self.assertRaises(CairnPostError) as astray:
            serve(self, 404, nothing).client.captured()
        self.assertTrue(is_wrong_address(astray.exception))
        self.assertIsNone(astray.exception.__context__)
        # Health failing some other way is its own error, not a wrong address.
        down = Stand(self, lambda n, seen: None if seen.path == "/health" else (404, nothing))
        with self.assertRaises(TransportError):
            down.client.captured()


if __name__ == "__main__":
    unittest.main()
