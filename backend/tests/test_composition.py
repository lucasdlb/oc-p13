import pytest

from backend.app.composition import RuntimeServices
from backend.app.core.settings import Settings
from backend.app.main import create_app


class _Resource:
    def __init__(self, *, warmup_error: Exception | None = None, close_error: Exception | None = None) -> None:
        self.warmup_error = warmup_error
        self.close_error = close_error
        self.warmed = False
        self.closed = False

    def warmup(self) -> None:
        self.warmed = True
        if self.warmup_error:
            raise self.warmup_error

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            raise self.close_error


@pytest.mark.anyio
async def test_runtime_warmup_continues_after_one_provider_fails() -> None:
    lichess = _Resource()
    llm = _Resource(warmup_error=RuntimeError("llm unavailable"))
    coach = _Resource()
    rag = _Resource()
    runtime = RuntimeServices(
        lichess,
        llm,
        coach,
        rag,
        _Resource(),
        _Resource(),
        _Resource(),
        _Resource(),
        _Resource(),
        None,
        _Resource(),
        True,
    )  # type: ignore[arg-type]

    await runtime.warmup()

    assert llm.warmed
    assert rag.warmed


def test_runtime_close_attempts_every_resource() -> None:
    lichess = _Resource(close_error=RuntimeError("close failed"))
    llm = _Resource()
    coach = _Resource()
    rag = _Resource()
    runtime = RuntimeServices(
        lichess,
        llm,
        coach,
        rag,
        _Resource(),
        _Resource(),
        _Resource(),
        _Resource(),
        _Resource(),
        None,
        _Resource(),
        True,
    )  # type: ignore[arg-type]

    runtime.close()

    assert lichess.closed
    assert llm.closed
    assert rag.closed


def test_create_app_accepts_injected_settings() -> None:
    app = create_app(Settings())

    assert app.title == "POC Agent d'ouvertures FFE"
