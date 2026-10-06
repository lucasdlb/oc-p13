"""LangGraph boundary for coach synthesis."""

from dataclasses import dataclass
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.models.analysis import CoachExplanationResponse
from backend.app.services.analysis import render_run_coach
from backend.app.services.coach import CoachService
from backend.app.services.run_store import RunStore


class CoachGraphState(TypedDict):
    run_id: str
    level: str
    response: NotRequired[CoachExplanationResponse]


@dataclass(frozen=True)
class CoachGraphDependencies:
    coach_service: CoachService
    run_store: RunStore


def run_coach_graph(
    run_id: str,
    level: str,
    dependencies: CoachGraphDependencies,
) -> CoachExplanationResponse:
    """Generate coach prose once; the service owns persistence and deduplication."""

    def synthesize(state: CoachGraphState) -> dict[str, CoachExplanationResponse]:
        return {
            "response": render_run_coach(
                run_id=state["run_id"],
                level=state["level"],
                coach_service=dependencies.coach_service,
                run_store=dependencies.run_store,
            )
        }

    builder = StateGraph(CoachGraphState)
    builder.add_node("synthesize_coach", synthesize)
    builder.add_edge(START, "synthesize_coach")
    builder.add_edge("synthesize_coach", END)
    result = builder.compile().invoke({"run_id": run_id, "level": level})
    return result["response"]
