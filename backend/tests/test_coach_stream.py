import threading
from types import SimpleNamespace

from backend.app.services import coach_stream
from backend.app.services.coach import CoachFallbackError
from backend.app.services.retrieval_contracts import CoachContext, CoachPositionContext


class _FallbackStreamCoach:
    def stream_explain(self, _context: object, *, level: str):  # type: ignore[no-untyped-def]
        assert level == "intermediaire"
        yield "partial LLM response"
        raise CoachFallbackError("deterministic fallback", "llm_coach_too_long")


class _RunStore:
    def get_run(self, _run_id: str):  # type: ignore[no-untyped-def]
        return None

    def save_coach_result(self, *args: object) -> bool:
        return True

    def reset_coach(self, _run_id: str) -> bool:
        return True


class _RawReferenceStreamCoach:
    def stream_explain(self, _context: object, *, level: str):  # type: ignore[no-untyped-def]
        assert level == "debutant"
        yield (
            "Regardez une attaque sur e5 ou d5. Le coup e5 reste important. "
            "Regardez d7d5, e7e6, b8c6 ou Nf6. Suite d7d5 puis g1f3."
        )


def test_stream_fallback_is_final_result_not_an_additional_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(coach_stream, "coach_context_for_run", lambda _run: object())
    monkeypatch.setattr(coach_stream, "_publish", lambda _active, event, data: events.append((event, data)))
    monkeypatch.setattr(coach_stream, "_mark_done", lambda _active: None)
    active = SimpleNamespace(
        run_id="run-1",
        run_store=_RunStore(),
        coach_service=_FallbackStreamCoach(),
        level="intermediaire",
        cancel_event=threading.Event(),
    )

    coach_stream._generate(active, SimpleNamespace(run_id="run-1"))

    assert events == [
        ("token", {"text": "partial LLM response"}),
        (
            "done",
            {
                "explanation": "deterministic fallback",
                "coach_status": "fallback",
                "fallbacks_used": ["llm_coach_too_long"],
            },
        ),
    ]


def test_stream_finalizes_all_allowed_uci_references(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    context = CoachContext(
        current_position=CoachPositionContext(
            state="matched",
            opening_name="King's Pawn Game",
            eco_code="B00",
            pgn="1. e4",
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        ),
        recommended_moves=[
            {"san": "d5", "uci": "d7d5"},
            {"san": "e6", "uci": "e7e6"},
            {"san": "Nc6", "uci": "b8c6"},
            {"san": "Nf6", "uci": "g8f6"},
            {"san": "e5", "uci": "e7e5"},
        ],
    )
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(coach_stream, "coach_context_for_run", lambda _run: context)
    monkeypatch.setattr(coach_stream, "_publish", lambda _active, event, data: events.append((event, data)))
    monkeypatch.setattr(coach_stream, "_mark_done", lambda _active: None)
    active = SimpleNamespace(
        run_id="run-2",
        run_store=_RunStore(),
        coach_service=_RawReferenceStreamCoach(),
        level="debutant",
        cancel_event=threading.Event(),
    )

    coach_stream._generate(active, SimpleNamespace(run_id="run-2"))

    explanation = events[-1][1]["explanation"]
    for uci, san in (("d7d5", "d5"), ("e7e6", "e6"), ("b8c6", "Nc6"), ("g8f6", "Nf6")):
        assert f"[[move:uci={uci},label={san}]]" in explanation
    assert "[[square:sq=e5,label=e5]]" in explanation
    assert "[[square:sq=d5,label=d5]]" in explanation
    assert "[[move:uci=e7e5,label=e5]]" in explanation
    assert "[[line:moves=d7d5,g1f3,label=d5 puis Nf3]]" in explanation
