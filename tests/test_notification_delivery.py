"""External notification delivery remains minimal, safe and idempotent."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

from founderos_atlas.notification_delivery import (
    CallbackProvider,
    DeliveryOutbox,
    SignedWebhookProvider,
    STATUS_DELIVERED,
    STATUS_FAILED,
    STATUS_RETRY,
)


UTC = timezone.utc


class NotificationDeliveryTests(unittest.TestCase):
    def test_independent_handles_share_a_lock_and_preserve_parallel_enqueues(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = DeliveryOutbox(tmp)
            second = DeliveryOutbox(tmp)
            self.assertIs(first._lock, second._lock)
            barrier = threading.Barrier(3)

            def enqueue(outbox, index: int) -> None:
                barrier.wait()
                outbox.enqueue(
                    action_id=f"note:{index}",
                    provider="email",
                    destination_ref="provider-ref:oncall",
                    title=f"Action {index}",
                    priority="medium",
                    href=f"/inbox?action={index}",
                )

            threads = [
                threading.Thread(target=enqueue, args=(first, 1)),
                threading.Thread(target=enqueue, args=(second, 2)),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=5)
            self.assertEqual(
                {"note:1", "note:2"},
                {item.action_id for item in first._read()},
            )

    def test_outbox_is_idempotent_and_persists_no_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outbox = DeliveryOutbox(tmp)
            created = outbox.enqueue(
                action_id="note:1",
                provider="webhook",
                destination_ref="provider-ref:primary",
                title="BGP session down",
                priority="high",
                href="/inbox?action=note%3A1",
            )
            self.assertIsNotNone(created)
            self.assertIsNone(outbox.enqueue(
                action_id="note:1",
                provider="webhook",
                destination_ref="provider-ref:primary",
                title="BGP session down",
                priority="high",
                href="/inbox?action=note%3A1",
            ))
            raw = outbox.path.read_text(encoding="utf-8")
            self.assertNotIn("password", raw.casefold())
            self.assertNotIn("token", raw.casefold())

    def test_webhook_is_signed_and_payload_is_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sent = []
            provider = SignedWebhookProvider(
                lambda body, headers: sent.append((body, headers)),
                signing_secret="super-secret-signing-value",
            )
            outbox = DeliveryOutbox(tmp)
            outbox.enqueue(
                action_id="note:1",
                provider="webhook",
                destination_ref="provider-ref:primary",
                title="Discovery failed",
                priority="high",
                href="/discovery?job=abc",
                scope_id="delhi",
            )
            result = outbox.dispatch({"webhook": provider})
            self.assertEqual(1, result["delivered"])
            payload = json.loads(sent[0][0])
            self.assertEqual(
                {"action_id", "title", "priority", "href", "scope_id"},
                set(payload),
            )
            self.assertIn("X-Atlas-Signature-SHA256", sent[0][1])
            self.assertNotIn("super-secret", outbox.path.read_text("utf-8"))

    def test_failure_retries_with_bounded_backoff_then_stops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 7, 26, 10, 0, tzinfo=UTC)
            outbox = DeliveryOutbox(tmp)
            outbox.enqueue(
                action_id="note:1",
                provider="email",
                destination_ref="provider-ref:oncall",
                title="Policy regression",
                priority="medium",
                href="/policy?finding=one",
                created_at=now,
            )
            provider = CallbackProvider(
                "email",
                lambda payload: (_ for _ in ()).throw(
                    RuntimeError("smtp password=leak")
                ),
            )
            first = outbox.dispatch({"email": provider}, now=now, max_attempts=2)
            self.assertEqual(1, first["retry"])
            self.assertEqual(STATUS_RETRY, outbox._read()[0].status)
            later = now + timedelta(minutes=2)
            second = outbox.dispatch(
                {"email": provider}, now=later, max_attempts=2
            )
            self.assertEqual(1, second["failed"])
            item = outbox._read()[0]
            self.assertEqual(STATUS_FAILED, item.status)
            self.assertNotIn("leak", item.last_error)
            self.assertNotIn("smtp password", outbox.path.read_text("utf-8"))

    def test_unsafe_external_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outbox = DeliveryOutbox(tmp)
            with self.assertRaisesRegex(ValueError, "application-relative"):
                outbox.enqueue(
                    action_id="note:1",
                    provider="email",
                    destination_ref="oncall",
                    title="Unsafe",
                    priority="high",
                    href="https://attacker.example/",
                )


if __name__ == "__main__":
    unittest.main()
