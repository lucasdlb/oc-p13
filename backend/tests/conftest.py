"""Shared test fixtures.

Milvus Lite registers an `atexit` hook that logs after pytest has already closed
its logging streams, which produces "I/O operation on closed file" noise. Releasing
the Lite servers during session teardown, while logging is still open, makes that
hook a no-op.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _release_milvus_lite_servers():  # type: ignore[no-untyped-def]
    yield

    try:
        from milvus_lite.server_manager import server_manager_instance
    except ImportError:
        return

    server_manager_instance.release_all()
