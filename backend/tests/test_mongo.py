from backend.app.core.settings import MongoSettings
from backend.app.services.mongo import MongoConnection


def test_disabled_connection_is_degraded() -> None:
    connection = MongoConnection(MongoSettings(enabled=False))

    assert connection.ok is False
    assert connection.database() is None


def test_unreachable_connection_degrades_without_raising() -> None:
    settings = MongoSettings(
        uri="mongodb://localhost:1",
        connect_timeout_seconds=0.05,
    )

    connection = MongoConnection(settings)

    assert connection.ok is False
    assert connection.database() is None


def test_close_is_a_noop_when_degraded() -> None:
    connection = MongoConnection(MongoSettings(enabled=False))

    connection.close()

    assert connection.ok is False
