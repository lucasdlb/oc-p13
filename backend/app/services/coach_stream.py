"""Shared coach generation and SSE subscription state for one API process."""

import asyncio
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.sse import ServerSentEvent

from backend.app.models.analysis import AnalysisRun
from backend.app.services.analysis import coach_context_for_run
from backend.app.services.coach import CoachFallbackError, CoachService, prepare_coach_output
from backend.app.services.run_store import RunStore
from backend.app.services.retrieval_contracts import CoachContext


@dataclass
class _ActiveCoachStream:
    run_id: str
    run_store: RunStore
    coach_service: CoachService
    level: str
    loop: asyncio.AbstractEventLoop
    subscribers: set[asyncio.Queue[tuple[str, dict]]] = field(default_factory=set)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    task: asyncio.Task[None] | None = None
    done: bool = False


_active_streams: dict[str, _ActiveCoachStream] = {}
_active_streams_lock = threading.Lock()


async def stream_coach(
    request: Request,
    run: AnalysisRun,
    run_store: RunStore,
    coach_service: CoachService,
    level: str,
) -> AsyncIterator[ServerSentEvent]:
    active, created = _get_or_create_stream(run, run_store, coach_service, level)
    if active is None:
        stored = run.coach_result or {}
        yield ServerSentEvent(event="start", data={"run_id": run.run_id})
        if run.coach_status in {"generated", "fallback"} and stored.get("explanation"):
            yield ServerSentEvent(event="token", data={"text": stored["explanation"]})
            yield ServerSentEvent(
                event="done",
                data={
                    "explanation": stored["explanation"],
                    "coach_status": run.coach_status,
                    "fallbacks_used": stored.get("fallbacks_used", []),
                },
            )
        else:
            yield ServerSentEvent(
                event="error",
                data={"message": "Coach generation unavailable"},
            )
        return

    queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()
    with _active_streams_lock:
        active.subscribers.add(queue)
    if created:
        active.task = asyncio.create_task(asyncio.to_thread(_generate, active, run))

    try:
        yield ServerSentEvent(event="start", data={"run_id": run.run_id})
        while True:
            try:
                event, data = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                if await request.is_disconnected():
                    raise asyncio.CancelledError
                continue
            yield ServerSentEvent(event=event, data=data)
            if event in {"done", "error"}:
                break
    except asyncio.CancelledError:
        _unsubscribe(active, queue)
        raise
    finally:
        _unsubscribe(active, queue)


def _get_or_create_stream(
    run: AnalysisRun,
    run_store: RunStore,
    coach_service: CoachService,
    level: str,
) -> tuple[_ActiveCoachStream | None, bool]:
    with _active_streams_lock:
        active = _active_streams.get(run.run_id)
        if active is not None:
            return active, False
        if run.coach_status in {"generated", "fallback"}:
            return None, False
        if run.coach_status == "running":
            # A process restart can leave a persisted running marker without
            # an in-memory producer. Only this process can have an active
            # producer, so reclaim the stale marker before retrying.
            run_store.reset_coach(run.run_id)
        if not run_store.claim_family(run.run_id, "coach"):
            return None, False
        active = _ActiveCoachStream(
            run_id=run.run_id,
            run_store=run_store,
            coach_service=coach_service,
            level=level,
            loop=asyncio.get_running_loop(),
        )
        _active_streams[run.run_id] = active
        return active, True


def _generate(active: _ActiveCoachStream, original_run: AnalysisRun) -> None:
    try:
        run = active.run_store.get_run(original_run.run_id) or original_run
        context = coach_context_for_run(run)
        chunks: list[str] = []
        stream_explain = getattr(active.coach_service, "stream_explain", None)
        if callable(stream_explain):
            iterator = stream_explain(context, level=active.level)
        else:
            result = active.coach_service.explain(context, level=active.level)
            iterator = iter([result.text])
        for chunk in iterator:
            if active.cancel_event.is_set():
                return
            if not chunk:
                continue
            chunks.append(chunk)
            _publish(active, "token", {"text": chunk})

        explanation = prepare_coach_output("".join(chunks).strip(), context).text
        if active.cancel_event.is_set():
            return
        if not explanation:
            active.run_store.reset_coach(active.run_id)
            _mark_done(active)
            _publish(active, "error", {"message": "Coach generation unavailable"})
            return
        active.run_store.save_coach_result(active.run_id, explanation, "generated", [])
        _mark_done(active)
        _publish(
            active,
            "done",
            {
                "explanation": explanation,
                "coach_status": "generated",
                "fallbacks_used": [],
            },
        )
    except CoachFallbackError as exc:
        if active.cancel_event.is_set():
            return
        safe_text = prepare_coach_output(exc.text, context).text if isinstance(context, CoachContext) else exc.text
        active.run_store.save_coach_result(
            active.run_id,
            safe_text,
            "fallback",
            [exc.fallback_label],
        )
        _mark_done(active)
        _publish(
            active,
            "done",
            {
                "explanation": safe_text,
                "coach_status": "fallback",
                "fallbacks_used": [exc.fallback_label],
            },
        )
    except Exception:  # noqa: BLE001 - the stream must report a safe event
        if not active.cancel_event.is_set():
            active.run_store.reset_coach(active.run_id)
            _mark_done(active)
            _publish(active, "error", {"message": "Coach generation unavailable"})
    finally:
        _mark_done(active)


def _publish(active: _ActiveCoachStream, event: str, data: dict) -> None:
    def publish_on_loop() -> None:
        with _active_streams_lock:
            subscribers = tuple(active.subscribers)
        for subscriber in subscribers:
            subscriber.put_nowait((event, data))

    active.loop.call_soon_threadsafe(publish_on_loop)


def _unsubscribe(active: _ActiveCoachStream, queue: asyncio.Queue[tuple[str, dict]]) -> None:
    with _active_streams_lock:
        was_subscribed = queue in active.subscribers
        active.subscribers.discard(queue)
        if was_subscribed and not active.subscribers and not active.done:
            active.cancel_event.set()
            if _active_streams.get(active.run_id) is active:
                _active_streams.pop(active.run_id, None)
            active.run_store.reset_coach(active.run_id)


def _mark_done(active: _ActiveCoachStream) -> None:
    with _active_streams_lock:
        active.done = True
        if _active_streams.get(active.run_id) is active:
            _active_streams.pop(active.run_id, None)
