"""Initialize the database — create all tables."""

import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.monitor.logger import setup_logging
from src.storage.database import init_db

import structlog

logger = structlog.get_logger()


async def main() -> None:
    setup_logging()
    logger.info("initializing_database")
    await init_db()
    logger.info("database_initialized")


if __name__ == "__main__":
    asyncio.run(main())
