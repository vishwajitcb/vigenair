"""MongoDB connection manager for ViGenAiR."""

import asyncio
import logging
import os
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# Global database client and database instance
_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def get_mongodb_uri() -> str:
    """Get MongoDB connection URI from environment."""
    return os.environ.get("MONGODB_URI", "mongodb://localhost:27017")


def get_mongodb_db_name() -> str:
    """Get MongoDB database name from environment."""
    return os.environ.get("MONGODB_DB", "vigenair")


async def init_db() -> AsyncIOMotorDatabase:
    """Initialize MongoDB connection and return database instance."""
    global _client, _database, _main_loop

    if _database is not None:
        return _database

    # Store the main event loop for use by sync wrappers in background threads
    _main_loop = asyncio.get_running_loop()
    logger.info(f"Stored main event loop: {id(_main_loop)}")

    uri = get_mongodb_uri()
    db_name = get_mongodb_db_name()

    logger.info(f"Connecting to MongoDB at {uri}, database: {db_name}")

    _client = AsyncIOMotorClient(uri)
    _database = _client[db_name]

    # Create indexes for the jobs collection
    jobs_collection = _database.jobs

    # Unique index on folder (S3 folder name is the unique identifier)
    await jobs_collection.create_index("folder", unique=True)

    # Index on status for filtering
    await jobs_collection.create_index("status")

    # Index on createdAt for sorting
    await jobs_collection.create_index("createdAt")

    # Index on userId for future multi-user support
    await jobs_collection.create_index("userId")

    # Verify connection
    await _client.admin.command('ping')
    logger.info("MongoDB connection established successfully")

    return _database


async def get_database() -> AsyncIOMotorDatabase:
    """Get the database instance, initializing if needed."""
    global _database

    if _database is None:
        return await init_db()

    return _database


async def close_db():
    """Close the MongoDB connection."""
    global _client, _database, _main_loop

    if _client is not None:
        _client.close()
        _client = None
        _database = None
        _main_loop = None
        logger.info("MongoDB connection closed")


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Get the main event loop for scheduling async operations from sync code.

    This is used by sync wrapper functions that run in background threads
    to schedule async MongoDB operations on the main event loop where the
    motor client was initialized.
    """
    return _main_loop
