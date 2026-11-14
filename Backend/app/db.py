import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import psycopg
from fastapi import HTTPException
from psycopg import errors as pgerr
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings
log = logging.getLogger("medicitas.db")

pool: AsyncConnectionPool | None = None

async def open_pool() -> None:
    global pool
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=2,
        max_size=int(__import__("os").environ.get("DB_POOL_MAX", "20")),
        kwargs={"row_factory": dict_row, "autocommit": True},
        open=False,
    )
    await pool.open(wait=True, timeout=30)


async def close_pool() -> None:
    if pool is not None:
        await pool.close()