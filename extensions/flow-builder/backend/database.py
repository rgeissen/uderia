"""
Database connection and initialization for Flow Builder.
Uses a separate SQLite database (tda_flows.db) from Uderia core.
"""

import aiosqlite
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Database path - stored in extension's data directory
DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "tda_flows.db"
SCHEMA_PATH = Path(__file__).parent.parent / "schema" / "flows.sql"


async def get_db() -> aiosqlite.Connection:
    """Get a database connection."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db


async def init_database():
    """Initialize the database with schema."""
    logger.info(f"Initializing Flow Builder database at {DB_PATH}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")

    schema_sql = SCHEMA_PATH.read_text()

    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.executescript(schema_sql)
        await db.commit()
        logger.info("Flow Builder database initialized successfully")


async def execute_query(query: str, params: tuple = None) -> list:
    """Execute a SELECT query and return results."""
    async with await get_db() as db:
        cursor = await db.execute(query, params or ())
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def execute_write(query: str, params: tuple = None) -> int:
    """Execute an INSERT/UPDATE/DELETE query and return affected rows."""
    async with await get_db() as db:
        cursor = await db.execute(query, params or ())
        await db.commit()
        return cursor.rowcount


async def execute_insert(query: str, params: tuple = None) -> str:
    """Execute an INSERT query and return the last row ID."""
    async with await get_db() as db:
        cursor = await db.execute(query, params or ())
        await db.commit()
        return cursor.lastrowid


class DatabaseConnection:
    """Context manager for database connections."""

    def __init__(self):
        self.db = None

    async def __aenter__(self) -> aiosqlite.Connection:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(str(DB_PATH))
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA foreign_keys = ON")
        return self.db

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.db:
            await self.db.close()


# Convenience function for use in route handlers
def get_db_connection():
    """Get a database connection context manager."""
    return DatabaseConnection()
