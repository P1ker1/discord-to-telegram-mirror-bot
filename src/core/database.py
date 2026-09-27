import json
import logging
from pathlib import Path
from typing import Optional
import aiosqlite

from src.core.config import config

logger = logging.getLogger(__name__)

class Database:
    """
    Manages SQLite persistence for Discord <-> Telegram message ID correlation.
    Uses parameterized queries throughout (SQL injection safe) and an ephemeral
    connection-per-query pattern suited for low-frequency announcement volume.
    """
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.database_path
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        """Opens a connection with a 10s busy timeout for concurrent access safety."""
        return aiosqlite.connect(self.db_path, timeout=10.0)

    async def init_db(self):
        """Initialize the database schema with rollback journal mode for Docker volume compatibility."""
        async with self._connect() as db:
            # DELETE mode is used instead of WAL to prevent 'disk I/O error' on Docker host bind-mounts
            # (WAL requires POSIX mmap shared memory on .shm files, which virtualized host filesystems do not support).
            try:
                await db.execute("PRAGMA journal_mode=DELETE;")
            except Exception as e:
                logger.warning(f"Could not set journal_mode to DELETE: {e}")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS message_mappings (
                    discord_message_id INTEGER PRIMARY KEY,
                    telegram_chat_id TEXT NOT NULL,
                    telegram_message_ids TEXT NOT NULL,
                    has_media INTEGER NOT NULL DEFAULT 0,
                    followup_message_id INTEGER DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Migration: ensure followup_message_id column exists if table was created in an earlier version
            try:
                await db.execute("ALTER TABLE message_mappings ADD COLUMN followup_message_id INTEGER DEFAULT NULL;")
            except Exception:
                pass

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_mappings_discord_id 
                ON message_mappings(discord_message_id);
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.commit()
        logger.info(f"Database initialized at {self.db_path} (DELETE journal mode)")

    async def save_mapping(
        self,
        discord_msg_id: int,
        telegram_chat_id: str,
        telegram_msg_ids: list[int],
        has_media: bool = False,
        followup_message_id: Optional[int] = None
    ):
        """Save a new mapping between Discord message ID and Telegram message IDs."""
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO message_mappings 
                (discord_message_id, telegram_chat_id, telegram_message_ids, has_media, followup_message_id, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    discord_msg_id,
                    str(telegram_chat_id),
                    json.dumps(telegram_msg_ids),
                    1 if has_media else 0,
                    followup_message_id
                )
            )
            await db.commit()
        logger.debug(f"Saved mapping: Discord {discord_msg_id} -> Telegram {telegram_msg_ids} (followup: {followup_message_id})")

    async def get_mapping(self, discord_msg_id: int) -> Optional[dict]:
        """Fetch Telegram message IDs and info mapped to a Discord message ID."""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM message_mappings WHERE discord_message_id = ?",
                (discord_msg_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                followup_id = row["followup_message_id"] if "followup_message_id" in row.keys() else None
                return {
                    "discord_message_id": row["discord_message_id"],
                    "telegram_chat_id": row["telegram_chat_id"],
                    "telegram_message_ids": json.loads(row["telegram_message_ids"]),
                    "has_media": bool(row["has_media"]),
                    "followup_message_id": followup_id,
                    "created_at": row["created_at"],
                }

    async def delete_mapping(self, discord_msg_id: int) -> Optional[dict]:
        """Delete mapping and return the deleted mapping data if found."""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM message_mappings WHERE discord_message_id = ?",
                (discord_msg_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                followup_id = row["followup_message_id"] if "followup_message_id" in row.keys() else None
                mapping = {
                    "discord_message_id": row["discord_message_id"],
                    "telegram_chat_id": row["telegram_chat_id"],
                    "telegram_message_ids": json.loads(row["telegram_message_ids"]),
                    "has_media": bool(row["has_media"]),
                    "followup_message_id": followup_id,
                    "created_at": row["created_at"],
                }

            await db.execute(
                "DELETE FROM message_mappings WHERE discord_message_id = ?",
                (discord_msg_id,)
            )
            await db.commit()

        logger.debug(f"Deleted mapping for Discord {discord_msg_id}")
        return mapping

    async def delete_mappings_bulk(self, discord_msg_ids: list[int]) -> list[dict]:
        """Delete multiple mappings in a single batch query and return list of deleted records."""
        if not discord_msg_ids:
            return []

        # Safe against SQL injection: generates only '?' placeholders; values are bound as parameters
        placeholders = ",".join("?" for _ in discord_msg_ids)
        deleted = []
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM message_mappings WHERE discord_message_id IN ({placeholders})",
                discord_msg_ids
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    followup_id = row["followup_message_id"] if "followup_message_id" in row.keys() else None
                    deleted.append({
                        "discord_message_id": row["discord_message_id"],
                        "telegram_chat_id": row["telegram_chat_id"],
                        "telegram_message_ids": json.loads(row["telegram_message_ids"]),
                        "has_media": bool(row["has_media"]),
                        "followup_message_id": followup_id,
                        "created_at": row["created_at"],
                    })

            if deleted:
                await db.execute(
                    f"DELETE FROM message_mappings WHERE discord_message_id IN ({placeholders})",
                    discord_msg_ids
                )
                await db.commit()

        logger.debug(f"Bulk deleted {len(deleted)} mappings from database")
        return deleted

    async def get_metadata(self, key: str) -> Optional[str]:
        """Fetch a persistent metadata string value by key."""
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT value FROM bot_metadata WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row["value"] if row else None

    async def set_metadata(self, key: str, value: str):
        """Save or update a persistent metadata key-value pair."""
        async with self._connect() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO bot_metadata (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (key, value)
            )
            await db.commit()
        logger.debug(f"Saved metadata: {key} = {value}")

db = Database()
