from backend.app.services.mongo import MongoConnection
from backend.tests.settings_factories import mongo_settings


def test_disabled_connection_is_degraded() -> None:
    connection = MongoConnection(mongo_settings(enabled=False, uri=None))

    assert connection.ok is False
    assert connection.database() is None


def test_unreachable_connection_degrades_without_raising() -> None:
    settings = mongo_settings(
        uri="mongodb://localhost:1",
        connect_timeout_seconds=0.05,
    )

    connection = MongoConnection(settings)

    assert connection.ok is False
    assert connection.database() is None


def test_close_is_a_noop_when_degraded() -> None:
    connection = MongoConnection(mongo_settings(enabled=False, uri=None))

    connection.close()

    assert connection.ok is False
