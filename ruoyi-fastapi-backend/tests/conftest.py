"""Keep unit tests isolated from the configured application database."""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine


@pytest.fixture(autouse=True)
def forbid_unexpected_database_connections() -> Iterator[None]:
    if os.getenv('MINDMAP_DB_INTEGRATION') == '1':
        yield
        return

    attempted = False

    def reject_connection(*_args: object) -> None:
        nonlocal attempted
        attempted = True
        raise AssertionError('Unit tests must mock database I/O; real database integration is opt-in')

    event.listen(Engine, 'do_connect', reject_connection)
    try:
        yield
    finally:
        event.remove(Engine, 'do_connect', reject_connection)
        # Background job code can catch the connection exception. Still fail
        # the test so a swallowed error cannot conceal incomplete isolation.
        if attempted:
            pytest.fail('Unexpected real database connection; mock the owning service/session boundary')
