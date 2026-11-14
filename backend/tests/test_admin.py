import copy
import csv
import io
import json
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from admin import AdminService, conflict_key, coverage, detect_conflicts, edited_shift
from domain import Problem
from service import BookingService, Contention
from test_booking import MemoryStore, NOW, selection, shift
from handler import organizer_actor


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(shift(capacity=5), shift("two", 5))
        self.store.rows["EVENT#2026"] = {"shiftIds": ["one", "two"]}
        self.admin = AdminService(self.store, "organizer-actor", clock=lambda: NOW)
        self.booking = BookingService(self.store, clock=lambda: NOW)

    def add(self, id="one", email="family@example.com", **changes):
        return self.booking.book(email, selection(id, **changes))

    def test_auth_requires_access_token_and_exact_group(self):
        for groups in (["organizers"], "organizers", "[organizers]", '["organizers"]'):
            event = {
                "requestContext": {
                    "authorizer": {
                        "jwt": {
                            "claims": {
                                "cognito:groups": groups,
                                "token_use": "access",
                                "sub": "actor",
                            }
                        }
                    }
                }
            }
            self.assertEqual(organizer_actor(event), "actor")
        for claims in (
            {},
            {
                "cognito:groups": ["not-organizers"],
                "token_use": "access",
                "sub": "actor",
            },
            {"cognito:groups": ["organizers"], "token_use": "id", "sub": "actor"},
        ):
            with self.assertRaises(Problem):
                organizer_actor(
                    {"requestContext": {"authorizer": {"jwt": {"claims": claims}}}}
                )

    def test_overview_private_contacts_but_never_management_hashes(self):
        raw = selection()
        self.booking.book("private@example.com", raw)
        result = self.admin.overview()
        encoded = json.dumps(result)
        self.assertIn("private@example.com", encoded)
        self.assertNotIn("tokenHash", encoded)
        self.assertNotIn(raw["manageToken"], encoded)
        self.assertNotIn("pk", result["bookings"][0])

    def test_conflicts_distinguish_family_and_person_and_review(self):
        a = self.add(name="Susan Example")
        b = self.add("two", name="Other Person")
        conflicts = self.admin.overview()["conflicts"]
        self.assertEqual(conflicts[0]["kind"], "shared_email")
        key = conflicts[0]["id"]
        self.admin.review_conflict(key, {"note": "Two different family members."})
        self.assertTrue(self.admin.overview()["conflicts"][0]["reviewed"])
        self.add("two", name="Susan Example")
        self.assertTrue(
            any(c["kind"] == "same_person" for c in self.admin.overview()["conflicts"])
        )
        self.assertTrue(
            any(
                row.get("pk", "").startswith("AUDIT#")
                for row in self.store.rows.values()
            )
        )

    def test_adjacent_bookings_are_not_conflicts(self):
        self.add(start=9, end=11)
        self.add("two", start=11, end=13)
        self.assertEqual(self.admin.overview()["conflicts"], [])

    def test_edit_rejects_lower_limit_and_invalidates_no_bookings(self):
        self.add()
        self.add(name="Second Person")
        with self.assertRaises(Problem):
            self.admin.update_shift("one", {"revision": 2, "capacity": 1})
        with self.assertRaises(Problem):
            self.admin.update_shift("one", {"revision": 2, "start": 10})
        with self.assertRaises(Problem):
            self.admin.update_shift("one", {"revision": 2, "flex": False})
        self.assertEqual(self.store.get("SHIFT#one")["revision"], 2)
        self.admin.update_shift(
            "one", {"revision": 2, "capacity": 1, "overflowPercent": 100}
        )
        self.assertEqual(self.store.get("SHIFT#one")["capacity"], 1)
        self.assertEqual(len(self.store.get("SHIFT#one")["roster"]), 2)

    def test_edit_requires_revision_and_atomic_compare(self):
        with self.assertRaises(Problem):
            self.admin.update_shift("one", {"revision": 99, "capacity": 3})
        original = self.store.commit_admin_shift
        self.store.commit_admin_shift = lambda *args: (_ for _ in ()).throw(
            Contention()
        )
        with self.assertRaises(Problem) as error:
            self.admin.update_shift("one", {"revision": 0, "capacity": 3})
        self.assertEqual(error.exception.code, "stale")
        self.store.commit_admin_shift = original
        self.admin.update_shift("one", {"revision": 0, "capacity": 3})
        self.assertEqual(self.store.get("SHIFT#one")["revision"], 1)

    def test_edit_validates_policy_and_whole_event_window(self):
        for payload in (
            {"capacity": True},
            {"overflowPercent": float("nan")},
            {"attendance": {"incrementMinutes": 0}},
            {"attendance": {"minMinutes": 300}},
            {"attendance": {"allowedStarts": []}},
            {"attendance": {"allowedStarts": [9.25]}},
            {"date": "2030-01-01"},
        ):
            with self.subTest(payload=payload), self.assertRaises(Problem):
                self.admin.update_shift("one", {"revision": 0, **payload})
        self.admin.update_shift(
            "one",
            {
                "revision": 0,
                "attendance": {
                    "incrementMinutes": 15,
                    "minMinutes": 45,
                    "allowedStarts": [9, 9.25],
                },
            },
        )
        self.assertEqual(
            self.store.get("SHIFT#one")["attendance"]["incrementMinutes"], 15
        )

    def test_coverage_respects_departure(self):
        self.add(start=9, end=11)
        segments = self.admin.overview()["shifts"][0]["coverage"]
        self.assertEqual(next(s for s in segments if s["start"] == 10.5)["count"], 1)
        self.assertEqual(next(s for s in segments if s["start"] == 11)["count"], 0)

    def test_admin_cancel_frees_capacity_and_audits(self):
        result = self.add()
        self.admin.cancel_booking(result["bookingId"])
        self.assertEqual(self.store.get("SHIFT#one")["roster"], [])
        self.assertEqual(self.admin.overview()["bookings"], [])
        self.assertEqual(
            self.admin.cancel_booking(result["bookingId"])["status"], "canceled"
        )
        self.assertTrue(
            any(
                row.get("kind") == "booking_canceled"
                for row in self.store.rows.values()
            )
        )

    def test_task_configuration_and_exported_preferences(self):
        self.admin.update_shift(
            "one",
            {
                "revision": 0,
                "subJobs": [
                    {
                        "id": "cashier",
                        "label": "Checkout",
                        "description": "Help at the till",
                    }
                ],
            },
        )
        self.add(subJobs=["cashier"])
        overview = self.admin.overview()
        self.assertEqual(
            overview["bookings"][0]["subJobPreferences"][0]["label"], "Checkout"
        )
        self.assertIn("Task preferences", self.admin.export({}))
        self.assertIn("Checkout", self.admin.export({}))
        with self.assertRaises(Problem):
            self.admin.update_shift(
                "one",
                {
                    "revision": 2,
                    "subJobs": [
                        {"id": "same", "label": "A"},
                        {"id": "same", "label": "B"},
                    ],
                },
            )

    def test_export_filters_and_neutralizes_formula(self):
        self.add(name='=HYPERLINK("https://bad")')
        self.add("two", email="other@example.com", name="Someone Else")
        rows = list(
            csv.reader(
                io.StringIO(self.admin.export({"shiftId": "one"}).lstrip("\ufeff"))
            )
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[1][0].startswith("'="))
        self.assertEqual(
            len(
                list(
                    csv.reader(
                        io.StringIO(
                            self.admin.export({"q": "Someone"}).lstrip("\ufeff")
                        )
                    )
                )
            ),
            2,
        )

    def test_messages_deduplicate_family_and_support_single_group_all(self):
        a = self.add(name="Susan")
        self.add("two", name="Andy")
        self.add("two", email="other@example.com", name="Dave")
        base = {"subject": "Meet here", "body": "Hello team"}
        all = self.admin.message_preview({**base, "selector": {"mode": "all"}})
        self.assertEqual(all["recipientCount"], 2)
        self.assertEqual(all["volunteerCount"], 3)
        single = self.admin.message_preview(
            {**base, "selector": {"mode": "selected", "bookingIds": [a["bookingId"]]}}
        )
        self.assertEqual(single["recipientCount"], 1)
        self.assertEqual(single["volunteerCount"], 1)
        group = self.admin.message_preview(
            {**base, "selector": {"mode": "group", "field": "shiftId", "value": "two"}}
        )
        self.assertEqual(group["volunteerCount"], 2)
        self.assertFalse(all["emailEnabled"])

    def test_saved_draft_is_private_and_requires_fresh_snapshot(self):
        self.add()
        payload = {
            "subject": "Hello",
            "body": "Meet at the lot",
            "selector": {"mode": "all"},
        }
        preview = self.admin.message_preview(payload)
        self.add("two", name="Another person")
        with self.assertRaises(Problem):
            self.admin.save_message({**payload, "fingerprint": preview["fingerprint"]})
        preview = self.admin.message_preview(payload)
        result = self.admin.save_message(
            {**payload, "fingerprint": preview["fingerprint"]}
        )
        self.assertFalse(result["emailEnabled"])
        draft = self.store.get("DRAFT#" + result["id"])
        self.assertEqual(draft["status"], "draft_sending_disabled")
        self.assertEqual(len(draft["recipients"]), 1)
        self.assertLess(draft["expiresAt"], NOW + 31 * 86400)
        listed = self.admin.list_drafts()["drafts"]
        self.assertEqual(listed[0]["id"], result["id"])
        self.assertNotIn("recipients", listed[0])
        self.assertEqual(listed[0]["selector"], {"mode": "all"})
