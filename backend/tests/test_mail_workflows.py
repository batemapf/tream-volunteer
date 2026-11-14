import copy
import os
import unittest
from unittest.mock import patch
from test_booking import MemoryStore, shift, selection, NOW
from service import BookingService
from domain import Problem
from mail import content


class MailWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "EMAIL_ENABLED": "true",
                "EMAIL_TEST_RECIPIENTS": "batemapf@gmail.com",
                "SITE_ORIGIN": "https://test.invalid",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = MemoryStore(shift(capacity=2), shift("two", capacity=1))
        self.service = BookingService(self.store, clock=lambda: NOW)
        self.raw = selection()
        self.booked = self.service.book("batemapf@gmail.com", self.raw)

    def change(self, **values):
        return self.service.change(
            self.booked["bookingId"],
            self.raw["manageToken"],
            {
                "requestId": "a" * 20,
                "revision": 0,
                "shiftId": "two",
                "start": 10,
                "end": 12,
                **values,
            },
        )

    def test_book_change_cancel_outbox_and_read_only_links(self):
        mail = self.store.get("MAIL#" + self.booked["notificationId"])
        self.assertEqual(mail["status"], "pending")
        subject, body = content(mail)
        self.assertIn("Signup confirmed", subject)
        self.assertIn("manage.html#booking=", body)
        self.assertIn(self.raw["manageToken"], body)
        snapshot = copy.deepcopy(self.store.rows)
        self.service.managed(self.booked["bookingId"], self.raw["manageToken"])
        self.assertEqual(self.store.rows, snapshot)
        self.change()
        self.change()  # Safe retry: no extra outbox or roster changes.
        self.assertEqual(self.store.get("SHIFT#one")["roster"], [])
        self.assertEqual(len(self.store.get("SHIFT#two")["roster"]), 1)
        self.assertEqual(
            self.service.managed(self.booked["bookingId"], self.raw["manageToken"])[
                "revision"
            ],
            1,
        )
        self.service.cancel(self.booked["bookingId"], self.raw["manageToken"])
        self.service.cancel(self.booked["bookingId"], self.raw["manageToken"])
        self.assertEqual(self.store.get("SHIFT#two")["roster"], [])
        mail = [
            v for v in self.store.rows.values() if v.get("recordType") == "mailPending"
        ]
        self.assertCountEqual(
            [m["kind"] for m in mail], ["confirmation", "changed", "cancellation"]
        )
        with self.assertRaises(Problem):
            self.change(requestId="b" * 20, revision=1)

    def test_full_destination_preserves_original_and_sends_nothing(self):
        self.service.book("someone@example.com", selection("two"))
        with self.assertRaises(Problem) as error:
            self.change(start=9, end=11)
        self.assertEqual(error.exception.code, "full")
        self.assertEqual(len(self.store.get("SHIFT#one")["roster"]), 1)
        self.assertEqual(
            self.store.get("BOOKING#" + self.booked["bookingId"])["revision"], 0
        )
        self.assertEqual(
            len(
                [
                    v
                    for v in self.store.rows.values()
                    if v.get("recordType") == "mailPending"
                ]
            ),
            1,
        )

    def test_wrong_token_and_stale_revision(self):
        with self.assertRaises(Problem):
            self.service.change(
                self.booked["bookingId"], "x" * 43, {"requestId": "a" * 20}
            )
        self.change(shiftId="one", start=11, end=13)
        with self.assertRaises(Problem) as error:
            self.change(requestId="b" * 20)
        self.assertEqual(error.exception.code, "stale")

    def test_other_addresses_never_queue_and_old_disabled_stays_disabled(self):
        result = self.service.book("other@example.com", selection())
        row = self.store.get("MAIL#" + result["notificationId"])
        self.assertEqual(row["status"], "disabled")
        self.assertNotIn("recordType", row)
        self.assertNotIn("manageToken", row)
