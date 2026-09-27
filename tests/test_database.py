import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from src.database import Database

class TestDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = str(Path(self.temp_dir.name) / "test_bot.db")
        self.db = Database(db_path=self.test_db_path)
        await self.db.init_db()

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_save_and_get_mapping(self):
        discord_id = 9876543210
        telegram_chat = "-1001234567890"
        telegram_msg_ids = [101, 102]

        await self.db.save_mapping(
            discord_msg_id=discord_id,
            telegram_chat_id=telegram_chat,
            telegram_msg_ids=telegram_msg_ids,
            has_media=True
        )

        mapping = await self.db.get_mapping(discord_id)
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping["discord_message_id"], discord_id)
        self.assertEqual(mapping["telegram_chat_id"], telegram_chat)
        self.assertEqual(mapping["telegram_message_ids"], telegram_msg_ids)
        self.assertTrue(mapping["has_media"])

    async def test_delete_mapping(self):
        discord_id = 1122334455
        await self.db.save_mapping(
            discord_msg_id=discord_id,
            telegram_chat_id="-100999",
            telegram_msg_ids=[555]
        )

        deleted = await self.db.delete_mapping(discord_id)
        self.assertIsNotNone(deleted)
        self.assertEqual(deleted["telegram_message_ids"], [555])

        # Check that it's no longer in the database
        lookup = await self.db.get_mapping(discord_id)
        self.assertIsNone(lookup)

    async def test_delete_mappings_bulk(self):
        ids = [1001, 1002, 1003]
        for msg_id in ids:
            await self.db.save_mapping(
                discord_msg_id=msg_id,
                telegram_chat_id="-100123",
                telegram_msg_ids=[msg_id + 1000]
            )

        deleted_list = await self.db.delete_mappings_bulk(ids)
        self.assertEqual(len(deleted_list), 3)

        for msg_id in ids:
            self.assertIsNone(await self.db.get_mapping(msg_id))

    async def test_metadata_crud(self):
        # Non-existent key returns None
        self.assertIsNone(await self.db.get_metadata("non_existent_key"))

        # Save metadata
        await self.db.set_metadata("last_weekly_digest_week", "2026-W39")
        val = await self.db.get_metadata("last_weekly_digest_week")
        self.assertEqual(val, "2026-W39")

        # Overwrite metadata
        await self.db.set_metadata("last_weekly_digest_week", "2026-W40")
        val2 = await self.db.get_metadata("last_weekly_digest_week")
        self.assertEqual(val2, "2026-W40")

if __name__ == "__main__":
    unittest.main()
