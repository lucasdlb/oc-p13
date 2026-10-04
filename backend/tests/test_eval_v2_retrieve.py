import pytest

from backend.app.models.knowledge import KnowledgeChunk, ScoredChunk
from backend.app.services.intent_router import CandidateMove
from backend.app.services.milvus import MilvusMetadataFilter
from backend.app.services.retrieval_contracts import OpeningTreeContext, OpeningTreeNodeContext
from experiments.rag.eval_v2 import retrieve


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


class FakeTree:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def context_for_position(self, *, moves: list[str], fen: str) -> OpeningTreeContext:
        self.calls.append({"moves": moves, "fen": fen})
        return OpeningTreeContext(current=RUY, children=(BERLIN,))


class FakeProvider:
    dimension = 4

    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [1.0, 0.0, 0.0, 0.0]


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def search(
        self,
        vector: list[float],
        k: int,
        *,
        metadata_filter: MilvusMetadataFilter | None = None,
        min_score: float | None = None,
    ) -> list[ScoredChunk]:
        self.calls.append({"k": k, "metadata_filter": metadata_filter, "min_score": min_score})
        if metadata_filter and metadata_filter.opening_node_ids == ("ruy-node",):
            return [_scored_chunk("current", "ruy-node", "Ruy Lopez", section_title="Plans")]
        if metadata_filter and metadata_filter.opening_node_ids == ("berlin-node",):
            return [_scored_chunk("berlin", "berlin-node", "Ruy Lopez: Berlin Defense")]
        return []


def _scored_chunk(identifier: str, node_id: str, opening_name: str, *, section_title: str = "Ideas") -> ScoredChunk:
    return ScoredChunk(
        chunk=KnowledgeChunk(
            id=identifier,
            text=f"{opening_name} prose",
            source="wikibooks-chess-opening-theory",
            page_id=f"wikibooks::{identifier}",
            canonical_title=opening_name,
            section_index=1,
            part_index=0,
            section_title=section_title,
            source_url="https://example.test/source",
            license_or_terms="CC BY-SA 4.0",
            opening_name=opening_name,
            eco_code="C60",
            opening_node_id=node_id,
            intent="plan",
            is_history=False,
            is_misc=False,
        ),
        score=0.9,
    )


def test_eval_v2_document_shape_includes_pollution_and_attribution_fields() -> None:
    result = ScoredChunk(
        chunk=KnowledgeChunk(
            id="chunk-1",
            text="Ruy Lopez prose",
            source="wikibooks-chess-opening-theory",
            page_id="wikibooks::ruy-lopez",
            canonical_title="Ruy Lopez",
            section_index=1,
            part_index=0,
            section_title="Plans",
            source_url="https://example.test/ruy-lopez",
            license_or_terms="CC BY-SA 4.0",
            opening_name="Ruy Lopez",
            eco_code="C60",
            opening_node_id="node-1",
            intent="plan",
            is_history=False,
            is_misc=False,
            created_at="2026-10-03T00:00:00+00:00",
        ),
        score=0.98765,
    )

    assert retrieve._to_document(result) == {
        "id": "chunk-1",
        "score": 0.9877,
        "source": "wikibooks-chess-opening-theory",
        "source_url": "https://example.test/ruy-lopez",
        "license_or_terms": "CC BY-SA 4.0",
        "page_id": "wikibooks::ruy-lopez",
        "section_title": "Plans",
        "section_index": 1,
        "part_index": 0,
        "opening_name": "Ruy Lopez",
        "eco_code": "C60",
        "opening_node_id": "node-1",
        "intent": "plan",
        "is_history": False,
        "is_misc": False,
        "text": "Ruy Lopez prose",
    }


def test_eval_v2_query_text_uses_question_opening_position_and_intent() -> None:
    assert retrieve._query_text(
        {
            "question": "Que peuvent jouer les Noirs ?",
            "current_opening": "Ruy Lopez",
            "position": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "intent": "ask_next_moves",
        }
    ) == (
        "Que peuvent jouer les Noirs ?\n"
        "Opening: Ruy Lopez\n"
        "Position: 1. e4 e5 2. Nf3 Nc6 3. Bb5\n"
        "Intent: ask_next_moves"
    )


def test_retrieve_cases_uses_real_pipeline_and_records_artifacts() -> None:
    tree = FakeTree()
    store = FakeStore()
    provider = FakeProvider()
    cases = [
        {
            "id": "next-ruy",
            "question": "Que peuvent jouer les Noirs maintenant ?",
            "current_opening": "Ruy Lopez",
            "position": "1. e4 e5 2. Nf3 Nc6 3. Bb5",
            "moves": ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
            "fen": "fen",
        }
    ]

    retrieved, latency, pipeline = retrieve.retrieve_cases(
        cases,
        store,
        provider,
        tree,
        k=5,
        min_score=0.25,
    )

    assert [doc["id"] for doc in retrieved["next-ruy"]] == ["current", "berlin"]
    assert tree.calls == [{"moves": cases[0]["moves"], "fen": "fen"}]
    assert provider.queries == [retrieve._query_text(cases[0])]
    assert [call["metadata_filter"].opening_node_ids for call in store.calls] == [("ruy-node",), ("berlin-node",)]
    assert all(call["min_score"] == 0.25 for call in store.calls)
    assert set(latency) == {"embed", "search", "total"}
    assert pipeline["next-ruy"]["tree_context"]["current"]["node_id"] == "ruy-node"
    assert pipeline["next-ruy"]["intent_decision"]["intent"] == "ask_next_moves"
    assert pipeline["next-ruy"]["retrieval_plan"]["buckets"][1]["name"] == "children"
    assert [ctx["chunk_id"] for ctx in pipeline["next-ruy"]["rag_result"]["contexts"]] == ["current", "berlin"]


def test_intent_context_exposes_direct_child_candidates() -> None:
    context = retrieve._intent_context(
        {
            "question": "Et ...Nf6 ?",
            "moves": ["e2e4"],
            "fen": "fen",
        },
        OpeningTreeContext(current=RUY, children=(BERLIN,)),
    )

    assert context.current_opening_name == "Ruy Lopez"
    assert context.legal_child_moves == (
        CandidateMove(
            san="Nf6",
            uci="g8f6",
            opening_name="Ruy Lopez: Berlin Defense",
            eco_code="C65",
            opening_node_id="berlin-node",
        ),
    )


def _pipeline(*fallback_reasons: str) -> dict[str, dict]:
    return {
        f"case-{index}": {
            "rag_result": {"contexts": [], "fallback_reasons": list(reasons)},
        }
        for index, reasons in enumerate(fallback_reasons)
    }


def test_reject_incomplete_retrieval_fails_on_store_shortfall() -> None:
    retrieved = {"case-0": [], "case-1": [{"id": "doc"}]}
    pipeline = _pipeline(("rag_store_unavailable",), ())

    with pytest.raises(RuntimeError, match="rag store unavailable for 1/2 cases \\(case-0\\)"):
        retrieve._reject_incomplete_retrieval(retrieved, pipeline)


def test_reject_incomplete_retrieval_fails_when_every_case_is_empty() -> None:
    with pytest.raises(RuntimeError, match="every case retrieved zero documents"):
        retrieve._reject_incomplete_retrieval({"case-0": [], "case-1": []}, _pipeline((), ()))


def test_reject_incomplete_retrieval_warns_on_partial_empty(capsys: pytest.CaptureFixture[str]) -> None:
    retrieve._reject_incomplete_retrieval(
        {"case-0": [], "case-1": [{"id": "doc"}]},
        _pipeline((), ()),
    )

    assert "warning: 1 cases retrieved no documents: case-0" in capsys.readouterr().err


def test_reject_incomplete_retrieval_passes_a_complete_run() -> None:
    retrieve._reject_incomplete_retrieval(
        {"case-0": [{"id": "doc"}], "case-1": [{"id": "doc"}]},
        _pipeline((), ()),
    )
