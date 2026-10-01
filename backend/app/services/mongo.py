"""MongoDB connection with graceful degradation.

If MongoDB is disabled or unavailable, cache reads become misses, cache writes
are skipped, and sessions are not persisted. The analysis flow never fails
because of MongoDB.
"""

import logging
from functools import lru_cache

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from backend.app.core.settings import MongoSettings, get_settings


logger = logging.getLogger("backend.mongo")


class MongoConnection:
    """Holds a single MongoClient and reports availability via `ok`.

    The connection is attempted once at construction. If MongoDB is down at
    that moment, the connection stays degraded until the process restarts.
    """

    def __init__(self, settings: MongoSettings) -> None:
        self.settings = settings
        self.ok = False
        self._client: MongoClient | None = None

        if not settings.enabled:
            logger.info("MongoDB is disabled in config.toml: cache and sessions are off")
            return

        timeout_ms = int(settings.connect_timeout_seconds * 1000)
        try:
            client = MongoClient(
                settings.uri,
                serverSelectionTimeoutMS=timeout_ms,
                connectTimeoutMS=timeout_ms,
            )
            client.admin.command("ping")
        except PyMongoError as exc:
            logger.warning(
                "MongoDB unavailable (%s): cache and sessions degrade to no-op", exc
            )
            return

        self._client = client
        self.ok = True

    def database(self, name: str | None = None):
        """Return the database handle, or None when degraded."""
        if not self.ok or self._client is None:
            return None
        return self._client[name or self.settings.database]

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self.ok = False


@lru_cache
def get_mongo() -> MongoConnection:
    return MongoConnection(get_settings().mongodb)
