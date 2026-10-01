"""MongoDB session store for demonstration sessions.

Moves and analyses are embedded in the session document. Navigation never
mutates the session: only new moves do, and a new move played after going back
truncates the discarded future variation (the caller computes the effective
move line). Timestamps are stored as ISO 8601 UTC strings.
"""

import logging
from datetime import UTC, datetime
from functools import lru_cache

import chess
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError

from backend.app.services.mongo import MongoConnection, get_mongo


logger = logging.getLogger("backend.sessions")

SESSIONS_COLLECTION = "sessions"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def format_pgn(sans: list[str]) -> str:
    parts: list[str] = []
    for index, san in enumerate(sans):
        if index % 2 == 0:
            parts.append(f"{index // 2 + 1}. {san}")
        else:
            parts[-1] = f"{parts[-1]} {san}"
    return " ".join(parts)


def build_move_docs(moves: list[str]) -> list[dict] | None:
    """Build session move documents from a UCI move line.

    Returns None when the line cannot be replayed legally: the session line
    is then left untouched rather than persisted in a broken state.
    """
    board = chess.Board()
    sans: list[str] = []
    documents: list[dict] = []
    for ply, uci in enumerate(moves, start=1):
        try:
            move = chess.Move.from_uci(uci.lower())
            san = board.san(move)
            board.push(move)
        except (ValueError, AssertionError):
            return None
        sans.append(san)
        documents.append(
            {
                "ply": ply,
                "uci": uci.lower(),
                "san": san,
                "fen": board.fen(),
                "pgn": format_pgn(sans),
                "created_at": now_iso(),
            }
        )
    return documents


class SessionStore:
    def __init__(self, database: object) -> None:
        self._sessions = None if database is None else database[SESSIONS_COLLECTION]
        if self._sessions is not None:
            self._sessions.create_index("started_at")

    def available(self) -> bool:
        return self._sessions is not None

    def create_session(self) -> dict | None:
        if not self.available():
            return None
        document = {
            "started_at": now_iso(),
            "ended_at": None,
            "status": "active",
            "moves": [],
            "analyses": [],
        }
        try:
            result = self._sessions.insert_one(dict(document))
        except (PyMongoError, TypeError, ValueError) as exc:
            logger.warning("Session creation failed (%s)", exc)
            return None
        return self.get_session(str(result.inserted_id))

    def get_session(self, session_id: str) -> dict | None:
        if not self.available():
            return None
        try:
            document_id = ObjectId(session_id)
            document = self._sessions.find_one({"_id": document_id})
        except (InvalidId, TypeError, ValueError, PyMongoError) as exc:
            logger.warning("Session lookup failed for %s (%s)", session_id, exc)
            return None
        return _serialize(document) if document else None

    def set_moves(self, session_id: str, moves: list[dict]) -> bool:
        return self._update(session_id, {"$set": {"moves": moves}})

    def append_move(self, session_id: str, move: dict) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        return self.set_moves(session_id, [*session["moves"], move])

    def save_analysis(
        self,
        session_id: str,
        position_key: str,
        fen: str,
        response: dict,
    ) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        record = {
            "position_key": position_key,
            "fen": fen,
            "response": response,
            "created_at": now_iso(),
        }
        analyses = [
            analysis
            for analysis in session["analyses"]
            if analysis["position_key"] != position_key
        ]
        analyses.append(record)
        return self._update(session_id, {"$set": {"analyses": analyses}})

    def end_session(self, session_id: str) -> bool:
        return self._update(session_id, {"$set": {"ended_at": now_iso(), "status": "ended"}})

    def _update(self, session_id: str, update: dict) -> bool:
        if not self.available():
            return False
        try:
            document_id = ObjectId(session_id)
            result = self._sessions.update_one({"_id": document_id}, update)
        except (InvalidId, TypeError, ValueError, PyMongoError) as exc:
            logger.warning("Session update failed for %s (%s)", session_id, exc)
            return False
        return bool(getattr(result, "matched_count", 0))


def _serialize(document: dict) -> dict:
    return {
        "id": str(document["_id"]),
        "started_at": document.get("started_at"),
        "ended_at": document.get("ended_at"),
        "status": document.get("status", "active"),
        "moves": list(document.get("moves", [])),
        "analyses": list(document.get("analyses", [])),
    }


@lru_cache
def get_session_store() -> SessionStore:
    mongo: MongoConnection = get_mongo()
    return SessionStore(database=mongo.database())
