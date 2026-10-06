"""LangGraph boundary for the progressive RAG family."""

from dataclasses import dataclass
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.models.analysis import RagContextResponse
from backend.app.services.analysis import retrieve_rag_for_run
from backend.app.services.intent_router import IntentRouter
from backend.app.services.opening_tree import OpeningTree
from backend.app.services.rag import RagService
from backend.app.services.run_store import RunStore


class RagGraphState(TypedDict):
    run_id: str
    response: NotRequired[RagContextResponse]


@dataclass(frozen=True)
class RagGraphDependencies:
    run_store: RunStore
    opening_tree: OpeningTree | None
    intent_router: IntentRouter | None
    rag_service: RagService | None


def run_rag_graph(run_id: str, dependencies: RagGraphDependencies) -> RagContextResponse:
    """Run RAG once; the underlying service owns claim, cache, and persistence."""

    def retrieve(state: RagGraphState) -> dict[str, RagContextResponse]:
        return {
            "response": retrieve_rag_for_run(
                state["run_id"],
                dependencies.run_store,
                dependencies.opening_tree,
                dependencies.intent_router,
                dependencies.rag_service,
            )
        }

    builder = StateGraph(RagGraphState)
    builder.add_node("retrieve_rag", retrieve)
    builder.add_edge(START, "retrieve_rag")
    builder.add_edge("retrieve_rag", END)
    result = builder.compile().invoke({"run_id": run_id})
    return result["response"]
