"""AI 脑图实时预览与事件隐私边界。"""

import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from redis.cluster import key_slot
from sqlalchemy.exc import IntegrityError

from exceptions.exception import ServiceException
from module_mindmap.ai.change_summary import summarize_committed_node_changes
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.dao.mindmap_ai_dao import MindmapAiDao
from module_mindmap.service.mindmap_ai_service import (
    _CURRENT_JOB_EXECUTION_EPOCH,
    AI_DRAFT_PREVIEW_FRAME_TTL_SECONDS,
    AI_DRAFT_PREVIEW_TTL_SECONDS,
    MindmapAiService,
    MindmapAiTaskManager,
    _direct_job_change_result,
    _event_json,
    _safe_event_payload,
)


def _document(text: str = '实时脑图') -> dict:
    return {
        'root': {'data': {'uid': 'root', 'text': text}, 'children': []},
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }


async def _accept_checkpoint(_db: object, values: dict) -> tuple[SimpleNamespace, bool]:
    return SimpleNamespace(**values), True


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.expirations[key] = ex

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)
            self.expirations.pop(key, None)

    async def eval(  # noqa: PLR0911, PLR0912
        self,
        script: str,
        numkeys: int,
        *items: object,
    ) -> int:
        keys = [str(item) for item in items[:numkeys]]
        args = [str(item) for item in items[numkeys:]]
        async with self._lock:
            if 'mindmap-ai:publish-draft-execution' in script:
                terminal_key, execution_key = keys
                if terminal_key in self.values:
                    return 0
                current = self.values.get(execution_key)
                if current is not None:
                    try:
                        if int(current) > int(args[0]):
                            return 0
                    except ValueError:
                        return 0
                self.values[execution_key] = args[0]
                self.expirations[execution_key] = int(args[1])
                return 1

            terminal_key, execution_key, latest_key = keys[:3]
            expected_epoch = args[0]
            terminal_epoch = self.values.get(terminal_key)
            is_store = 'mindmap-ai:store-draft-preview' in script
            current_epoch = self.values.get(execution_key)
            if is_store:
                if terminal_epoch is not None:
                    return -1
                if current_epoch != expected_epoch:
                    return -2
            else:
                if terminal_epoch is not None and terminal_epoch != expected_epoch:
                    return -1
                if current_epoch is not None and current_epoch != expected_epoch:
                    return -2

            current_value = self.values.get(latest_key)
            if current_value is not None and not is_store and current_epoch is None:
                current_payload = json.loads(current_value)
                value_epoch = current_payload.get('executionEpoch')
                if value_epoch is not None and str(value_epoch) != expected_epoch:
                    return -3
            expected_present = args[1] == '1'
            if expected_present != (current_value is not None):
                return 0
            if expected_present and current_value != args[2]:
                return 0

            if is_store:
                exact_key = keys[3]
                for key in keys[4:]:
                    await self.delete(key)
                if args[3] == '1':
                    self.values[exact_key] = args[4]
                    self.expirations[exact_key] = int(args[5])
                else:
                    await self.delete(exact_key)
                self.values[latest_key] = args[6]
                self.expirations[latest_key] = int(args[7])
                return 1

            if 'mindmap-ai:mark-draft-terminal' in script:
                self.values[terminal_key] = expected_epoch
                self.expirations[terminal_key] = int(args[3])
            for key in keys[2:]:
                await self.delete(key)
            return 1


class _TerminalRaceRedis(_FakeRedis):
    async def eval(self, script: str, numkeys: int, *items: object) -> int:
        if 'mindmap-ai:store-draft-preview' in script:
            terminal_key = MindmapAiTaskManager._draft_preview_terminal_key(
                'job-terminal-race',
            )
            self.values[terminal_key] = '1'
        return await super().eval(script, numkeys, *items)


class _FailingTerminalRedis(_FakeRedis):
    async def eval(self, script: str, numkeys: int, *items: object) -> int:
        if 'mindmap-ai:mark-draft-terminal' in script:
            raise ConnectionError('terminal write failed')
        return await super().eval(script, numkeys, *items)


async def _publish_execution(job_id: str, execution_epoch: int = 1) -> None:
    assert await MindmapAiTaskManager._publish_execution_epoch(job_id, execution_epoch)


def test_all_draft_preview_lua_keys_share_one_redis_cluster_slot() -> None:
    job_id = '77d93c56-bdf5-4b52-8574-d313c654cd0e'
    keys = [
        MindmapAiTaskManager._draft_preview_key(job_id),
        MindmapAiTaskManager._draft_preview_terminal_key(job_id),
        MindmapAiTaskManager._draft_preview_execution_key(job_id),
        MindmapAiTaskManager._draft_preview_version_key(job_id, 1),
        MindmapAiTaskManager._draft_preview_version_key(job_id, 999),
    ]

    assert f'{{{job_id}}}' in keys[0]
    assert len({key_slot(key.encode()) for key in keys}) == 1


def test_event_payload_uses_allowlist_and_never_serializes_mindmap_content() -> None:
    unsafe = {
        'status': 'running',
        'progress': 40,
        'toolName': 'update_nodes',
        'previewVersion': 3,
        'previewAvailable': True,
        'summary': {
            'nodeCount': 4,
            'treeDepth': 2,
            'title': '不能写入事件的标题',
        },
        'errorMessage': '经过映射的安全错误摘要',
        'usage': {
            'inputTokens': 10,
            'outputTokens': 5,
            'totalTokens': 15,
            'reasoningTokens': 999,
            'rawUsage': {'secret': '不得写入'},
        },
        'prompt': '用户的私密提示词',
        'operations': [{'payload': {'patch': {'text': '机密节点正文'}}}],
        'previewState': _document('机密节点正文'),
        'issues': [{'path': 'root.children[0]', 'message': '机密节点正文'}],
    }

    safe = _safe_event_payload(unsafe)

    assert safe == {
        'status': 'running',
        'progress': 40,
        'toolName': 'update_nodes',
        'previewVersion': 3,
        'previewAvailable': True,
        'summary': {'nodeCount': 4, 'treeDepth': 2},
        'errorMessage': '经过映射的安全错误摘要',
        'usage': {'inputTokens': 10, 'outputTokens': 5, 'totalTokens': 15},
    }
    serialized = _event_json(unsafe)
    assert '用户的私密提示词' not in serialized
    assert '机密节点正文' not in serialized
    assert 'root.children' not in serialized
    assert 'reasoningTokens' not in serialized
    assert 'rawUsage' not in serialized


def test_event_payload_preserves_direct_change_summary_without_content() -> None:
    safe = _safe_event_payload({
        'changeSummary': {
            'added': 2,
            'updated': 3,
            'moved': 1,
            'deleted': 4,
            'total': 10,
            'private': 'drop me',
        },
        'directCommit': {
            'operationGroupId': 'ai:job:1',
            'changeSummary': {'createdCount': 2, 'updatedCount': 3},
            'affectedUids': ['node-1'],
        },
    })
    assert safe['changeSummary'] == {
        'added': 2,
        'updated': 3,
        'moved': 1,
        'deleted': 4,
        'total': 10,
    }
    assert safe['directCommit']['changeSummary'] == {
        'added': 2,
        'updated': 3,
        'moved': 0,
        'deleted': 0,
        'total': 5,
    }


def test_canonical_change_summary_counts_moved_uids_and_deleted_subtrees() -> None:
    assert summarize_committed_node_changes([[
        {'type': 'node.create', 'nodeUid': 'new'},
        {
            'type': 'node.update',
            'payload': {
                'dataChanged': True,
                'childrenChanged': False,
            },
        },
        {
            'type': 'node.update',
            'payload': {
                'dataChanged': False,
                'childrenChanged': True,
                'oldChildUids': ['a', 'b'],
                'childUids': ['b'],
            },
        },
        {
            'type': 'node.delete',
            'payload': {'deletedNodeUids': ['gone', 'leaf']},
        },
    ]]) == {
        'added': 1,
        'updated': 1,
        'moved': 1,
        'deleted': 2,
        'total': 5,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize('log_evidence', ['complete', 'incomplete', 'missing'])
async def test_direct_job_change_result_versions_legacy_log_recovery(
    monkeypatch: pytest.MonkeyPatch, log_evidence: str,
) -> None:
    job = SimpleNamespace(id='job-legacy', source_mindmap_id=9)
    expected_summary = {'added': 1, 'updated': 0, 'moved': 0, 'deleted': 2, 'total': 3}
    pages = [[SimpleNamespace(
        sequence=1,
        event_type='draft_changed',
        payload_json=json.dumps({
            'directCommit': {
                'operationGroupId': 'ai:job-legacy:1',
                'changeSummary': expected_summary,
            },
        }),
    )], []]
    monkeypatch.setattr(
        MindmapAiDao,
        'list_events',
        AsyncMock(side_effect=pages),
    )
    operations = [
        {'type': 'node.create', 'nodeUid': 'new'},
        {'type': 'node.delete', 'payload': {'deletedNodeUids': ['old', 'leaf']}},
    ]
    if log_evidence == 'complete':
        operations[1]['nodeUid'] = 'old'
    monkeypatch.setattr(
        'module_mindmap.service.mindmap_ai_service.MindmapContentDao.get_changes_by_mutations',
        AsyncMock(return_value=[SimpleNamespace(
            client_mutation_id='ai:job-legacy:1', operations=operations,
        )] if log_evidence != 'missing' else []),
    )
    assert await _direct_job_change_result(object(), job) == {
        'changeSummary': expected_summary,
        'changeSummaryVersion': 2 if log_evidence == 'complete' else 1,
    }


def test_event_payload_rejects_invalid_token_usage_values() -> None:
    safe = _safe_event_payload({
        'usage': {
            'inputTokens': -1,
            'outputTokens': True,
            'totalTokens': 12.5,
            'reasoningTokens': 500,
        },
    })

    assert safe == {'usage': {}}


def test_event_payload_drops_non_finite_provider_scalars() -> None:
    safe = _safe_event_payload({
        'progress': float('nan'),
        'summary': {
            'nodeCount': 3,
            'treeDepth': float('inf'),
        },
    })

    assert safe == {'summary': {'nodeCount': 3}}
    # The durable serializer must never be able to emit non-standard JSON.
    assert 'NaN' not in _event_json({
        'progress': float('nan'),
        'summary': {'treeDepth': float('inf')},
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(('summary', 'expected'), [
    ({'nodeCount': float('nan'), 'treeDepth': float('inf')}, {}),
    ({'nodeCount': 3, 'status': 'running', 'prompt': 'private', 'changeSummary': {'added': 9}},
     {'nodeCount': 3, 'status': 'running'}),
    (None, {}),
])
async def test_checkpoint_and_redis_preview_share_safe_summary_projection(
    summary: dict | None, expected: dict,
) -> None:
    checkpoint = MindmapAiTaskManager._draft_checkpoint_values(
        job_id='job-nonfinite-summary',
        document=_document(),
        operations=[],
        initial_state=None,
        preview_version=1,
        preview_epoch=1,
        summary=summary,
        expires_time=datetime.now() + timedelta(hours=1),
    )
    assert json.loads(checkpoint['summary_json']) == expected
    recovered = MindmapAiTaskManager._draft_checkpoint_preview(
        SimpleNamespace(**checkpoint, update_time=datetime.now()),
    )
    assert recovered['summary'] == expected

    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-nonfinite-summary')
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-nonfinite-summary',
            _document(),
            operation_cursor=1,
            expected_execution_epoch=1,
            summary=summary,
        ) is True
    finally:
        MindmapAiTaskManager._redis = None
    preview = json.loads(
        redis.values[MindmapAiTaskManager._draft_preview_key('job-nonfinite-summary')],
    )
    assert preview['summary'] == expected


@pytest.mark.asyncio
async def test_draft_preview_is_kept_in_short_lived_redis_snapshot() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-1')
        stored = await MindmapAiTaskManager._store_draft_preview(
            'job-1',
            _document(),
            operation_cursor=7,
            expected_execution_epoch=1,
            summary={'nodeCount': 1, 'title': '不得复制到摘要'},
        )
        preview = await MindmapAiTaskManager.get_draft_preview('job-1')
    finally:
        MindmapAiTaskManager._redis = None

    assert stored is True
    assert preview is not None
    assert preview['operationCursor'] == 7  # noqa: PLR2004
    assert preview['document']['root']['data']['text'] == '实时脑图'
    assert preview['summary'] == {'nodeCount': 1}
    latest_key = MindmapAiTaskManager._draft_preview_key('job-1')
    version_key = MindmapAiTaskManager._draft_preview_version_key('job-1', 7)
    assert redis.expirations[latest_key] == AI_DRAFT_PREVIEW_TTL_SECONDS
    assert (
        redis.expirations[version_key]
        == AI_DRAFT_PREVIEW_FRAME_TTL_SECONDS
    )


@pytest.mark.asyncio
async def test_draft_preview_versions_are_replayable_without_regressing_latest() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-versions')
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-versions',
            _document('版本 7'),
            operation_cursor=7,
            expected_execution_epoch=1,
        )
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-versions',
            _document('迟到的版本 3'),
            operation_cursor=3,
            expected_execution_epoch=1,
        )

        latest = await MindmapAiTaskManager.get_draft_preview('job-versions')
        version_three = await MindmapAiTaskManager.get_draft_preview('job-versions', 3)
        missing = await MindmapAiTaskManager.get_draft_preview('job-versions', 4)
    finally:
        MindmapAiTaskManager._redis = None

    assert latest is not None
    assert latest['operationCursor'] == 7  # noqa: PLR2004
    assert latest['document']['root']['data']['text'] == '版本 7'
    assert latest['availableVersions'] == [3, 7]
    assert version_three is not None
    assert version_three['operationCursor'] == 3  # noqa: PLR2004
    assert version_three['document']['root']['data']['text'] == '迟到的版本 3'
    assert missing is None


@pytest.mark.asyncio
async def test_recovered_run_allocates_monotonic_preview_epoch_and_preserves_old_frame() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-recovered')
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-recovered',
            _document('恢复前版本 7'),
            operation_cursor=7,
            expected_execution_epoch=1,
            preview_epoch=1,
        )

        run = await MindmapAiTaskManager._begin_draft_preview_run(
            'job-recovered',
            # 持久化 SSE 历史可能比短 TTL Redis 帧更新，恢复时必须以两者
            # 的最大版本为准。
            persisted_version=12,
            persisted_epoch=3,
        )
        initial_coordinates = MindmapAiTaskManager._draft_preview_coordinates(
            'job-recovered',
            0,
        )
        assert run.epoch == 4  # noqa: PLR2004
        assert initial_coordinates == (13, 4)
        await _publish_execution('job-recovered', 4)
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-recovered',
            _document('恢复后初始帧'),
            operation_cursor=initial_coordinates[0],
            expected_execution_epoch=4,
            preview_epoch=initial_coordinates[1],
        )

        changed_coordinates = MindmapAiTaskManager._draft_preview_coordinates(
            'job-recovered',
            3,
        )
        assert changed_coordinates == (16, 4)
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-recovered',
            _document('恢复后版本 16'),
            operation_cursor=changed_coordinates[0],
            expected_execution_epoch=4,
            preview_epoch=changed_coordinates[1],
        )

        latest = await MindmapAiTaskManager.get_draft_preview('job-recovered')
        old_frame = await MindmapAiTaskManager.get_draft_preview('job-recovered', 7)
        recovered_frame = await MindmapAiTaskManager.get_draft_preview('job-recovered', 13)
    finally:
        MindmapAiTaskManager._draft_preview_runs.pop('job-recovered', None)
        MindmapAiTaskManager._redis = None

    assert latest is not None
    assert latest['operationCursor'] == 16  # noqa: PLR2004
    assert latest['previewEpoch'] == 4  # noqa: PLR2004
    assert latest['document']['root']['data']['text'] == '恢复后版本 16'
    assert old_frame is not None
    assert old_frame['document']['root']['data']['text'] == '恢复前版本 7'
    assert recovered_frame is not None
    assert recovered_frame['document']['root']['data']['text'] == '恢复后初始帧'


def test_recovery_checkpoint_uses_historical_maxima_after_legacy_regression() -> None:
    version, epoch = MindmapAiTaskManager._draft_preview_history_checkpoint([
        json.dumps({'previewVersion': 12, 'previewEpoch': 1}),
        json.dumps({'previewVersion': 0, 'previewEpoch': 2}),
        json.dumps({'previewVersion': True, 'previewEpoch': '3'}),
        '无效 JSON',
    ])

    assert version == 12  # noqa: PLR2004
    assert epoch == 2  # noqa: PLR2004


@pytest.mark.asyncio
async def test_deleting_draft_preview_removes_latest_and_versioned_frames() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-delete')
        await MindmapAiTaskManager._store_draft_preview(
            'job-delete',
            _document(),
            operation_cursor=2,
            expected_execution_epoch=1,
        )
        await MindmapAiTaskManager.delete_draft_preview('job-delete', 1)
    finally:
        MindmapAiTaskManager._redis = None

    assert MindmapAiTaskManager._draft_preview_key('job-delete') not in redis.values
    assert (
        MindmapAiTaskManager._draft_preview_version_key('job-delete', 2)
        not in redis.values
    )
    assert redis.values[
        MindmapAiTaskManager._draft_preview_execution_key('job-delete')
    ] == '1'


@pytest.mark.asyncio
async def test_draft_frame_cache_evicts_old_versions_at_count_limit() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-frame-count')
        with patch(
            'module_mindmap.service.mindmap_ai_service.AI_DRAFT_PREVIEW_MAX_FRAMES',
            2,
        ):
            for version in (1, 2, 3):
                await MindmapAiTaskManager._store_draft_preview(
                    'job-frame-count',
                    _document(f'版本 {version}'),
                    operation_cursor=version,
                    expected_execution_epoch=1,
                )
        latest = await MindmapAiTaskManager.get_draft_preview('job-frame-count')
        first = await MindmapAiTaskManager.get_draft_preview('job-frame-count', 1)
        second = await MindmapAiTaskManager.get_draft_preview('job-frame-count', 2)
        third = await MindmapAiTaskManager.get_draft_preview('job-frame-count', 3)
    finally:
        MindmapAiTaskManager._redis = None

    assert latest is not None
    assert latest['availableVersions'] == [2, 3]
    assert first is None
    assert second is not None
    assert third is not None


@pytest.mark.asyncio
async def test_draft_frame_cache_falls_back_to_bounded_latest_when_frame_budget_is_too_small() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-frame-bytes')
        with patch(
            'module_mindmap.service.mindmap_ai_service.AI_DRAFT_PREVIEW_MAX_TOTAL_BYTES',
            1,
        ):
            stored = await MindmapAiTaskManager._store_draft_preview(
                'job-frame-bytes',
                _document('只能保留最新快照'),
                operation_cursor=9,
                expected_execution_epoch=1,
            )
        latest = await MindmapAiTaskManager.get_draft_preview('job-frame-bytes')
        frame = await MindmapAiTaskManager.get_draft_preview('job-frame-bytes', 9)
    finally:
        MindmapAiTaskManager._redis = None

    assert stored is True
    assert latest is not None
    assert latest['operationCursor'] == 9  # noqa: PLR2004
    assert latest['availableVersions'] == []
    assert frame is None


@pytest.mark.asyncio
async def test_terminal_tombstone_wins_race_with_late_post_commit_cache_write() -> None:
    redis = _TerminalRaceRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-terminal-race')
        stored = await MindmapAiTaskManager._store_draft_preview(
            'job-terminal-race',
            _document('迟到正文'),
            operation_cursor=9,
            expected_execution_epoch=1,
        )
    finally:
        MindmapAiTaskManager._redis = None

    assert stored is False
    assert MindmapAiTaskManager._draft_preview_key('job-terminal-race') not in redis.values
    assert (
        MindmapAiTaskManager._draft_preview_version_key('job-terminal-race', 9)
        not in redis.values
    )
    assert redis.values[
        MindmapAiTaskManager._draft_preview_terminal_key('job-terminal-race')
    ] == '1'


@pytest.mark.asyncio
async def test_old_execution_epoch_cannot_write_delete_or_terminalize_new_cache() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-epoch-cas', 1)
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-epoch-cas',
            _document('第一轮'),
            operation_cursor=1,
            expected_execution_epoch=1,
        )
        await _publish_execution('job-epoch-cas', 2)
        stale_delete_before_first_frame = await MindmapAiTaskManager.delete_draft_preview(
            'job-epoch-cas',
            1,
        )
        stale_terminal_before_first_frame = await MindmapAiTaskManager.mark_draft_terminal(
            'job-epoch-cas',
            1,
        )
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-epoch-cas',
            _document('第二轮'),
            operation_cursor=2,
            expected_execution_epoch=2,
        )
        stale_publish = await MindmapAiTaskManager._publish_execution_epoch(
            'job-epoch-cas',
            1,
        )

        stale_write = await MindmapAiTaskManager._store_draft_preview(
            'job-epoch-cas',
            _document('迟到的第一轮'),
            operation_cursor=3,
            expected_execution_epoch=1,
        )
        stale_delete = await MindmapAiTaskManager.delete_draft_preview(
            'job-epoch-cas',
            1,
        )
        stale_terminal = await MindmapAiTaskManager.mark_draft_terminal(
            'job-epoch-cas',
            1,
        )
        latest = await MindmapAiTaskManager.get_draft_preview('job-epoch-cas')
        current_terminal = await MindmapAiTaskManager.mark_draft_terminal(
            'job-epoch-cas',
            2,
        )
        after_terminal = await MindmapAiTaskManager.get_draft_preview('job-epoch-cas')
    finally:
        MindmapAiTaskManager._redis = None

    assert stale_delete_before_first_frame is False
    assert stale_terminal_before_first_frame is False
    assert stale_publish is False
    assert stale_write is False
    assert stale_delete is False
    assert stale_terminal is False
    assert latest is not None
    assert latest['executionEpoch'] == 2  # noqa: PLR2004
    assert latest['document']['root']['data']['text'] == '第二轮'
    assert current_terminal is True
    assert after_terminal is None
    assert redis.values[
        MindmapAiTaskManager._draft_preview_terminal_key('job-epoch-cas')
    ] == '2'


@pytest.mark.asyncio
async def test_new_epoch_can_terminalize_previous_latest_before_writing_first_frame() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-terminal-takeover', 1)
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-terminal-takeover',
            _document('旧轮次 latest'),
            operation_cursor=7,
            expected_execution_epoch=1,
        )
        await _publish_execution('job-terminal-takeover', 2)

        marked = await MindmapAiTaskManager.mark_draft_terminal(
            'job-terminal-takeover',
            2,
        )
    finally:
        MindmapAiTaskManager._redis = None

    assert marked is True
    assert MindmapAiTaskManager._draft_preview_key('job-terminal-takeover') not in redis.values
    assert redis.values[
        MindmapAiTaskManager._draft_preview_terminal_key('job-terminal-takeover')
    ] == '2'


@pytest.mark.asyncio
async def test_terminal_script_failure_does_not_delete_unfenced_draft() -> None:
    redis = _FailingTerminalRedis()
    MindmapAiTaskManager.configure_redis(redis)
    try:
        await _publish_execution('job-terminal-failure', 4)
        assert await MindmapAiTaskManager._store_draft_preview(
            'job-terminal-failure',
            _document('仍需保留到 TTL'),
            operation_cursor=6,
            expected_execution_epoch=4,
        )

        marked = await MindmapAiTaskManager.mark_draft_terminal(
            'job-terminal-failure',
            4,
        )
    finally:
        MindmapAiTaskManager._redis = None

    assert marked is False
    assert MindmapAiTaskManager._draft_preview_key('job-terminal-failure') in redis.values
    assert (
        MindmapAiTaskManager._draft_preview_version_key('job-terminal-failure', 6)
        in redis.values
    )
    assert (
        MindmapAiTaskManager._draft_preview_terminal_key('job-terminal-failure')
        not in redis.values
    )


@pytest.mark.asyncio
async def test_draft_changed_event_stores_snapshot_but_persists_only_metadata() -> None:
    redis = _FakeRedis()
    database = SimpleNamespace(commit=AsyncMock())

    class _SessionFactory:
        def __call__(self) -> '_SessionFactory':
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return database

        async def __aexit__(self, *_args: object) -> None:
            return None

    MindmapAiTaskManager.configure_redis(redis)
    await _publish_execution('job-2')
    epoch_token = _CURRENT_JOB_EXECUTION_EPOCH.set(1)
    try:
        with (
            patch(
                'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
                new=_SessionFactory(),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
                new=AsyncMock(),
            ) as add_event,
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.upsert_draft_checkpoint',
                new=AsyncMock(side_effect=_accept_checkpoint),
            ) as upsert_checkpoint,
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(return_value=SimpleNamespace(
                    status='running',
                    execution_epoch=1,
                    expires_time=datetime.now() + timedelta(days=1),
                )),
            ),
        ):
            await MindmapAiTaskManager._emit('job-2', 'draft_changed', {
                'operationCursor': 2,
                'operations': [{'payload': {'patch': {'text': '私密节点'}}}],
                'previewState': _document('私密节点'),
                'summary': {'nodeCount': 1, 'treeDepth': 1},
                'toolName': 'update_nodes',
            })
    finally:
        _CURRENT_JOB_EXECUTION_EPOCH.reset(epoch_token)
        MindmapAiTaskManager._redis = None

    payload = json.loads(add_event.await_args.args[3])
    assert payload == {
        'summary': {'nodeCount': 1, 'treeDepth': 1},
        'toolName': 'update_nodes',
        'changeCount': 1,
        'previewVersion': 2,
        'previewEpoch': 1,
        'previewAvailable': True,
    }
    assert '私密节点' not in add_event.await_args.args[3]
    stored = json.loads(redis.values[MindmapAiTaskManager._draft_preview_key('job-2')])
    assert stored['document']['root']['data']['text'] == '私密节点'
    checkpoint_values = upsert_checkpoint.await_args.args[1]
    assert '私密节点' not in checkpoint_values['document_ciphertext']
    assert '私密节点' not in checkpoint_values['operations_ciphertext']
    assert checkpoint_values['document_hash']


@pytest.mark.asyncio
async def test_draft_checkpoint_and_event_commit_before_redis_cache() -> None:
    redis = _FakeRedis()
    database = SimpleNamespace(
        commit=AsyncMock(side_effect=RuntimeError('commit failed')),
        rollback=AsyncMock(),
    )

    class _SessionFactory:
        def __call__(self) -> '_SessionFactory':
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return database

        async def __aexit__(self, *_args: object) -> None:
            return None

    MindmapAiTaskManager.configure_redis(redis)
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=AsyncMock(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.upsert_draft_checkpoint',
            new=AsyncMock(side_effect=_accept_checkpoint),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(
                status='running',
                expires_time=datetime.now() + timedelta(days=1),
            )),
        ),
        pytest.raises(RuntimeError, match='commit failed'),
    ):
        await MindmapAiTaskManager._emit('job-commit', 'draft_changed', {
            'operationCursor': 1,
            'operations': [],
            'previewState': _document('尚未提交'),
        })
    MindmapAiTaskManager._redis = None

    assert redis.values == {}


@pytest.mark.asyncio
async def test_direct_mutation_broadcast_waits_for_atomic_event_commit() -> None:
    redis = _FakeRedis()
    trace: list[str] = []
    committed_revision = 7
    database = SimpleNamespace(
        commit=AsyncMock(side_effect=lambda: trace.append('commit')),
        rollback=AsyncMock(),
    )

    class _SessionFactory:
        def __call__(self) -> '_SessionFactory':
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return database

        async def __aexit__(self, *_args: object) -> None:
            return None

    job = SimpleNamespace(
        status='running',
        execution_epoch=1,
        expires_time=datetime.now() + timedelta(days=1),
        source_mindmap_id=42,
    )
    MindmapAiTaskManager.configure_redis(redis)
    await _publish_execution('job-direct-atomic')
    epoch_token = _CURRENT_JOB_EXECUTION_EPOCH.set(1)
    try:
        async def stage_direct_commit(
            _db: object, _job: object, _operations: list[dict], _cursor: int,
        ) -> dict:
            trace.append('stage')
            return {
                'contentRevision': committed_revision,
                'operationGroupId': 'ai:job-direct-atomic:1',
                '_nextExpectedRevision': committed_revision,
                '_deferredBroadcast': {},
                '_committedDocument': _document('直写提交'),
            }

        async def publish_direct_commit(_mindmap_id: int, _result: dict) -> None:
            trace.append('publish')

        with (
            patch(
                'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
                new=_SessionFactory(),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(return_value=job),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.upsert_draft_checkpoint',
                new=AsyncMock(side_effect=_accept_checkpoint),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
                new=AsyncMock(return_value=SimpleNamespace(sequence=1)),
            ),
            patch.object(
                MindmapAiTaskManager,
                '_commit_direct_draft',
                new=stage_direct_commit,
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiMutationGateway.publish_direct_commit',
                new=publish_direct_commit,
            ),
            patch.object(
                MindmapAiTaskManager,
                '_store_draft_preview',
                new=AsyncMock(side_effect=RuntimeError('redis unavailable')),
            ) as store_preview,
        ):
            await MindmapAiTaskManager._emit('job-direct-atomic', 'draft_changed', {
                'operationCursor': 1,
                'operations': [{'type': 'update_node'}],
                'previewState': _document('直写提交'),
            })
    finally:
        _CURRENT_JOB_EXECUTION_EPOCH.reset(epoch_token)
        MindmapAiTaskManager._redis = None

    assert trace == ['stage', 'commit', 'publish']
    store_preview.assert_awaited_once()
    assert MindmapAiTaskManager._direct_commit_revisions['job-direct-atomic'] == committed_revision
    MindmapAiTaskManager._direct_commit_revisions.pop('job-direct-atomic', None)


@pytest.mark.asyncio
async def test_direct_mutation_rolls_back_when_event_is_suppressed() -> None:
    redis = _FakeRedis()
    database = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    class _SessionFactory:
        def __call__(self) -> '_SessionFactory':
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return database

        async def __aexit__(self, *_args: object) -> None:
            return None

    job = SimpleNamespace(
        status='running',
        execution_epoch=1,
        expires_time=datetime.now() + timedelta(days=1),
        source_mindmap_id=42,
    )
    MindmapAiTaskManager.configure_redis(redis)
    await _publish_execution('job-direct-suppressed')
    epoch_token = _CURRENT_JOB_EXECUTION_EPOCH.set(1)
    try:
        with (
            patch(
                'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
                new=_SessionFactory(),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(return_value=job),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.upsert_draft_checkpoint',
                new=AsyncMock(side_effect=_accept_checkpoint),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                MindmapAiTaskManager,
                '_commit_direct_draft',
                new=AsyncMock(return_value={
                    'contentRevision': 7,
                    '_nextExpectedRevision': 7,
                    '_deferredBroadcast': {},
                    '_committedDocument': _document('终态竞态'),
                }),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiMutationGateway.publish_direct_commit',
                new=AsyncMock(),
            ) as publish,
        ):
            await MindmapAiTaskManager._emit('job-direct-suppressed', 'draft_changed', {
                'operationCursor': 1,
                'operations': [{'type': 'update_node'}],
                'previewState': _document('终态竞态'),
            })
    finally:
        _CURRENT_JOB_EXECUTION_EPOCH.reset(epoch_token)
        MindmapAiTaskManager._redis = None

    database.commit.assert_not_awaited()
    database.rollback.assert_awaited_once()
    publish.assert_not_awaited()
    assert 'job-direct-suppressed' not in MindmapAiTaskManager._direct_commit_revisions


@pytest.mark.asyncio
async def test_checkpoint_coordinate_conflict_is_a_domain_error_not_event_outage() -> None:
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    class _SessionFactory:
        def __call__(self) -> '_SessionFactory':
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return database

        async def __aexit__(self, *_args: object) -> None:
            return None

    token = _CURRENT_JOB_EXECUTION_EPOCH.set(1)
    try:
        with (
            patch(
                'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
                new=_SessionFactory(),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(return_value=SimpleNamespace(
                    status='running',
                    execution_epoch=1,
                    expires_time=datetime.now() + timedelta(days=1),
                )),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.upsert_draft_checkpoint',
                new=AsyncMock(side_effect=ValueError('AI 草稿检查点坐标冲突')),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
                new=AsyncMock(),
            ) as add_event,
            pytest.raises(MindmapArtifactError) as error,
        ):
            await MindmapAiTaskManager._emit('job-checkpoint-conflict', 'draft_changed', {
                'operationCursor': 1,
                'operations': [],
                'previewState': _document('冲突帧'),
            })
    finally:
        _CURRENT_JOB_EXECUTION_EPOCH.reset(token)

    assert error.value.code == 'AI_DOCUMENT_CONFLICT'
    assert '实时事件持久化失败' not in str(error.value)
    database.rollback.assert_awaited_once()
    add_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_sequence_integrity_conflict_is_a_domain_error_not_event_outage() -> None:
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    class _SessionFactory:
        def __call__(self) -> '_SessionFactory':
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return database

        async def __aexit__(self, *_args: object) -> None:
            return None

    token = _CURRENT_JOB_EXECUTION_EPOCH.set(1)
    try:
        with (
            patch(
                'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
                new=_SessionFactory(),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(return_value=SimpleNamespace(
                    status='running',
                    execution_epoch=1,
                    expires_time=datetime.now() + timedelta(days=1),
                )),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
                new=AsyncMock(side_effect=IntegrityError(
                    'INSERT', {}, Exception('duplicate event sequence'),
                )),
            ) as add_event,
            pytest.raises(MindmapArtifactError) as error,
        ):
            await MindmapAiTaskManager._emit(
                'job-event-sequence-conflict',
                'tool_completed',
                {'toolName': 'validate_draft'},
            )
    finally:
        _CURRENT_JOB_EXECUTION_EPOCH.reset(token)

    assert error.value.code == 'AI_DOCUMENT_CONFLICT'
    assert '实时事件持久化失败' not in str(error.value)
    database.rollback.assert_awaited_once()
    add_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_oversized_checkpoint_never_stages_event_or_checkpoint() -> None:
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    class _SessionFactory:
        def __call__(self) -> '_SessionFactory':
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return database

        async def __aexit__(self, *_args: object) -> None:
            return None

    add_event = AsyncMock()
    upsert_checkpoint = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
            new=_SessionFactory(),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
            new=add_event,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.upsert_draft_checkpoint',
            new=upsert_checkpoint,
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(
                status='running',
                expires_time=datetime.now() + timedelta(days=1),
            )),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.AI_DRAFT_PREVIEW_MAX_LATEST_BYTES',
            1,
        ),
        pytest.raises(MindmapArtifactError, match='容量上限'),
    ):
        await MindmapAiTaskManager._emit('job-too-large', 'draft_changed', {
            'operationCursor': 1,
            'operations': [],
            'previewState': _document('超限'),
        })

    upsert_checkpoint.assert_not_awaited()
    add_event.assert_not_awaited()
    database.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_checkpoint_coordinates_reject_different_document_hash() -> None:
    existing = SimpleNamespace(
        preview_epoch=3,
        preview_version=8,
        document_hash='existing-hash',
    )
    with (
        patch.object(
            MindmapAiDao,
            'get_draft_checkpoint',
            new=AsyncMock(return_value=existing),
        ),
        pytest.raises(ValueError, match='坐标冲突'),
    ):
        await MindmapAiDao.upsert_draft_checkpoint(SimpleNamespace(), {
            'job_id': 'job-conflict',
            'preview_epoch': 3,
            'preview_version': 8,
            'document_hash': 'different-hash',
        })


@pytest.mark.asyncio
async def test_old_execution_epoch_cannot_publish_checkpoint_after_takeover() -> None:
    database = SimpleNamespace(rollback=AsyncMock())

    class _SessionFactory:
        def __call__(self) -> '_SessionFactory':
            return self

        async def __aenter__(self) -> SimpleNamespace:
            return database

        async def __aexit__(self, *_args: object) -> None:
            return None

    upsert_checkpoint = AsyncMock()
    add_event = AsyncMock()
    token = _CURRENT_JOB_EXECUTION_EPOCH.set(4)
    try:
        with (
            patch(
                'module_mindmap.service.mindmap_ai_service.AsyncSessionLocal',
                new=_SessionFactory(),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(return_value=SimpleNamespace(
                    status='running',
                    execution_epoch=5,
                )),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.upsert_draft_checkpoint',
                new=upsert_checkpoint,
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_event',
                new=add_event,
            ),
        ):
            await MindmapAiTaskManager._emit('job-taken-over', 'draft_changed', {
                'operationCursor': 1,
                'operations': [],
                'previewState': _document('旧执行者'),
            })
    finally:
        _CURRENT_JOB_EXECUTION_EPOCH.reset(token)

    upsert_checkpoint.assert_not_awaited()
    add_event.assert_not_awaited()


def test_corrupt_operations_ciphertext_invalidates_entire_checkpoint() -> None:
    values = MindmapAiTaskManager._draft_checkpoint_values(
        job_id='job-corrupt',
        document=_document(),
        operations=[],
        initial_state=None,
        preview_version=2,
        preview_epoch=1,
        summary={},
        expires_time=datetime.now() + timedelta(hours=1),
    )
    checkpoint = SimpleNamespace(**{
        **values,
        'operations_ciphertext': 'corrupt-ciphertext',
        'update_time': datetime.now(),
    })

    assert MindmapAiTaskManager._draft_checkpoint_preview(checkpoint) is None


@pytest.mark.asyncio
async def test_preview_service_recovers_verified_checkpoint_and_refills_redis() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    checkpoint_values = MindmapAiTaskManager._draft_checkpoint_values(
        job_id='job-db-fallback',
        document=_document('数据库恢复草稿'),
        operations=[{'type': 'update_node'}],
        initial_state=None,
        preview_version=8,
        preview_epoch=3,
        summary={'nodeCount': 1},
        expires_time=datetime.now() + timedelta(hours=1),
    )
    checkpoint = SimpleNamespace(
        **checkpoint_values,
        update_time=datetime.now(),
    )
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(
                status='running',
                progress=50,
                execution_epoch=3,
            )),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_draft_checkpoint',
            new=AsyncMock(return_value=checkpoint),
        ),
    ):
        preview = await MindmapAiService.get_job_draft_preview(
            SimpleNamespace(),
            'job-db-fallback',
            user_id=9,
        )
        unavailable_old_version = await MindmapAiService.get_job_draft_preview(
            SimpleNamespace(),
            'job-db-fallback',
            user_id=9,
            version=7,
        )
    MindmapAiTaskManager._redis = None

    assert preview['available'] is True
    assert preview['operationCursor'] == 8  # noqa: PLR2004
    assert preview['previewEpoch'] == 3  # noqa: PLR2004
    assert preview['document']['root']['data']['text'] == '数据库恢复草稿'
    assert MindmapAiTaskManager._draft_preview_key('job-db-fallback') in redis.values
    assert unavailable_old_version['available'] is False
    assert unavailable_old_version['requestedVersion'] == 7  # noqa: PLR2004


@pytest.mark.asyncio
@pytest.mark.parametrize('checkpoint_failure', ['authentication', 'expired'])
async def test_present_invalid_checkpoint_never_falls_back_to_redis_latest(
    checkpoint_failure: str,
) -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    await _publish_execution('job-fail-closed', 5)
    assert await MindmapAiTaskManager._store_draft_preview(
        'job-fail-closed',
        _document('不得回退的 Redis 正文'),
        operation_cursor=8,
        preview_epoch=5,
        expected_execution_epoch=5,
    )
    checkpoint_values = MindmapAiTaskManager._draft_checkpoint_values(
        job_id='job-fail-closed',
        document=_document('数据库正文'),
        operations=[],
        initial_state=None,
        preview_version=8,
        preview_epoch=5,
        summary={},
        expires_time=(
            datetime.now() - timedelta(seconds=1)
            if checkpoint_failure == 'expired'
            else datetime.now() + timedelta(hours=1)
        ),
    )
    if checkpoint_failure == 'authentication':
        checkpoint_values['operations_ciphertext'] = 'invalid-ciphertext'
    checkpoint = SimpleNamespace(**checkpoint_values, update_time=datetime.now())
    try:
        with (
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(return_value=SimpleNamespace(
                    status='running',
                    progress=50,
                    execution_epoch=5,
                )),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_draft_checkpoint',
                new=AsyncMock(return_value=checkpoint),
            ),
        ):
            response = await MindmapAiService.get_job_draft_preview(
                SimpleNamespace(),
                'job-fail-closed',
                user_id=9,
            )
    finally:
        MindmapAiTaskManager._redis = None

    assert response['available'] is False


@pytest.mark.asyncio
async def test_only_exact_redis_version_older_than_db_checkpoint_may_fallback() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    await _publish_execution('job-history-fallback', 4)
    assert await MindmapAiTaskManager._store_draft_preview(
        'job-history-fallback',
        _document('历史版本 7'),
        operation_cursor=7,
        preview_epoch=3,
        expected_execution_epoch=4,
    )
    assert await MindmapAiTaskManager._store_draft_preview(
        'job-history-fallback',
        _document('伪造的新版本 9'),
        operation_cursor=9,
        preview_epoch=4,
        expected_execution_epoch=4,
    )
    checkpoint_values = MindmapAiTaskManager._draft_checkpoint_values(
        job_id='job-history-fallback',
        document=_document('数据库最新版本 8'),
        operations=[],
        initial_state=None,
        preview_version=8,
        preview_epoch=4,
        summary={},
        expires_time=datetime.now() + timedelta(hours=1),
    )
    checkpoint = SimpleNamespace(**checkpoint_values, update_time=datetime.now())
    try:
        with (
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(return_value=SimpleNamespace(
                    status='running',
                    progress=50,
                    execution_epoch=4,
                )),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_draft_checkpoint',
                new=AsyncMock(return_value=checkpoint),
            ),
        ):
            historical = await MindmapAiService.get_job_draft_preview(
                SimpleNamespace(),
                'job-history-fallback',
                user_id=9,
                version=7,
            )
            newer = await MindmapAiService.get_job_draft_preview(
                SimpleNamespace(),
                'job-history-fallback',
                user_id=9,
                version=9,
            )
    finally:
        MindmapAiTaskManager._redis = None

    assert historical['available'] is True
    assert historical['document']['root']['data']['text'] == '历史版本 7'
    assert newer['available'] is False
    assert newer['requestedVersion'] == 9  # noqa: PLR2004


@pytest.mark.asyncio
async def test_preview_service_checks_job_ownership_before_reading_snapshot() -> None:
    redis = _FakeRedis()
    MindmapAiTaskManager.configure_redis(redis)
    await _publish_execution('job-3')
    await MindmapAiTaskManager._store_draft_preview(
        'job-3',
        _document(),
        operation_cursor=5,
        expected_execution_epoch=1,
    )
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(status='running', progress=45)),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_draft_checkpoint',
            new=AsyncMock(return_value=None),
        ),
    ):
        preview = await MindmapAiService.get_job_draft_preview(
            SimpleNamespace(), 'job-3', user_id=9,
        )

    assert preview['available'] is True
    assert preview['operationCursor'] == 5  # noqa: PLR2004
    assert preview['document']['root']['data']['text'] == '实时脑图'

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(ServiceException) as missing,
    ):
        await MindmapAiService.get_job_draft_preview(SimpleNamespace(), 'job-3', user_id=10)
    assert missing.value.message == 'AI 脑图任务不存在'
    MindmapAiTaskManager._redis = None


@pytest.mark.asyncio
async def test_terminal_job_never_exposes_stale_checkpoint_or_redis_draft() -> None:
    get_preview = AsyncMock(return_value={
        'jobId': 'job-terminal',
        'document': _document('不应返回'),
    })
    get_checkpoint = AsyncMock()
    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(return_value=SimpleNamespace(status='ready', progress=100)),
        ),
        patch.object(MindmapAiTaskManager, 'get_draft_preview', new=get_preview),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_draft_checkpoint',
            new=get_checkpoint,
        ),
    ):
        response = await MindmapAiService.get_job_draft_preview(
            SimpleNamespace(),
            'job-terminal',
            user_id=9,
        )

    assert response == {
        'available': False,
        'jobId': 'job-terminal',
        'status': 'ready',
        'progress': 100,
    }
    get_preview.assert_not_awaited()
    get_checkpoint.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('terminal_status', ['ready', 'cancelled'])
async def test_terminal_commit_wins_preview_current_read_even_when_redis_fence_fails(
    terminal_status: str,
) -> None:
    """A committed completion/cancel must prevent the legacy Redis fallback."""
    redis = _FailingTerminalRedis()
    MindmapAiTaskManager.configure_redis(redis)
    await _publish_execution('job-terminal-current-read', 6)
    assert await MindmapAiTaskManager._store_draft_preview(
        'job-terminal-current-read',
        _document('终态后不得返回的旧草稿'),
        operation_cursor=5,
        preview_epoch=4,
        expected_execution_epoch=6,
    )

    row_lock = asyncio.Lock()
    terminal_holds_lock = asyncio.Event()
    allow_terminal_commit = asyncio.Event()
    terminal_committed = asyncio.Event()
    job_state = {
        'status': 'running',
        'progress': 60,
        'execution_epoch': 6,
    }

    async def get_job(
        _db: object,
        _job_id: str,
        _user_id: int,
        *,
        for_update: bool = False,
    ) -> SimpleNamespace:
        if for_update:
            # Model a database current/locking read: it waits for a terminal
            # writer that already owns the row, then observes its commit.
            async with row_lock:
                return SimpleNamespace(**job_state)
        return SimpleNamespace(status='running', progress=60, execution_epoch=6)

    async def get_checkpoint(_db: object, _job_id: str) -> None:
        # Under PostgreSQL READ COMMITTED the checkpoint deletion is visible
        # after the terminal transaction commits.  The old implementation then
        # incorrectly fell through to the still-populated Redis cache.
        await terminal_committed.wait()

    async def commit_terminal() -> bool:
        async with row_lock:
            terminal_holds_lock.set()
            await allow_terminal_commit.wait()
            job_state['status'] = terminal_status
            job_state['progress'] = 100
        terminal_committed.set()
        return await MindmapAiTaskManager.mark_draft_terminal(
            'job-terminal-current-read',
            6,
        )

    get_checkpoint_mock = AsyncMock(side_effect=get_checkpoint)
    terminal_task = asyncio.create_task(commit_terminal())
    await terminal_holds_lock.wait()
    try:
        with (
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
                new=AsyncMock(side_effect=get_job),
            ),
            patch(
                'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_draft_checkpoint',
                new=get_checkpoint_mock,
            ),
        ):
            preview_task = asyncio.create_task(
                MindmapAiService.get_job_draft_preview(
                    SimpleNamespace(),
                    'job-terminal-current-read',
                    user_id=9,
                ),
            )
            await asyncio.sleep(0)
            assert preview_task.done() is False
            allow_terminal_commit.set()
            response, fenced = await asyncio.gather(preview_task, terminal_task)
    finally:
        MindmapAiTaskManager._redis = None

    assert fenced is False
    assert response == {
        'available': False,
        'jobId': 'job-terminal-current-read',
        'status': terminal_status,
        'progress': 100,
    }
    get_checkpoint_mock.assert_not_awaited()
    assert (
        MindmapAiTaskManager._draft_preview_key('job-terminal-current-read')
        in redis.values
    )


@pytest.mark.asyncio
async def test_preview_row_lock_spans_redis_compatibility_read() -> None:
    """A GET that wins the row lock is linearized before later completion."""
    row_lock = asyncio.Lock()
    redis_read_started = asyncio.Event()
    allow_redis_read = asyncio.Event()
    terminal_acquired_lock = asyncio.Event()

    async def get_job(
        _db: object,
        _job_id: str,
        _user_id: int,
        *,
        for_update: bool = False,
    ) -> SimpleNamespace:
        assert for_update is True
        await row_lock.acquire()
        return SimpleNamespace(status='running', progress=40, execution_epoch=2)

    async def read_redis(_job_id: str, _version: int | None) -> dict:
        redis_read_started.set()
        await allow_redis_read.wait()
        return {
            'jobId': 'job-preview-lock-span',
            'operationCursor': 3,
            'previewEpoch': 2,
            'document': _document('锁内读取的草稿'),
            'updatedTime': datetime.now().isoformat(),
        }

    async def complete_after_get() -> None:
        async with row_lock:
            terminal_acquired_lock.set()

    with (
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job',
            new=AsyncMock(side_effect=get_job),
        ),
        patch(
            'module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_draft_checkpoint',
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            MindmapAiTaskManager,
            'get_draft_preview',
            new=AsyncMock(side_effect=read_redis),
        ),
    ):
        preview_task = asyncio.create_task(
            MindmapAiService.get_job_draft_preview(
                SimpleNamespace(),
                'job-preview-lock-span',
                user_id=9,
            ),
        )
        await redis_read_started.wait()
        completion_task = asyncio.create_task(complete_after_get())
        await asyncio.sleep(0)
        assert terminal_acquired_lock.is_set() is False

        allow_redis_read.set()
        response = await preview_task
        # Simulate request-session teardown releasing the database row lock.
        row_lock.release()
        await completion_task

    assert response['available'] is True
    assert response['document']['root']['data']['text'] == '锁内读取的草稿'
    assert terminal_acquired_lock.is_set() is True
