from __future__ import annotations

import aiosqlite
import json
import time
from typing import Any, Optional


class Cache:
    def __init__(self, path: str = "cache.sqlite3") -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              ts INTEGER NOT NULL
            )
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def get_json(self, key: str) -> Optional[Any]:
        if not self._db:
            raise RuntimeError("Cache not initialized")
        async with self._db.execute("SELECT value FROM cache WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return json.loads(row[0])

    async def set_json(self, key: str, value: Any) -> None:
        if not self._db:
            raise RuntimeError("Cache not initialized")
        payload = json.dumps(value, ensure_ascii=False)
        ts = int(time.time())
        await self._db.execute(
            "INSERT OR REPLACE INTO cache(key, value, ts) VALUES(?, ?, ?)",
            (key, payload, ts),
        )
        await self._db.commit()