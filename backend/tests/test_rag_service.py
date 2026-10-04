import pytest

from backend.app.models.knowledge import KnowledgeChunk, ScoredChunk
from backend.app.services.embeddings import EmbeddingProviderError
from backend.app.services.milvus import MilvusMetadataFilter, MilvusStoreError
from backend.app.services.rag import RagRetrievalResult, RagService
from backend.app.services.retrieval_contracts import (
    OpeningTreeContext,
    OpeningTreeNodeContext,
    RetrievalBucket,
    RetrievalPlan,
)


RUY = OpeningTreeNodeContext(
    node_id="ruy-node",
    eco_code="C60",
    opening_name="Ruy Lopez",
    pgn="1. e4 e5 2. Nf3 Nc6 3. Bb5",
    uci=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"),
    san=("e4", "e5", "Nf3", "Nc6", "Bb5"),
    fen="ruy-fen",
    epd="ruy-epd",
    depth=5,
)

BERLIN = OpeningTreeNodeContext(
    node_id="berlin-node",
    eco_code="C65",
    opening_name="Ruy Lopez: Berlin Defense",
    pgn="1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6",
    uci=("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6"),
    san=("e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6"),
    fen="berlin-fen",
    epd="berlin-epd",
    depth=6,
    entry_move="Nf6",
)


class FakeEmbeddingProvider:
    dimension = 4

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        if self.fail:
            raise EmbeddingProviderError("ollama down")
        return [1.0, 0.0, 0.0, 0.0]


class FakeStore:
    def __init__(
        self,
        responses: dict[tuple[str, ...], list[ScoredChunk]] | None = None,
        eco_responses: dict[str, list[ScoredChunk]] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.eco_responses = eco_responses or {}
        self.calls: list[dict] = []

    def search(
        self,
        vector: list[float],
        k: int,
        *,
        eco_code: str | None = None,
        metadata_filter: MilvusMetadataFilter | None = None,
        min_score: float | None = None,
    ) -> list[ScoredChunk]:
        assert vector == [1.0, 0.0, 0.0, 0.0]
        self.calls.append(
            {"k": k, "eco_code": eco_code, "metadata_filter": metadata_filter, "min_score": min_score}
        )
        if eco_code:
            return self.eco_responses.get(eco_code, [])[:k]
        node_ids = metadata_filter.opening_node_ids if metadata_filter else ()
        return self.responses.get(node_ids, [])[:k]


class FailingStore(FakeStore):
    def search(self, *args: object, **kwargs: object) -> list[ScoredChunk]:
        raise MilvusStoreError("milvus down")


def _chunk(identifier: str, text: str, **metadata: object) -> ScoredChunk:
    return ScoredChunk(
        chunk=KnowledgeChunk(
            id=identifier,
            text=text,
            source=str(metadata.pop("source", "wikibooks")),
            source_url=metadata.pop("source_url", "https://example.test/source"),  # type: ignore[arg-type]
            license_or_terms=metadata.pop("license_or_terms", "CC BY-SA 4.0"),  # type: ignore[arg-type]
            page_id=str(metadata.pop("page_id", "wikibooks::Ruy_Lopez")),
            canonical_title=str(metadata.pop("canonical_title", "Ruy Lopez")),
            section_index=metadata.pop("section_index", 2),  # type: ignore[arg-type]
            part_index=metadata.pop("part_index", 0),  # type: ignore[arg-type]
            section_title=metadata.pop("section_title", "Ideas"),  # type: ignore[arg-type]
            opening_node_id=metadata.pop("opening_node_id", "ruy-node"),  # type: ignore[arg-type]
            eco_code=metadata.pop("eco_code", "C60"),  # type: ignore[arg-type]
            opening_name=metadata.pop("opening_name", "Ruy Lopez"),  # type: ignore[arg-type]
            intent=metadata.pop("intent", "plan"),  # type: ignore[arg-type]
            is_history=metadata.pop("is_history", False),  # type: ignore[arg-type]
            is_misc=metadata.pop("is_misc", False),  # type: ignore[arg-type]
        ),
        score=0.91,
    )


def test_current_only_plan_searches_only_current_node_and_preserves_attribution() -> None:
    plan = RetrievalPlan.current_only(
        tree_context=OpeningTreeContext(current=RUY, children=(BERLIN,), excluded_descendant_node_ids=("deep-node",)),
        reason="safe_default",
    )
    store = FakeStore({("ruy-node",): [_chunk("current", "Ruy Lopez ideas")]})
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store, min_score=0.25)

    result = service.retrieve(plan, "Explain this position")

    assert isinstance(result, RagRetrievalResult)
    assert result.fallback_reasons == ()
    assert [context.chunk_id for context in result.contexts] == ["current"]
    assert result.contexts[0].relation_to_position == "current"
    assert result.contexts[0].source == "wikibooks"
    assert result.contexts[0].source_url == "https://example.test/source"
    assert result.contexts[0].license_or_terms == "CC BY-SA 4.0"
    assert store.calls == [
        {
            "k": 4,
            "eco_code": None,
            "metadata_filter": MilvusMetadataFilter(
                opening_node_ids=("ruy-node",),
                intent_not_in=("history", "misc"),
                is_history=False,
                is_misc=False,
            ),
            "min_score": 0.25,
        }
    ]


def test_current_bucket_falls_back_to_eco_when_chunks_are_not_node_mapped() -> None:
    plan = RetrievalPlan.current_only(tree_context=OpeningTreeContext(current=RUY))
    store = FakeStore(
        eco_responses={"C60": [_chunk("current-eco", "Ruy Lopez ideas", opening_node_id=None)]}
    )
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store)

    result = service.retrieve(plan, "Explain this position")

    assert [context.chunk_id for context in result.contexts] == ["current-eco"]
    assert result.contexts[0].relation_to_position == "current"
    assert store.calls == [
        {
            "k": 4,
            "eco_code": None,
            "metadata_filter": MilvusMetadataFilter(
                opening_node_ids=("ruy-node",),
                intent_not_in=("history", "misc"),
                is_history=False,
                is_misc=False,
            ),
            "min_score": None,
        },
        {
            "k": 4,
            "eco_code": "C60",
            "metadata_filter": MilvusMetadataFilter(
                intent_not_in=("history", "misc"),
                is_history=False,
                is_misc=False,
            ),
            "min_score": None,
        },
    ]


def test_child_allowed_plan_labels_child_context_as_conditional() -> None:
    plan = RetrievalPlan(
        intent="ask_specific_candidate",
        state="matched",
        reason="specific_direct_child_allowed",
        buckets=(
            RetrievalBucket(name="current", relation_to_position="current", node_ids=("ruy-node",), limit=1),
            RetrievalBucket(
                name="matched_child",
                relation_to_position="child",
                node_ids=("berlin-node",),
                limit=2,
                entry_move="Nf6",
            ),
        ),
    )
    store = FakeStore(
        {
            ("ruy-node",): [_chunk("current", "Ruy Lopez ideas")],
            ("berlin-node",): [
                _chunk(
                    "berlin",
                    "The Berlin starts after ...Nf6.",
                    opening_node_id="berlin-node",
                    eco_code="C65",
                    opening_name="Ruy Lopez: Berlin Defense",
                )
            ],
        }
    )
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store)

    result = service.retrieve(plan, "What about Nf6?")

    assert [context.chunk_id for context in result.contexts] == ["current", "berlin"]
    child = result.contexts[1]
    assert child.relation_to_position == "child"
    assert child.entry_move == "Nf6"
    assert child.opening_node_id == "berlin-node"


def test_bucket_limits_are_applied_before_merge() -> None:
    plan = RetrievalPlan.with_children(tree_context=OpeningTreeContext(current=RUY, children=(BERLIN,)))
    store = FakeStore(
        {
            ("ruy-node",): [_chunk("current-1", "one"), _chunk("current-2", "two")],
            ("berlin-node",): [
                _chunk("child-1", "one", opening_node_id="berlin-node"),
                _chunk("child-2", "two", opening_node_id="berlin-node"),
                _chunk("child-3", "three", opening_node_id="berlin-node"),
            ],
        }
    )
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store)

    result = service.retrieve(plan, "next moves")

    assert [call["k"] for call in store.calls] == [4, 3]
    assert [context.chunk_id for context in result.contexts] == [
        "current-1",
        "current-2",
        "child-1",
        "child-2",
        "child-3",
    ]


def test_reranking_excludes_deep_descendants_and_emits_diagnostics() -> None:
    plan = RetrievalPlan.current_only(
        tree_context=OpeningTreeContext(current=RUY, excluded_descendant_node_ids=("deep-node",)),
    )
    store = FakeStore(
        {
            ("ruy-node",): [
                _chunk("deep", "Deep descendant", opening_node_id="deep-node"),
                _chunk("current", "Current line", opening_node_id="ruy-node"),
            ]
        }
    )
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store)

    result = service.retrieve(plan, "explain")

    assert [context.chunk_id for context in result.contexts] == ["current"]
    assert result.reranking_diagnostics == (
        {
            "chunk_id": "deep",
            "bucket": "current",
            "original_score": 0.91,
            "reranked_score": 0.91,
            "decision": "excluded",
            "reason_codes": ["excluded_descendant"],
        },
        {
            "chunk_id": "current",
            "bucket": "current",
            "original_score": 0.91,
            "reranked_score": 1.31,
            "decision": "kept",
            "reason_codes": ["boost_current"],
        },
    )


def test_reranking_suppresses_history_and_misc_unless_requested() -> None:
    plan = RetrievalPlan.current_only(tree_context=OpeningTreeContext(current=RUY))
    store = FakeStore(
        {
            ("ruy-node",): [
                _chunk("history", "History", intent="history", is_history=True),
                _chunk("misc", "Trivia", intent="misc", is_misc=True),
                _chunk("current", "Plans", intent="plan", is_misc=False),
            ]
        }
    )
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store)

    result = service.retrieve(plan, "explain")

    assert [context.chunk_id for context in result.contexts] == ["current"]
    assert [diagnostic["reason_codes"] for diagnostic in result.reranking_diagnostics] == [
        ["history_suppressed"],
        ["misc_suppressed"],
        ["boost_current"],
    ]


def test_history_is_kept_when_history_bucket_requests_it() -> None:
    plan = RetrievalPlan.history_only(tree_context=OpeningTreeContext(current=RUY))
    store = FakeStore({("ruy-node",): [_chunk("history", "History", intent="history", is_history=True)]})
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store)

    result = service.retrieve(plan, "histoire")

    assert [context.chunk_id for context in result.contexts] == ["history"]
    assert result.reranking_diagnostics[0]["decision"] == "kept"


def test_current_explanation_keeps_current_prose_above_child_prose() -> None:
    plan = RetrievalPlan(
        intent="explain_current_position",
        state="matched",
        reason="current_position",
        buckets=(
            RetrievalBucket(name="current", relation_to_position="current", node_ids=("ruy-node",), limit=1),
            RetrievalBucket(name="children", relation_to_position="child", node_ids=("berlin-node",), limit=1),
        ),
    )
    store = FakeStore(
        {
            ("ruy-node",): [_chunk("current", "Ruy ideas", opening_node_id="ruy-node")],
            ("berlin-node",): [
                _chunk("berlin", "Berlin ideas", opening_node_id="berlin-node", eco_code="C65")
            ],
        }
    )
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store)

    result = service.retrieve(plan, "explain")

    assert [context.chunk_id for context in result.contexts] == ["current", "berlin"]
    assert result.reranking_diagnostics[0]["reranked_score"] > result.reranking_diagnostics[1]["reranked_score"]


def test_reranking_deduplicates_page_section_results_preserving_source_attribution() -> None:
    plan = RetrievalPlan.current_only(tree_context=OpeningTreeContext(current=RUY))
    store = FakeStore(
        {
            ("ruy-node",): [
                _chunk("first", "Plans", page_id="wikibooks::Ruy", section_index=2, part_index=0),
                _chunk("duplicate", "Same section", page_id="wikibooks::Ruy", section_index=2, part_index=1),
            ]
        }
    )
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store)

    result = service.retrieve(plan, "explain")

    assert [context.chunk_id for context in result.contexts] == ["first"]
    assert result.contexts[0].source_url == "https://example.test/source"
    assert result.reranking_diagnostics[-1]["reason_codes"] == ["duplicate_page_section"]


def test_history_and_general_buckets_use_expected_filters() -> None:
    plan = RetrievalPlan(
        intent="ask_history",
        state="matched",
        reason="history_and_general",
        buckets=(
            RetrievalBucket(
                name="history",
                relation_to_position="current",
                node_ids=("ruy-node",),
                limit=2,
                include_history=True,
            ),
            RetrievalBucket(
                name="general",
                relation_to_position="general",
                node_ids=(),
                limit=2,
                include_misc=True,
            ),
        ),
    )
    store = FakeStore()
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=store)

    service.retrieve(plan, "history")


    assert [call["metadata_filter"] for call in store.calls] == [
        MilvusMetadataFilter(opening_node_ids=("ruy-node",), intent_in=("history",), is_history=True),
        MilvusMetadataFilter(),
    ]


def test_embedding_failure_returns_empty_context_with_fallback_metadata() -> None:
    service = RagService(embedding_provider=FakeEmbeddingProvider(fail=True), store=FakeStore())

    result = service.retrieve(RetrievalPlan.current_only(tree_context=OpeningTreeContext(current=RUY)), "query")

    assert result.contexts == ()
    assert result.fallback_reasons == ("rag_embedding_unavailable",)


def test_store_failure_returns_empty_context_with_fallback_metadata() -> None:
    service = RagService(embedding_provider=FakeEmbeddingProvider(), store=FailingStore())

    result = service.retrieve(RetrievalPlan.current_only(tree_context=OpeningTreeContext(current=RUY)), "query")

    assert result.contexts == ()
    assert result.fallback_reasons == ("rag_store_unavailable",)


def test_empty_plan_returns_empty_context_without_external_calls() -> None:
    provider = FakeEmbeddingProvider()
    service = RagService(
        embedding_provider=provider,
        store=FakeStore(),
    )
    plan = RetrievalPlan(intent="unclear", state="unsupported", reason="empty", buckets=())

    result = service.retrieve(plan, "query")

    assert result.contexts == ()
    assert result.fallback_reasons == ()
    assert provider.queries == []
