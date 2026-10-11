import chess

from backend.app.services.cache_store import (
    CacheStore,
    lichess_cache_key,
    masters_cache_key,
    stockfish_cache_key,
    videos_cache_key,
)
from backend.tests.fakes import FakeDatabase
from backend.tests.settings_factories import mongo_settings


SETTINGS = mongo_settings(
    enabled=True,
    uri="mongodb://localhost:27017",
    database="test",
    connect_timeout_seconds=0.05,
    lichess_cache_ttl_seconds=86400,
    videos_cache_ttl_seconds=604800,
)


def test_lichess_cache_roundtrip() -> None:
    store = CacheStore(database=FakeDatabase(), settings=SETTINGS)

    assert store.get_lichess("explorer|standard|e2e4|1000") is None
    store.set_lichess("explorer|standard|e2e4|1000", {"games": 100})
    assert store.get_lichess("explorer|standard|e2e4|1000") == {"games": 100}
    assert store.get_lichess("explorer|standard|e2e4|1200") is None


def test_masters_results_share_the_lichess_collection_with_distinct_keys() -> None:
    database = FakeDatabase()
    store = CacheStore(database=database, settings=SETTINGS)

    store.set_masters(masters_cache_key(["e2e4"]), {"games": 5})

    assert store.get_masters(masters_cache_key(["e2e4"])) == {"games": 5}
    assert store.get_lichess(lichess_cache_key(["e2e4"], [1000])) is None
    assert store.get_lichess(lichess_cache_key(["e2e4"], [1000, 1200])) is None
    assert "lichess_cache" in database.collections
    assert "masters_cache" not in database.collections


def test_stockfish_cache_roundtrip() -> None:
    store = CacheStore(database=FakeDatabase(), settings=SETTINGS)

    payload = {"status": "ok", "best_move": "g1f3", "depth": 12}
    store.set_stockfish("stockfish|epd|d12|v1", payload)

    assert store.get_stockfish("stockfish|epd|d12|v1") == payload
    assert store.get_stockfish("stockfish|epd|d13|v1") is None


def test_degraded_store_never_raises() -> None:
    store = CacheStore(database=None, settings=SETTINGS)

    assert store.available() is False

    store.set_lichess("key", {"games": 1})
    store.set_stockfish("key", {"status": "ok"})
    store.set_videos("key", [])

    assert store.get_lichess("key") is None
    assert store.get_stockfish("key") is None
    assert store.get_videos("key") is None


def test_ttl_indexes_follow_the_policy() -> None:
    database = FakeDatabase()
    CacheStore(database=database, settings=SETTINGS)

    lichess_indexes = dict(database.collections["lichess_cache"].indexes)
    stockfish_indexes = dict(database.collections["stockfish_cache"].indexes)
    videos_indexes = dict(database.collections["videos_cache"].indexes)

    assert lichess_indexes["cached_at"] == {"expireAfterSeconds": 86400}
    assert lichess_indexes["key"] == {"unique": True}
    assert "cached_at" not in stockfish_indexes
    assert stockfish_indexes["key"] == {"unique": True}
    assert videos_indexes["cached_at"] == {"expireAfterSeconds": 604800}


def test_lichess_cache_key_covers_all_response_parameters() -> None:
    assert (
        lichess_cache_key(["E2e4", "e7e5"], [1000, 1200])
        == "explorer|standard|e2e4,e7e5|1000,1200"
    )
    assert lichess_cache_key(["e2e4"], [1000]) != lichess_cache_key(["e2e4"], [1200])
    assert lichess_cache_key(["e2e4"], [1000]) != lichess_cache_key(["d2d4"], [1000])


def test_masters_cache_key_ignores_ratings() -> None:
    assert masters_cache_key(["E2e4", "e7e5"]) == "masters|e2e4,e7e5"


def test_stockfish_cache_key_normalizes_fen_and_covers_depth_and_version() -> None:
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    epd = chess.Board(fen).epd()

    key = stockfish_cache_key(fen, 12, "Stockfish 17")

    assert key == f"stockfish|{epd}|d12|mpv1|Stockfish 17"
    assert stockfish_cache_key(fen, 13, "Stockfish 17") != key
    assert stockfish_cache_key(fen, 12, "Stockfish 16") != key


def test_videos_cache_key_normalizes_whitespace_and_case() -> None:
    assert videos_cache_key("Ruy   Lopez  chess ") == "videos|ruy lopez chess"
