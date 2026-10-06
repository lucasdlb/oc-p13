"""MongoDB persistence for progressive analysis runs."""

import logging
from datetime import UTC, datetime
from functools import lru_cache
from uuid import uuid4

from pymongo.errors import PyMongoError

from backend.app.models.analysis import AnalysisRun, FamilyStatus
from backend.app.services.mongo import MongoConnection, get_mongo


logger = logging.getLogger("backend.analysis_runs")
RUNS_COLLECTION = "analysis_runs"
SESSION_FINGERPRINT_INDEX = "analysis_runs_session_fingerprint_unique"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class RunStore:
    """Store each run separately so family updates are atomic."""

    def __init__(self, database: object) -> None:
        self._runs = None if database is None else database[RUNS_COLLECTION]
        if self._runs is not None:
            self._runs.create_index("run_id", unique=True)
            self._runs.create_index(
                [("session_id", 1), ("request_fingerprint", 1)],
                unique=True,
                name=SESSION_FINGERPRINT_INDEX,
            )

    def available(self) -> bool:
        return self._runs is not None

    def create_run(self, run: AnalysisRun) -> AnalysisRun | None:
        if not self.available():
            return None
        document = run.model_dump()
        try:
            self._runs.insert_one(document)
        except (PyMongoError, TypeError, ValueError) as exc:
            logger.warning("Analysis run creation failed (%s)", exc)
            return self.get_by_fingerprint(run.session_id, run.request_fingerprint)
        return self.get_run(run.run_id)

    def get_run(self, run_id: str) -> AnalysisRun | None:
        if not self.available():
            return None
        try:
            document = self._runs.find_one({"run_id": run_id})
        except (PyMongoError, TypeError, ValueError) as exc:
            logger.warning("Analysis run lookup failed for %s (%s)", run_id, exc)
            return None
        if document is None:
            return None
        try:
            return AnalysisRun.model_validate(document)
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid analysis run %s (%s)", run_id, exc)
            return None

    def get_by_fingerprint(
        self,
        session_id: str | None,
        request_fingerprint: str,
    ) -> AnalysisRun | None:
        if not self.available():
            return None
        try:
            document = self._runs.find_one(
                {"session_id": session_id, "request_fingerprint": request_fingerprint}
            )
        except (PyMongoError, TypeError, ValueError) as exc:
            logger.warning("Analysis run fingerprint lookup failed (%s)", exc)
            return None
        if document is None:
            return None
        try:
            return AnalysisRun.model_validate(document)
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid fingerprinted analysis run (%s)", exc)
            return None

    def update(self, run_id: str, fields: dict) -> bool:
        return self._update_where({"run_id": run_id}, fields)

    def _update_where(self, query: dict, fields: dict) -> bool:
        if not self.available():
            return False
        fields = {**fields, "updated_at": now_iso()}
        try:
            result = self._runs.update_one(query, {"$set": fields})
        except (PyMongoError, TypeError, ValueError) as exc:
            logger.warning("Analysis run update failed for %s (%s)", query, exc)
            return False
        return bool(getattr(result, "matched_count", 0))

    def claim_family(self, run_id: str, family: str) -> bool:
        """Atomically transition a pending family to running."""
        if family not in {"explorer", "stockfish", "rag", "coach"}:
            raise ValueError(f"Unsupported run family: {family}")
        if not self.available():
            return False
        status_field = f"{family}_status"
        try:
            result = self._runs.update_one(
                {"run_id": run_id, status_field: "pending"},
                {"$set": {status_field: "running", "updated_at": now_iso()}},
            )
        except (PyMongoError, TypeError, ValueError) as exc:
            logger.warning("Analysis run claim failed for %s (%s)", run_id, exc)
            return False
        return bool(getattr(result, "matched_count", 0))

    def set_family_status(self, run_id: str, family: str, status: FamilyStatus) -> bool:
        if family not in {"explorer", "stockfish", "rag", "coach"}:
            raise ValueError(f"Unsupported run family: {family}")
        return self.update(run_id, {f"{family}_status": status})

    def save_explorer_facts(self, run_id: str, facts: dict) -> bool:
        return self.update(run_id, {"explorer_facts": facts, "explorer_status": "generated"})

    def save_stockfish_result(
        self,
        run_id: str,
        result: dict | None,
        status: FamilyStatus,
        fallbacks: list[str] | None = None,
    ) -> bool:
        fields = {"stockfish_result": result, "stockfish_status": status}
        if fallbacks is not None:
            fields["stockfish_fallbacks"] = fallbacks
        return self.update(run_id, fields)

    def save_rag_context(
        self,
        run_id: str,
        context: list[dict],
        tree_context: dict,
        retrieved_contexts: list[dict],
        status: FamilyStatus,
        fallbacks: list[str],
        coach_context: dict | None = None,
    ) -> bool:
        fields = {
            "rag_context": context,
            "rag_tree_context": tree_context,
            "rag_retrieved_contexts": retrieved_contexts,
            "rag_status": status,
            "rag_fallbacks": fallbacks,
        }
        if coach_context is not None:
            fields["coach_context_artifact"] = coach_context
        return self.update(
            run_id,
            fields,
        )

    def save_coach_result(
        self,
        run_id: str,
        explanation: str,
        status: FamilyStatus,
        fallbacks: list[str],
    ) -> bool:
        return self._update_where(
            {"run_id": run_id, "coach_status": "running"},
            {
                "coach_result": {
                    "explanation": explanation,
                    "fallbacks_used": fallbacks,
                },
                "coach_status": status,
            },
        )

    def reset_coach(self, run_id: str) -> bool:
        return self.update(run_id, {"coach_status": "pending"})


def new_run_id() -> str:
    return uuid4().hex


@lru_cache
def get_run_store() -> RunStore:
    mongo: MongoConnection = get_mongo()
    return RunStore(database=mongo.database())
