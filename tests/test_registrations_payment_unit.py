from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fastapi import HTTPException

from app.services import registrations as registration_service
from app.utils.datetime import to_utc_naive, utc_now


class RegistrationPaymentValidationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.registration_id = str(ObjectId())
    @patch.object(registration_service, "get_registrations_collection")
    async def test_approve_allows_zero_payment(self, mock_get_collection) -> None:
        collection = AsyncMock()
        mock_get_collection.return_value = collection
        collection.find_one = AsyncMock(
            side_effect=[
                {
                    "_id": ObjectId(self.registration_id),
                    "status": "pending",
                    "billing_period": "monthly",
                },
                {
                    "_id": ObjectId(self.registration_id),
                    "status": "approved",
                    "billing_period": "monthly",
                    "payment_amount_cup": 0,
                },
            ]
        )
        collection.update_one = AsyncMock()
        ends_at = to_utc_naive(utc_now()) + timedelta(days=30)

        with patch.object(
            registration_service,
            "_registration_to_public",
            new_callable=AsyncMock,
            return_value={"id": self.registration_id, "payment_amount_cup": 0},
        ):
            result = await registration_service.approve_registration(self.registration_id, ends_at, 0)

        self.assertEqual(result["payment_amount_cup"], 0)
        update_payload = collection.update_one.await_args.args[1]["$set"]
        self.assertEqual(update_payload["payment_amount_cup"], 0)

    @patch.object(registration_service, "get_registrations_collection")
    async def test_approve_rejects_negative_payment(self, mock_get_collection) -> None:
        collection = AsyncMock()
        mock_get_collection.return_value = collection
        collection.find_one = AsyncMock(
            return_value={
                "_id": ObjectId(self.registration_id),
                "status": "pending",
                "billing_period": "monthly",
            }
        )
        ends_at = to_utc_naive(utc_now()) + timedelta(days=30)

        with self.assertRaises(HTTPException) as ctx:
            await registration_service.approve_registration(self.registration_id, ends_at, -1)

        self.assertEqual(ctx.exception.status_code, 400)
        collection.update_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
