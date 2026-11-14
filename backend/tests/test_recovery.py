import os
import unittest
from unittest.mock import patch
from test_booking import MemoryStore, selection, shift, NOW
from service import BookingService
from recovery import recover, contact_hash, RESPONSE
from domain import Problem, token_hash
from mail import content


class RecoveryStore(MemoryStore):
    def __init__(self, *items):
        super().__init__(*items)
        self.rates = {}

    def bookings_for_contact(self, hashed):
        return [
            b
            for b in self.rows.values()
            if b["pk"].startswith("BOOKING#") and b.get("contactHash") == hashed
        ]

    def claim_recovery(self, hashed, ip, now):
        ip_key = "ip:" + ip + ":" + str(now // 60)
        if (
            self.rates.get("email:" + hashed, 0) > now
            or self.rates.get(ip_key, 0) >= 10
        ):
            return False
        self.rates["email:" + hashed] = now + 300
        self.rates[ip_key] = self.rates.get(ip_key, 0) + 1
        return True


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "EMAIL_ENABLED": "true",
                "EMAIL_DELIVERY_MODE": "public",
                "SITE_ORIGIN": "https://volunteer.brentholidaysale.com",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = RecoveryStore(shift(capacity=4), shift("two", capacity=4))
        self.service = BookingService(self.store, clock=lambda: NOW)
        self.one, self.two, self.other = (
            selection(name="Family One"),
            selection("two", name="Family Two"),
            selection(name="Different Household"),
        )
        self.a = self.service.book("family@gmail.com", self.one)
        self.b = self.service.book("family@gmail.com", self.two)
        self.c = self.service.book("other@gmail.com", self.other)

    def request(self, email="family@gmail.com", now=NOW, ip="192.0.2.1"):
        return recover(self.store, email, ip, now)

    def summaries(self):
        return [r for r in self.store.rows.values() if r.get("kind") == "recovery"]

    def test_shared_family_email_lists_each_and_keeps_old_links_valid(self):
        before = self.store.get("BOOKING#" + self.a["bookingId"])["tokenHash"]
        self.assertEqual(self.request(" FAMILY@gmail.com "), RESPONSE)
        row = self.summaries()[0]
        self.assertEqual(len(row["items"]), 2)
        subject, body = content(row)
        self.assertIn("Family One", body)
        self.assertIn("Family Two", body)
        self.assertNotIn("Different Household", body)
        self.assertEqual(
            before, self.store.get("BOOKING#" + self.a["bookingId"])["tokenHash"]
        )
        for booking in (self.a, self.b):
            self.service.managed(booking["bookingId"], row["manageToken"])
        self.service.managed(self.a["bookingId"], self.one["manageToken"])
        with self.assertRaises(Problem):
            self.service.managed(self.c["bookingId"], row["manageToken"])
        self.assertNotIn(
            row["manageToken"],
            str(self.store.get("RECOVERYACCESS#" + token_hash(row["manageToken"]))),
        )

    def test_unknown_and_limited_responses_do_not_disclose_signup_existence(self):
        self.assertEqual(
            self.request(), self.request("unknown@gmail.com", ip="192.0.2.2")
        )
        self.assertEqual(self.request(), RESPONSE)
        self.assertEqual(len(self.summaries()), 1)
        self.assertEqual(self.request(now=NOW + 301), RESPONSE)
        self.assertEqual(len(self.summaries()), 2)

    def test_canceled_and_past_commitments_excluded_and_recovery_token_expires(self):
        self.service.cancel(self.b["bookingId"], self.two["manageToken"])
        self.request()
        row = self.summaries()[0]
        self.assertEqual(len(row["items"]), 1)
        future = BookingService(self.store, clock=lambda: NOW + 86401)
        with self.assertRaises(Problem):
            future.managed(self.a["bookingId"], row["manageToken"])
        future.managed(self.a["bookingId"], self.one["manageToken"])
        self.service.cancel(self.a["bookingId"], row["manageToken"])
        self.assertEqual(
            self.store.get("BOOKING#" + self.a["bookingId"])["status"], "canceled"
        )

    def test_shared_network_allows_different_household_recovery(self):
        self.request()
        self.request("other@gmail.com")
        self.assertEqual(len(self.summaries()), 2)

    def test_booking_scoped_update_link_cannot_manage_other_family_commitment(self):
        import secrets

        token = secrets.token_urlsafe(32)
        self.store.rows["RECOVERYACCESS#" + token_hash(token)] = {
            "contactHash": contact_hash("family@gmail.com"),
            "bookingId": self.a["bookingId"],
            "expiresAt": NOW + 86400,
        }
        self.service.managed(self.a["bookingId"], token)
        with self.assertRaises(Problem):
            self.service.managed(self.b["bookingId"], token)
