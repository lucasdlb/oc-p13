"""MongoDB cache store for Lichess, Masters, Stockfish and videos responses.

Only successful responses are written by the callers: Lichess seed fallbacks and
Stockfish `unavailable` results are never cached. TTL indexes purge expired
documents automatically (mongod TTL monitor, ~60s cadence). Masters responses
share the `lichess_cache` collection with a distinct key prefix.
"""

import logging
from datetime import UTC, datetime
from functools import lru_cache

import chess
from pymongo.errors import PyMongoError

from backend.app.core.settings import MongoSettings, get_settings
from backend.app.services.mongo import MongoConnection, get_mongo


logger = logging.getLogger("backend.cache")

LICHESS_COLLECTION = "lichess_cache"
STOCKFISH_COLLECTION = "stockfish_cache"
VIDEOS_COLLECTION = "videos_cache"


def lichess_cache_key(moves: list[str], ratings: list[int]) -> str:
    normalized = ",".join(move.lower() for move in moves)
    buckets = ",".join(str(rating) for rating in ratings)
    return f"explorer|standard|{normalized}|{buckets}"


def masters_cache_key(moves: list[str]) -> str:
    normalized = ",".join(move.lower() for move in moves)
    return f"masters|{normalized}"


def stockfish_cache_key(fen: str, depth: int, engine_version: str, multipv: int = 1) -> str:
    epd = chess.Board(fen).epd()
    return f"stockfish|{epd}|d{depth}|mpv{multipv}|{engine_version}"


def videos_cache_key(query: str) -> str:
    normalized = " ".join(query.lower().split())
    return f"videos|{normalized}"


class CacheStore:
    def __init__(self, database: object, settings: MongoSettings | None = None) -> None:
        self.settings = settings or get_settings().mongodb
        self._collections: dict[str, object] | None = None
        if database is None:
            return

        self._collections = {
            LICHESS_COLLECTION: database[LICHESS_COLLECTION],
            STOCKFISH_COLLECTION: database[STOCKFISH_COLLECTION],
            VIDEOS_COLLECTION: database[VIDEOS_COLLECTION],
        }
        self._collections[LICHESS_COLLECTION].create_index("key", unique=True)
        self._collections[LICHESS_COLLECTION].create_index(
            "cached_at", expireAfterSeconds=self.settings.lichess_cache_ttl_seconds
        )
        self._collections[STOCKFISH_COLLECTION].create_index("key", unique=True)
        self._collections[VIDEOS_COLLECTION].create_index("key", unique=True)
        self._collections[VIDEOS_COLLECTION].create_index(
            "cached_at", expireAfterSeconds=self.settings.videos_cache_ttl_seconds
        )

    def available(self) -> bool:
        return self._collections is not None

    def _get(self, collection: str, key: str):
        if not self.available():
            return None
        try:
            document = self._collections[collection].find_one({"key": key})
        except (PyMongoError, KeyError):
            logger.warning("Cache read failed for %s key=%s", collection, key)
            return None
        if not document or "payload" not in document:
            return None
        return document["payload"]

    def _set(self, collection: str, key: str, payload: object) -> None:
        if not self.available():
            return
        try:
            self._collections[collection].update_one(
                {"key": key},
                {"$set": {"payload": payload, "cached_at": datetime.now(UTC)}},
                upsert=True,
            )
        except (PyMongoError, KeyError):
            logger.warning("Cache write failed for %s key=%s", collection, key)

    def get_lichess(self, key: str):
        return self._get(LICHESS_COLLECTION, key)

    def set_lichess(self, key: str, payload: dict) -> None:
        self._set(LICHESS_COLLECTION, key, payload)

    def get_masters(self, key: str):
        return self._get(LICHESS_COLLECTION, key)

    def set_masters(self, key: str, payload: dict) -> None:
        self._set(LICHESS_COLLECTION, key, payload)

    def get_stockfish(self, key: str):
        return self._get(STOCKFISH_COLLECTION, key)

    def set_stockfish(self, key: str, payload: dict) -> None:
        self._set(STOCKFISH_COLLECTION, key, payload)

    def get_videos(self, key: str):
        return self._get(VIDEOS_COLLECTION, key)

    def set_videos(self, key: str, payload: list) -> None:
        self._set(VIDEOS_COLLECTION, key, payload)


@lru_cache
def get_cache_store() -> CacheStore:
    mongo: MongoConnection = get_mongo()
    return CacheStore(database=mongo.database(), settings=get_settings().mongodb)
