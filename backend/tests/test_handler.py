import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import handler
from test_booking import MemoryStore, NOW, selection, shift


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.previous = handler._store
        handler._store = MemoryStore(shift())
        handler._store.rows["EVENT#2026"] = {"shiftIds": ["one"]}
        self.origin = patch.dict(
            os.environ, {"SITE_ORIGIN": "https://board.example.com"}
        )
        self.origin.start()
        self.clock = patch("handler.time.time", return_value=NOW)
        self.clock.start()

    def tearDown(self):
        handler._store = self.previous
        self.origin.stop()
        self.clock.stop()

    def call(self, method, path, body=None, headers=None):
        event = {
            "requestContext": {"http": {"method": method}},
            "rawPath": path,
            "headers": headers or {},
            "body": json.dumps(body) if body is not None else "",
        }
        response = handler.handler(event, None)
        return response["statusCode"], json.loads(response["body"])

    def test_public_schedule_has_no_storage_fields(self):
        status, body = self.call("GET", "/schedule")
        self.assertEqual(status, 200)
        self.assertEqual(body["shifts"][0]["id"], "one")
        for field in ("pk", "revision", "expiresAt"):
            self.assertNotIn(field, body["shifts"][0])

    def test_origin_required_for_write(self):
        payload = {"email": "parent@example.com", "selections": [selection()]}
        self.assertEqual(self.call("POST", "/bookings", payload)[0], 403)
        self.assertEqual(
            self.call(
                "POST", "/bookings", payload, {"origin": "https://other.example.com"}
            )[0],
            403,
        )
        self.assertEqual(
            self.call(
                "POST", "/bookings", payload, {"origin": "https://board.example.com"}
            )[0],
            200,
        )

    def test_get_does_not_mutate_and_cancel_needs_token(self):
        raw = selection()
        _, result = self.call(
            "POST",
            "/bookings",
            {"email": "parent@example.com", "selections": [raw]},
            {"origin": "https://board.example.com"},
        )
        id = result["results"][0]["bookingId"]
        token = {"Authorization": "Bearer " + raw["manageToken"]}
        self.assertEqual(
            self.call("GET", "/bookings/" + id, headers=token)[1]["status"], "active"
        )
        self.assertEqual(
            self.call("GET", "/bookings/" + id + "/cancel", headers=token)[0], 404
        )
        self.assertEqual(
            self.call(
                "POST",
                "/bookings/" + id + "/cancel",
                {},
                {"origin": "https://board.example.com"},
            )[0],
            403,
        )
        self.assertEqual(
            self.call(
                "POST",
                "/bookings/" + id + "/cancel",
                {},
                {**token, "origin": "https://board.example.com"},
            )[1]["status"],
            "canceled",
        )

    def test_invalid_batch_is_bad_request(self):
        for payload in (
            [],
            {"email": "parent@example.com", "selections": []},
            {"email": "parent@example.com", "selections": [selection()] * 21},
        ):
            self.assertEqual(
                self.call(
                    "POST",
                    "/bookings",
                    payload,
                    {"origin": "https://board.example.com"},
                )[0],
                400,
            )

    def test_admin_requires_trusted_access_claims_not_bearer_header(self):
        self.assertEqual(
            self.call(
                "GET", "/admin/overview", headers={"Authorization": "Bearer invented"}
            )[0],
            403,
        )
        event = {
            "requestContext": {
                "http": {"method": "GET"},
                "authorizer": {
                    "jwt": {
                        "claims": {
                            "sub": "actor",
                            "token_use": "id",
                            "cognito:groups": ["organizers"],
                        }
                    }
                },
            },
            "rawPath": "/admin/overview",
            "headers": {},
        }
        self.assertEqual(handler.handler(event, None)["statusCode"], 403)
        event["requestContext"]["authorizer"]["jwt"]["claims"]["token_use"] = "access"
        result = handler.handler(event, None)
        self.assertEqual(result["statusCode"], 200)
        self.assertIn("bookings", json.loads(result["body"]))

    def test_health_does_not_require_database(self):
        handler._store = None
        self.assertEqual(
            self.call("GET", "/health")[1],
            {"ok": True, "environment": "development", "emailEnabled": False},
        )
        self.assertIsNone(handler._store)
