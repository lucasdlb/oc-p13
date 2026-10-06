"""Application-facing RAG retrieval seam.

`RagService` executes deterministic `RetrievalPlan` buckets against the vector
store. It stays imperative and dependency-injected so tests can use fake
embedding and store seams; LangGraph and API wiring happen outside this module.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import logging
import time
from typing import Protocol, TypedDict

from backend.app.models.knowledge import ScoredChunk
from backend.app.services.embeddings import EmbeddingProvider, EmbeddingProviderError
from backend.app.services.milvus import MilvusMetadataFilter, MilvusStore, MilvusStoreError
from backend.app.services.retrieval_contracts import RetrievedContext, RetrievalBucket, RetrievalPlan


logger = logging.getLogger("backend.rag")


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


@dataclass(frozen=True)
class RagRetrievalResult:
    contexts: tuple[RetrievedContext, ...]
    fallback_reasons: tuple[str, ...] = ()
    reranking_diagnostics: tuple["RerankingDiagnostic", ...] = ()

    def to_artifact(self) -> dict:
        return {
            "contexts": [context.to_artifact() for context in self.contexts],
            "fallback_reasons": list(self.fallback_reasons),
            "reranking_diagnostics": [
                dict(diagnostic) for diagnostic in self.reranking_diagnostics
            ],
        }


class RerankingDiagnostic(TypedDict):
    chunk_id: str
    bucket: str
    original_score: float
    reranked_score: float
    decision: str
    reason_codes: list[str]


@dataclass(frozen=True)
class _Candidate:
    context: RetrievedContext
    bucket: RetrievalBucket
    original_score: float
    reranked_score: float
    reason_codes: tuple[str, ...]
    original_index: int


class RagStore(Protocol):
    def search(
        self,
        vector: Sequence[float],
        k: int,
        *,
        eco_code: str | None = None,
        metadata_filter: MilvusMetadataFilter | None = None,
        min_score: float | None = None,
    ) -> list[ScoredChunk]: ...


class RagService:
    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        store: RagStore | MilvusStore,
        min_score: float | None = None,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._store = store
        self._min_score = min_score

    def warmup(self) -> None:
        """Load the embedding model before the first user retrieval."""
        self._embedding_provider.embed_query("retrieval warmup")

    def close(self) -> None:
        """Release resources owned by the embedding provider."""
        self._embedding_provider.close()

    def retrieve(self, plan: RetrievalPlan, query: str) -> RagRetrievalResult:
        if not plan.buckets:
            return RagRetrievalResult(contexts=())

        started = time.perf_counter()
        embedding_started = started
        try:
            vector = self._embedding_provider.embed_query(_query_text(query, plan))
        except EmbeddingProviderError:
            logger.info(
                "RAG retrieval timing",
                extra={
                    "status": "embedding_unavailable",
                    "embedding_ms": _elapsed_ms(embedding_started),
                    "milvus_search_ms": 0.0,
                    "rerank_ms": 0.0,
                    "total_ms": _elapsed_ms(started),
                },
            )
            return RagRetrievalResult(contexts=(), fallback_reasons=("rag_embedding_unavailable",))

        candidates: list[_Candidate] = []
        diagnostics: list[RerankingDiagnostic] = []
        search_started = time.perf_counter()
        try:
            for bucket in plan.buckets:
                for scored in self._search_bucket(vector, bucket, plan):
                    decision = _score_candidate(scored, bucket, plan)
                    if decision.excluded:
                        diagnostics.append(_diagnostic(scored, bucket, decision, "excluded"))
                        continue
                    candidates.append(
                        _Candidate(
                            context=_to_retrieved_context(scored, bucket),
                            bucket=bucket,
                            original_score=scored.score,
                            reranked_score=decision.score,
                            reason_codes=decision.reason_codes,
                            original_index=len(candidates),
                        )
                    )
        except MilvusStoreError:
            logger.info(
                "RAG retrieval timing",
                extra={
                    "status": "store_unavailable",
                    "embedding_ms": _elapsed_ms(embedding_started),
                    "milvus_search_ms": _elapsed_ms(search_started),
                    "rerank_ms": 0.0,
                    "total_ms": _elapsed_ms(started),
                },
            )
            return RagRetrievalResult(contexts=(), fallback_reasons=("rag_store_unavailable",))

        rerank_started = time.perf_counter()
        contexts, kept_diagnostics = _deduplicate_and_rank(candidates)
        diagnostics.extend(kept_diagnostics)
        logger.info(
            "RAG retrieval timing",
            extra={
                "status": "success",
                "embedding_ms": _elapsed_ms(embedding_started),
                "milvus_search_ms": _elapsed_ms(search_started),
                "rerank_ms": _elapsed_ms(rerank_started),
                "total_ms": _elapsed_ms(started),
                "bucket_count": len(plan.buckets),
                "candidate_count": len(candidates),
                "context_count": len(contexts),
            },
        )
        return RagRetrievalResult(contexts=contexts, reranking_diagnostics=tuple(diagnostics))

    def _search_bucket(
        self,
        vector: Sequence[float],
        bucket: RetrievalBucket,
        plan: RetrievalPlan,
    ) -> list[ScoredChunk]:
        if bucket.limit <= 0:
            return []
        results = self._store.search(
            vector,
            bucket.limit,
            metadata_filter=_metadata_filter(bucket),
            min_score=self._min_score,
        )
        if results or not bucket.eco_code or not bucket.node_ids:
            return results

        # Current demo corpus can be ECO-mapped before full opening-node mapping.
        # Keep node filtering as the primary path, then degrade to the same bucket
        # policy scoped by ECO so the API can still return attributed prose.
        eco_results = self._store.search(
            vector,
            bucket.limit,
            eco_code=bucket.eco_code,
            metadata_filter=_metadata_filter_without_node_ids(bucket),
            min_score=self._min_score,
        )
        if eco_results:
            return eco_results

        return self._store.search(
            vector,
            bucket.limit,
            eco_code=bucket.eco_code,
            metadata_filter=MilvusMetadataFilter(),
            min_score=self._min_score,
        )


def _query_text(query: str, plan: RetrievalPlan) -> str:
    stripped = query.strip()
    if stripped:
        return stripped
    hints = [bucket.query_hint for bucket in plan.buckets if bucket.query_hint]
    if hints:
        return " ".join(hints)
    return plan.intent.replace("_", " ")


def _metadata_filter(bucket: RetrievalBucket) -> MilvusMetadataFilter:
    if bucket.include_history:
        return MilvusMetadataFilter(
            opening_node_ids=bucket.node_ids,
            page_id=bucket.page_ids,
            intent_in=("history",),
            is_history=True,
        )
    if bucket.include_misc:
        return MilvusMetadataFilter(opening_node_ids=bucket.node_ids, page_id=bucket.page_ids)
    return MilvusMetadataFilter(
        opening_node_ids=bucket.node_ids,
        page_id=bucket.page_ids,
        intent_not_in=("history", "misc"),
        is_history=False,
        is_misc=False,
    )


def _metadata_filter_without_node_ids(bucket: RetrievalBucket) -> MilvusMetadataFilter:
    if bucket.include_history:
        return MilvusMetadataFilter(
            page_id=bucket.page_ids,
            intent_in=("history",),
            is_history=True,
        )
    if bucket.include_misc:
        return MilvusMetadataFilter(page_id=bucket.page_ids)
    return MilvusMetadataFilter(
        page_id=bucket.page_ids,
        intent_not_in=("history", "misc"),
        is_history=False,
        is_misc=False,
    )


@dataclass(frozen=True)
class _ScoreDecision:
    score: float
    excluded: bool
    reason_codes: tuple[str, ...]


def _score_candidate(
    scored: ScoredChunk,
    bucket: RetrievalBucket,
    plan: RetrievalPlan,
) -> _ScoreDecision:
    score = scored.score
    reason_codes: list[str] = []

    exclusion_reason = _exclusion_reason(scored, bucket, plan)
    if exclusion_reason:
        return _ScoreDecision(score=score, excluded=True, reason_codes=(exclusion_reason,))

    chunk = scored.chunk
    if chunk.is_history or chunk.intent == "history":
        if not bucket.include_history and plan.intent != "ask_history":
            return _ScoreDecision(score=score, excluded=True, reason_codes=("history_suppressed",))
        reason_codes.append("history_requested")

    if chunk.is_misc or chunk.intent == "misc":
        if _allow_unmapped_eco_fallback(scored, bucket):
            reason_codes.append("raw_eco_misc_allowed")
        elif not bucket.include_misc:
            return _ScoreDecision(score=score, excluded=True, reason_codes=("misc_suppressed",))
        reason_codes.append("misc_requested")

    if bucket.relation_to_position == "current":
        score += 0.40
        reason_codes.append("boost_current")
    elif bucket.relation_to_position == "child" and plan.intent == "ask_specific_candidate":
        score += 0.25
        reason_codes.append("boost_specific_child")
    elif bucket.relation_to_position == "child" and plan.intent == "explain_current_position":
        score -= 0.20
        reason_codes.append("penalize_child_for_current_explanation")
    elif bucket.relation_to_position == "parent":
        score -= 0.25
        reason_codes.append("penalize_parent")

    return _ScoreDecision(score=round(score, 6), excluded=False, reason_codes=tuple(reason_codes))


def _allow_unmapped_eco_fallback(scored: ScoredChunk, bucket: RetrievalBucket) -> bool:
    return (
        bucket.eco_code is not None
        and scored.chunk.opening_node_id is None
        and scored.chunk.eco_code == bucket.eco_code
        and scored.chunk.section_index == 0
        and bucket.relation_to_position in {"current", "parent", "child"}
    )


def _exclusion_reason(scored: ScoredChunk, bucket: RetrievalBucket, plan: RetrievalPlan) -> str | None:
    node_id = scored.chunk.opening_node_id
    if node_id and node_id in plan.excluded_node_ids:
        return "excluded_descendant"
    if node_id and bucket.node_ids and node_id not in bucket.node_ids:
        return "outside_bucket_node_ids"
    return None


def _deduplicate_and_rank(
    candidates: list[_Candidate],
) -> tuple[tuple[RetrievedContext, ...], list[RerankingDiagnostic]]:
    ranked = sorted(candidates, key=lambda candidate: (-candidate.reranked_score, candidate.original_index))
    seen_chunk_ids: set[str] = set()
    seen_sections: dict[tuple[str | None, str, int | None], int] = {}
    contexts: list[RetrievedContext] = []
    diagnostics: list[RerankingDiagnostic] = []

    for candidate in ranked:
        chunk_id = candidate.context.chunk_id
        section_key = (
            candidate.context.opening_node_id,
            candidate.context.page_id,
            candidate.context.section_index,
        )
        duplicate_reason = None
        if chunk_id in seen_chunk_ids:
            duplicate_reason = "duplicate_chunk"
        elif section_key in seen_sections and seen_sections[section_key] != candidate.context.part_index:
            duplicate_reason = "duplicate_page_section"

        if duplicate_reason:
            diagnostics.append(_candidate_diagnostic(candidate, "deduplicated", (duplicate_reason,)))
            continue

        seen_chunk_ids.add(chunk_id)
        seen_sections[section_key] = candidate.context.part_index
        contexts.append(candidate.context)
        diagnostics.append(_candidate_diagnostic(candidate, "kept", candidate.reason_codes))

    return tuple(contexts), diagnostics


def _diagnostic(
    scored: ScoredChunk,
    bucket: RetrievalBucket,
    decision: _ScoreDecision,
    action: str,
) -> RerankingDiagnostic:
    return {
        "chunk_id": scored.chunk.id,
        "bucket": bucket.name,
        "original_score": scored.score,
        "reranked_score": decision.score,
        "decision": action,
        "reason_codes": list(decision.reason_codes),
    }


def _candidate_diagnostic(
    candidate: _Candidate,
    action: str,
    reason_codes: tuple[str, ...],
) -> RerankingDiagnostic:
    return {
        "chunk_id": candidate.context.chunk_id,
        "bucket": candidate.bucket.name,
        "original_score": candidate.original_score,
        "reranked_score": candidate.reranked_score,
        "decision": action,
        "reason_codes": list(reason_codes),
    }


def _to_retrieved_context(scored: ScoredChunk, bucket: RetrievalBucket) -> RetrievedContext:
    chunk = scored.chunk
    return RetrievedContext(
        chunk_id=chunk.id,
        text=chunk.text,
        source=chunk.source,
        source_url=chunk.source_url,
        license_or_terms=chunk.license_or_terms,
        page_id=chunk.page_id,
        canonical_title=chunk.canonical_title,
        section_index=chunk.section_index,
        part_index=chunk.part_index,
        section_title=chunk.section_title,
        score=scored.score,
        relation_to_position=bucket.relation_to_position,
        entry_move=bucket.entry_move if bucket.relation_to_position == "child" else None,
        opening_node_id=chunk.opening_node_id,
        eco_code=chunk.eco_code,
        opening_name=chunk.opening_name,
        intent=chunk.intent,
        is_history=chunk.is_history,
        is_misc=chunk.is_misc,
    )
