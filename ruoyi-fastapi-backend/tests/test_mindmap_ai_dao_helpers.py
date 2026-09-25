"""Shared AI DAO execution must preserve scopes, locking and deletion order."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql

from module_mindmap.dao.mindmap_ai_dao import MindmapAiDao


@pytest.mark.asyncio
@pytest.mark.parametrize('for_update', [False, True])
@pytest.mark.parametrize(('method', 'table', 'key', 'owner'), [
    ('get_connector', 'mindmap_ai_connector', 'agent_key', None),
    ('get_session', 'mindmap_ai_session', 'id', 7),
    ('get_session', 'mindmap_ai_session', 'id', 0),
    ('get_session', 'mindmap_ai_session', 'id', None),
    ('get_job', 'mindmap_ai_job', 'id', 7),
    ('get_job', 'mindmap_ai_job', 'id', None),
    ('get_draft_checkpoint', 'mindmap_ai_draft_checkpoint', 'job_id', None),
    ('get_proposal', 'mindmap_ai_proposal', 'id', 7),
    ('get_proposal', 'mindmap_ai_proposal', 'id', None),
    ('get_undo', 'mindmap_ai_undo', 'proposal_id', 7),
])
async def test_shared_single_record_read_keeps_identity_owner_and_lock_refresh(
    method: str, table: str, key: str, owner: int | None, for_update: bool,
) -> None:
    record = object()
    result = Mock()
    result.scalars.return_value.first.return_value = record
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    arguments: dict[str, Any] = {'for_update': for_update}
    if method not in {'get_connector', 'get_draft_checkpoint'}:
        arguments['user_id'] = owner

    assert await getattr(MindmapAiDao, method)(db, 'record-id', **arguments) is record

    db.execute.assert_awaited_once()
    statement = db.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert f"{table}.{key} = 'record-id'" in sql
    if owner is not None:
        assert f'{table}.user_id = {owner}' in sql
    else:
        assert '.user_id =' not in sql
    assert sql.endswith('FOR UPDATE') is for_update
    assert statement.get_execution_options().get('populate_existing', False) is for_update


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['get_artifact', 'get_response'])
@pytest.mark.parametrize('owner', [None, 0, 7])
async def test_shared_unlocked_record_read_preserves_missing_result_and_scope(method: str, owner: int | None) -> None:
    result = Mock()
    result.scalars.return_value.first.return_value = None
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    assert await getattr(MindmapAiDao, method)(db, 'missing-id', user_id=owner) is None

    statement = db.execute.await_args.args[0]
    assert statement._for_update_arg is None
    assert 'populate_existing' not in statement.get_execution_options()
    assert ('.user_id =' in str(statement)) is (owner is not None)


@pytest.mark.asyncio
@pytest.mark.parametrize('full_delete', [False, True])
async def test_shared_history_delete_preserves_sql_order_direct_undo_and_counts(full_delete: bool) -> None:
    lock = Mock()
    lock.scalars.return_value = ['job-2', 'job-1']
    history_results = [SimpleNamespace(rowcount=count) for count in (2, 3, None)]
    remaining_results = [SimpleNamespace(rowcount=count) for count in (4, 5, 6, 7)]
    responses = [lock, *history_results, *remaining_results] if full_delete else history_results
    db = SimpleNamespace(execute=AsyncMock(side_effect=responses), commit=AsyncMock(), rollback=AsyncMock())
    method = MindmapAiDao.delete_job_payloads if full_delete else MindmapAiDao.delete_events_and_undos_for_jobs

    counts = await method(db, ['job-1', 'job-2'])

    statements = [call.args[0] for call in db.execute.await_args_list]
    if full_delete:
        lock_sql = str(statements.pop(0))
        assert 'ORDER BY mindmap_ai_job.id ASC' in lock_sql
        assert lock_sql.endswith('FOR UPDATE')
    tables = [statement.table.name for statement in statements]
    assert tables == [
        'mindmap_ai_undo', 'mindmap_ai_job_event', 'mindmap_ai_draft_checkpoint',
        *(['mindmap_ai_proposal', 'mindmap_ai_artifact', 'mindmap_ai_response', 'mindmap_ai_job'] if full_delete else []),
    ]
    undo_sql = str(statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert 'SELECT mindmap_ai_proposal.id' in undo_sql
    assert "mindmap_ai_proposal.job_id IN ('job-1', 'job-2')" in undo_sql
    assert "OR mindmap_ai_undo.proposal_id IN ('job-1', 'job-2')" in undo_sql
    assert counts == {
        'events': 3, 'checkpoints': 0, 'undos': 2,
        **({'proposals': 4, 'artifacts': 5, 'responses': 6, 'jobs': 7} if full_delete else {}),
    }
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_delete_stops_at_shared_history_failure_without_taking_transaction_ownership() -> None:
    lock = Mock()
    lock.scalars.return_value = ['job']
    failure = RuntimeError('checkpoint delete failed')
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[lock, SimpleNamespace(rowcount=1), SimpleNamespace(rowcount=1), failure]),
        commit=AsyncMock(), rollback=AsyncMock(),
    )

    with pytest.raises(RuntimeError) as raised:
        await MindmapAiDao.delete_job_payloads(db, ['job'])

    assert raised.value is failure
    assert [call.args[0].table.name for call in db.execute.await_args_list[1:]] == [
        'mindmap_ai_undo', 'mindmap_ai_job_event', 'mindmap_ai_draft_checkpoint',
    ]
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['delete_job_payloads', 'delete_events_and_undos_for_jobs'])
async def test_shared_deletes_with_empty_ids_do_not_access_database(method: str) -> None:
    db = SimpleNamespace(execute=AsyncMock())
    counts = await getattr(MindmapAiDao, method)(db, [])
    assert counts and all(count == 0 for count in counts.values())
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_heads_prioritize_execution_then_earliest_waiting_then_latest_terminal() -> None:
    now = datetime(2026, 9, 25)

    def job(session: str, uid: str, status: str, turn: int | None, age: int = 0) -> SimpleNamespace:
        return SimpleNamespace(session_id=session, id=uid, status=status, turn_index=turn, created_time=now + timedelta(seconds=age))

    jobs = [
        job('a', 'latest', 'completed_direct', 9), job('a', 'waiting', 'waiting_turn', 1),
        job('a', 'active-later', 'running', 5), job('a', 'active-first', 'cancel_requested', 4),
        job('b', 'waiting-later', 'waiting_turn', 5), job('b', 'waiting-first', 'waiting_turn', 3),
        job('c', 'terminal-latest', 'completed_no_change', 9), job('c', 'terminal-old', 'failed', 1),
        job('d', 'active-b', 'queued', 1), job('d', 'active-a', 'validating', 1),
        job('e', 'later-time', 'running', 1, 1), job('e', 'earlier-time', 'preparing', 1),
        job('f', 'null-turn', 'queued', None), job('f', 'first-turn', 'running', 1),
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: jobs)))

    heads = await MindmapAiDao.list_latest_jobs_for_sessions(db, ['a', 'b', 'c', 'd', 'e', 'f'])

    assert {session: head.id for session, head in heads.items()} == {
        'a': 'active-first', 'b': 'waiting-first', 'c': 'terminal-latest',
        'd': 'active-a', 'e': 'earlier-time', 'f': 'null-turn',
    }
    sql = str(db.execute.await_args.args[0])
    assert 'mindmap_ai_job.session_id IN' in sql
    assert 'ORDER BY mindmap_ai_job.session_id ASC, mindmap_ai_job.turn_index DESC, mindmap_ai_job.created_time DESC' in sql
