"""LangGraph entry point for the progressive Explorer analysis.

The graph deliberately delegates the business logic to the existing analysis
service. This keeps cache, persistence, fallbacks, and external-call policy in
the tested imperative layer while making the orchestration explicit.
"""

from dataclasses import dataclass
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.models.analysis import AnalyzePositionRequest, AnalyzePositionResponse
from backend.app.services.analysis import analyze_position
from backend.app.services.cache_store import CacheStore
from backend.app.services.coach import CoachService
from backend.app.services.lichess import LichessExplorerClient
from backend.app.services.opening_tree import OpeningTree
from backend.app.services.rag import RagService
from backend.app.services.run_store import RunStore
from backend.app.services.session_store import SessionStore
from backend.app.services.stockfish import StockfishService
from backend.app.services.intent_router import IntentRouter
from backend.app.services.youtube import YouTubeClient


class ExplorerGraphState(TypedDict):
    request: AnalyzePositionRequest
    response: NotRequired[AnalyzePositionResponse]


@dataclass(frozen=True)
class ExplorerGraphDependencies:
    """Runtime services injected into the graph, never stored in graph state."""

    lichess_client: LichessExplorerClient
    stockfish_service: StockfishService
    cache_store: CacheStore
    session_store: SessionStore
    opening_tree: OpeningTree | None
    intent_router: IntentRouter | None
    rag_service: RagService | None
    coach_service: CoachService | None
    run_store: RunStore
    youtube_client: YouTubeClient | None = None


def build_explorer_graph(dependencies: ExplorerGraphDependencies):
    """Compile the Explorer graph around the existing idempotent service."""

    def run_explorer(state: ExplorerGraphState) -> dict[str, AnalyzePositionResponse]:
        response = analyze_position(
            state["request"],
            dependencies.lichess_client,
            dependencies.stockfish_service,
            dependencies.cache_store,
            dependencies.session_store,
            dependencies.opening_tree,
            dependencies.intent_router,
            dependencies.rag_service,
            dependencies.coach_service,
            dependencies.run_store,
            youtube_client=dependencies.youtube_client,
        )
        return {"response": response}

    builder = StateGraph(ExplorerGraphState)
    builder.add_node("run_explorer", run_explorer)
    builder.add_edge(START, "run_explorer")
    builder.add_edge("run_explorer", END)
    return builder.compile()


def run_explorer_graph(
    request: AnalyzePositionRequest,
    dependencies: ExplorerGraphDependencies,
) -> AnalyzePositionResponse:
    """Run one Explorer request through LangGraph."""

    result = build_explorer_graph(dependencies).invoke({"request": request})
    return result["response"]
