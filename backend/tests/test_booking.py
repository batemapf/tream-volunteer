import copy
import json
import secrets
import sys
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain import Problem, effective_capacity, epoch, retention_expiry, token_hash
from service import BookingService, Contention, public_shift

NOW = epoch("2026-11-12", 12)


def shift(id="one", capacity=1):
    return {
        "pk": "SHIFT#" + id,
        "id": id,
        "date": "2026-12-05",
        "name": "Lot sales",
        "role": "Sales",
        "start": 9,
        "end": 13,
        "capacity": capacity,
        "flex": True,
        "attendance": {"incrementMinutes": 30, "minMinutes": 30},
        "overflowPercent": 0,
        "revision": 0,
        "roster": [],
        "open": True,
        "endAt": epoch("2026-12-05", 13),
        "publicUntil": epoch("2026-12-07", 0),
        "expiresAt": retention_expiry(epoch("2026-12-06", 19)),
    }


def selection(id="one", **kwargs):
    return {
        "shiftId": id,
        "start": 9,
        "end": 11,
        "name": "Susan Example",
        "shareName": False,
        "idempotencyKey": str(uuid.uuid4()),
        "participantId": str(uuid.uuid4()),
        "manageToken": secrets.token_urlsafe(32),
        **kwargs,
    }


class MemoryStore:
    def __init__(self, *shifts):
        self.rows = {s["pk"]: copy.deepcopy(s) for s in shifts}
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            return copy.deepcopy(self.rows.get(key))

    def get_many(self, keys):
        return [self.get(key) for key in keys]

    def list_drafts(self, now):
        return sorted(
            [
                copy.deepcopy(row)
                for row in self.rows.values()
                if row.get("recordType") == "messageDraft" and row["expiresAt"] > now
            ],
            key=lambda row: row["createdAt"],
            reverse=True,
        )[:50]

    def commit_records(self, rows):
        with self.lock:
            for row in rows:
                self.rows[row["pk"]] = copy.deepcopy(row)

    def commit_admin_shift(self, old, new, audit):
        with self.lock:
            if self.rows[old["pk"]]["revision"] != old["revision"]:
                raise Contention()
            self.rows[new["pk"]] = copy.deepcopy(new)
            self.rows[audit["pk"]] = copy.deepcopy(audit)

    def commit_booking(self, old, new, booking, idem, outbox):
        with self.lock:
            if (
                self.rows[old["pk"]]["revision"] != old["revision"]
                or idem["pk"] in self.rows
            ):
                raise Contention()
            for row in (new, booking, idem, outbox):
                self.rows[row["pk"]] = copy.deepcopy(row)

    def commit_cancel(self, old, new, booking, audit=None):
        with self.lock:
            if (
                self.rows[old["pk"]]["revision"] != old["revision"]
                or self.rows[booking["pk"]]["status"] != "active"
            ):
                raise Contention()
            self.rows[new["pk"]] = copy.deepcopy(new)
            self.rows[booking["pk"]]["status"] = "canceled"
            if audit:
                self.rows[audit["pk"]] = copy.deepcopy(audit)


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(shift(), shift("two"))
        self.service = BookingService(self.store, clock=lambda: NOW)

    def book(self, raw=None):
        return self.service.book("parent@example.com", raw or selection())

    def test_competing_claims_never_overbook(self):
        service = BookingService(MemoryStore(shift(capacity=3)), clock=lambda: NOW)

        def compete(_):
            try:
                return service.book("parent@example.com", selection())["status"]
            except Problem as e:
                return e.code

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(compete, range(20)))
        self.assertEqual(results.count("booked"), 3)
        self.assertEqual(len(service.store.get("SHIFT#one")["roster"]), 3)

    def test_retry_is_idempotent_and_token_not_retained(self):
        raw = selection()
        first = self.book(raw)
        self.assertEqual(first, self.book(raw))
        self.assertEqual(len(self.store.get("SHIFT#one")["roster"]), 1)
        serialized = json.dumps(self.store.rows)
        self.assertNotIn(raw["manageToken"], serialized)
        self.assertIn(token_hash(raw["manageToken"]), serialized)
        raw["name"] = "Someone else"
        with self.assertRaises(Problem) as e:
            self.book(raw)
        self.assertEqual(e.exception.code, "idempotency_conflict")

    def test_departure_does_not_consume_later_capacity(self):
        self.book(selection(start=9, end=11))
        self.book(selection(start=11, end=13))
        with self.assertRaises(Problem) as e:
            self.book(selection(start=10.5, end=11.5))
        self.assertEqual(e.exception.code, "full")

    def test_batch_keeps_valid_selections_and_shared_email(self):
        self.book()
        result = self.service.batch(
            "parent@example.com", [selection(), selection("two"), None]
        )
        self.assertEqual(
            [r["status"] for r in result["results"]], ["failed", "booked", "failed"]
        )

    def test_full_window_and_minimum_are_server_enforced(self):
        self.store.rows["SHIFT#one"]["flex"] = False
        with self.assertRaises(Problem):
            self.book()
        self.book(selection(end=13))
        self.store.rows["SHIFT#two"]["attendance"]["minMinutes"] = 90
        with self.assertRaises(Problem):
            self.book(selection("two", end=10))

    def test_entire_window_is_valid_when_increment_does_not_divide_length(self):
        self.store.rows["SHIFT#one"]["end"] = 12.5
        self.store.rows["SHIFT#one"]["flex"] = False
        self.store.rows["SHIFT#one"]["attendance"]["incrementMinutes"] = 60
        result = self.book(selection(end=12.5))
        self.assertEqual(result["end"], 12.5)

    def test_five_minute_choices_are_not_rejected_by_float_rounding(self):
        self.store.rows["SHIFT#one"]["attendance"] = {
            "incrementMinutes": 5,
            "minMinutes": 5,
            "maxMinutes": 5,
        }
        result = self.book(selection(start=9 + 5 / 60, end=9 + 10 / 60))
        self.assertEqual(round((result["end"] - result["start"]) * 60), 5)
        self.book(selection(start=9 + 10 / 60, end=9 + 15 / 60))

    def test_optional_task_preferences_validate_and_stay_private(self):
        self.store.rows["SHIFT#one"]["subJobs"] = [
            {"id": "cashier", "label": "Cashier"},
            {"id": "chainsaw", "label": "Chainsaw"},
            {"id": "retired", "label": "Old choice", "enabled": False},
        ]
        result = self.book(selection(subJobs=["cashier", "chainsaw"]))
        saved = self.store.get("BOOKING#" + result["bookingId"])
        self.assertEqual(
            [p["label"] for p in saved["subJobPreferences"]], ["Cashier", "Chainsaw"]
        )
        public = public_shift(self.store.get("SHIFT#one"), NOW)
        self.assertEqual([p["id"] for p in public["subJobs"]], ["cashier", "chainsaw"])
        self.assertNotIn("subJobPreferences", public["roster"][0])
        for options in (["unknown"], ["retired"], ["cashier", "cashier"], "cashier"):
            with self.subTest(options=options), self.assertRaises(Problem):
                self.book(selection(subJobs=options))

    def test_task_preferences_are_optional_and_snapshot_labels(self):
        self.store.rows["SHIFT#one"]["subJobs"] = [{"id": "sales", "label": "Sales"}]
        booked = self.book(selection())
        self.assertEqual(
            self.store.get("BOOKING#" + booked["bookingId"])["subJobPreferences"], []
        )
        other = self.service.book("parent@example.com", selection("two"))
        self.assertEqual(other["subJobPreferences"], [])
        self.store.rows["SHIFT#two"]["subJobs"] = [
            {"id": "custom", "label": "Original label"}
        ]
        # A separate adjacent interval can hold a different volunteer preference.
        chosen = self.service.book(
            "parent@example.com", selection("two", start=11, end=12, subJobs=["custom"])
        )
        self.store.rows["SHIFT#two"]["subJobs"][0]["label"] = "Renamed label"
        self.assertEqual(
            self.store.get("BOOKING#" + chosen["bookingId"])["subJobPreferences"][0][
                "label"
            ],
            "Original label",
        )

    def test_invalid_numbers_and_grid(self):
        for start, end in [(True, 11), (9, float("nan")), (8, 11), (9, 9), (9, 10.25)]:
            with self.subTest(start=start, end=end), self.assertRaises(Problem):
                self.book(selection(start=start, end=end))

    def test_overflow_rounding_and_actual_limit(self):
        s = shift(capacity=3)
        s["overflowPercent"] = 25
        self.assertEqual(effective_capacity(s), 3)
        s["overflowPercent"] = 50
        self.assertEqual(effective_capacity(s), 4)
        service = BookingService(MemoryStore(s), clock=lambda: NOW)
        for _ in range(4):
            service.book("parent@example.com", selection())
        with self.assertRaises(Problem):
            service.book("parent@example.com", selection())

    def test_public_projection_never_returns_contacts_or_tokens(self):
        raw = selection(shareName=True)
        self.book(raw)
        data = public_shift(self.store.get("SHIFT#one"), NOW)
        output = json.dumps(data)
        for private in [
            "parent@example.com",
            "Susan Example",
            raw["manageToken"],
            "tokenHash",
            "participantId",
        ]:
            self.assertNotIn(private, output)
        self.assertEqual(data["roster"][0]["publicName"], "Susan E.")
        self.assertEqual(
            public_shift(self.store.get("SHIFT#one"), epoch("2026-12-08", 0))["roster"],
            [],
        )

    def test_management_read_does_not_cancel_and_wrong_token_fails(self):
        raw = selection()
        result = self.book(raw)
        self.assertEqual(
            self.service.managed(result["bookingId"], raw["manageToken"])["status"],
            "active",
        )
        with self.assertRaises(Problem):
            self.service.cancel(result["bookingId"], secrets.token_urlsafe(32))
        self.assertEqual(
            self.service.cancel(result["bookingId"], raw["manageToken"]),
            {"status": "canceled"},
        )
        self.assertEqual(
            self.service.cancel(result["bookingId"], raw["manageToken"]),
            {"status": "canceled"},
        )
        self.book()

    def test_expired_management_denied(self):
        raw = selection()
        result = self.book(raw)
        self.service.clock = lambda: epoch("2030-01-01", 0)
        with self.assertRaises(Problem):
            self.service.managed(result["bookingId"], raw["manageToken"])

    def test_retention_is_27_calendar_months_and_dst_is_local(self):
        from datetime import datetime, timezone

        end = int(datetime(2026, 12, 31, tzinfo=timezone.utc).timestamp())
        self.assertEqual(
            datetime.fromtimestamp(retention_expiry(end), timezone.utc).isoformat(),
            "2029-03-31T00:00:00+00:00",
        )
        self.assertEqual(
            epoch("2026-12-05", 9) - epoch("2026-07-05", 9), 153 * 86400 + 3600
        )


if __name__ == "__main__":
    unittest.main()
