"""脑图节点评论服务测试。"""

import asyncio
import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from module_mindmap.dao.mindmap_comment_dao import MindmapCommentDao
from module_mindmap.entity.vo.mindmap_comment_vo import (
    MindmapCommentCreateModel,
    MindmapCommentReplyModel,
)
from module_mindmap.service.mindmap_comment_service import MindmapCommentService


class _ExpireAfterCommitRecord(SimpleNamespace):
    """模拟 AsyncSession 默认的 commit 后 ORM 实例过期行为。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, '_expired', False)

    def expire(self) -> None:
        object.__setattr__(self, '_expired', True)

    def __getattribute__(self, name: str) -> Any:
        if (
            not name.startswith('_')
            and name != 'expire'
            and object.__getattribute__(self, '_expired')
        ):
            raise AssertionError(f'commit 后不应再次读取 ORM 属性: {name}')
        return super().__getattribute__(name)


def _session_expiring(*records: _ExpireAfterCommitRecord) -> SimpleNamespace:
    async def expire_records() -> None:
        for record in records:
            record.expire()

    return SimpleNamespace(
        commit=AsyncMock(side_effect=expire_records),
        rollback=AsyncMock(),
    )


def _session_expiring_on_rollback(*records: _ExpireAfterCommitRecord) -> SimpleNamespace:
    async def expire_records() -> None:
        for record in records:
            record.expire()

    return SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(side_effect=expire_records),
    )


class _CommentLockHarness:
    """Model row locks and stale identity-map reads around actual service calls."""

    def __init__(self, first: str) -> None:
        self.first = first
        self.first_locked = asyncio.Event()
        self.second_waiting = asyncio.Event()
        self.resume_first = asyncio.Event()
        self.thread_lock = asyncio.Lock()
        self.comment_lock = asyncio.Lock()
        self.trace: list[str] = []
        self.comment = SimpleNamespace(id=23, thread_id=19, mindmap_id=5, created_by=7, del_flag='0')
        self.thread = SimpleNamespace(id=19, mindmap_id=5, created_by=8, node_uid='node-1', del_flag='0')

    def session(self, name: str) -> SimpleNamespace:
        held: list[asyncio.Lock] = []

        async def release() -> None:
            while held:
                held.pop().release()

        return SimpleNamespace(name=name, held=held, commit=AsyncMock(side_effect=release),
                               rollback=AsyncMock(side_effect=release))

    async def lock(self, db: SimpleNamespace, lock: asyncio.Lock, kind: str) -> None:
        if lock not in db.held:
            self.trace.append(f'{db.name}:wait-{kind}')
            await lock.acquire()
            db.held.append(lock)
            self.trace.append(f'{db.name}:locked-{kind}')

    async def get_thread(self, db: SimpleNamespace, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
        if db.name != self.first:
            self.second_waiting.set()
        await self.lock(db, self.thread_lock, 'thread')
        if db.name == self.first:
            self.first_locked.set()
            await self.resume_first.wait()
        return SimpleNamespace(**vars(self.thread))

    async def get_comment(
        self, db: SimpleNamespace, *_args: Any, for_update: bool = False, **_kwargs: Any,
    ) -> SimpleNamespace:
        if for_update:
            await self.lock(db, self.comment_lock, 'comment')
        return SimpleNamespace(**vars(self.comment))

    async def list_comments(self, db: SimpleNamespace, *_args: Any, **_kwargs: Any) -> list[SimpleNamespace]:
        if self.comment.del_flag != '0':
            return []
        await self.lock(db, self.comment_lock, 'comment')
        return [SimpleNamespace(**vars(self.comment))] if self.comment.del_flag == '0' else []

    async def delete_comment(self, db: SimpleNamespace, *_args: Any) -> None:
        await self.lock(db, self.comment_lock, 'comment')
        self.comment.del_flag = '2'


class MindmapCommentServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_comment_models_trim_and_reject_blank_content(self) -> None:
        model = MindmapCommentCreateModel(mindmapId=5, nodeUid=' node-1 ', content='  需要确认  ')
        self.assertEqual(model.node_uid, 'node-1')
        self.assertEqual(model.content, '需要确认')
        with self.assertRaises(ValidationError):
            MindmapCommentReplyModel(content='  \n  ')

    async def test_view_collaborator_can_create_comment_on_active_node(self) -> None:
        node = SimpleNamespace(text_plain='  核心需求  ')
        thread = _ExpireAfterCommitRecord(id=19)
        comment = _ExpireAfterCommitRecord(id=23)
        db = _session_expiring(thread, comment)
        with (
            patch.object(
                MindmapCommentService,
                '_ensure_comment_writable',
                new=AsyncMock(return_value=SimpleNamespace(status=0)),
            ) as access_mock,
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_active_node',
                new=AsyncMock(return_value=node),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.create_thread',
                new=AsyncMock(return_value=(thread, comment)),
            ) as create_mock,
            patch.object(MindmapCommentService, '_broadcast_change', new=AsyncMock()) as broadcast_mock,
        ):
            result = await MindmapCommentService.create_thread(
                db,
                MindmapCommentCreateModel(mindmapId=5, nodeUid='node-1', content='需要确认'),
                user_id=7,
            )

        access_mock.assert_awaited_once_with(db, 5, 7)
        create_mock.assert_awaited_once()
        self.assertEqual(create_mock.await_args.kwargs['node_text'], '核心需求')
        db.commit.assert_awaited_once()
        broadcast_mock.assert_awaited_once_with(5, 'created', 19, 'node-1')
        self.assertEqual(result, {
            'threadId': 19,
            'commentId': 23,
            'idempotentReplay': False,
        })

    async def test_deferred_thread_creation_leaves_commit_and_broadcast_to_caller(self) -> None:
        node = SimpleNamespace(text_plain='核心需求')
        thread = SimpleNamespace(id=19)
        comment = SimpleNamespace(id=23)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        broadcast_mock = AsyncMock()
        with (
            patch.object(
                MindmapCommentService,
                '_ensure_comment_writable',
                new=AsyncMock(return_value=SimpleNamespace(status=0)),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_active_node',
                new=AsyncMock(return_value=node),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.create_thread',
                new=AsyncMock(return_value=(thread, comment)),
            ),
            patch.object(MindmapCommentService, '_broadcast_change', new=broadcast_mock),
        ):
            result = await MindmapCommentService.create_thread(
                db,
                MindmapCommentCreateModel(mindmapId=5, nodeUid='node-1', content='需要确认'),
                user_id=7,
                commit=False,
                broadcast=False,
            )

        self.assertEqual(result['threadId'], 19)
        db.commit.assert_not_awaited()
        broadcast_mock.assert_not_awaited()

    async def test_create_retry_reuses_committed_comment_without_duplicate_write(self) -> None:
        request_id = 'comment-request-123456'
        existing = SimpleNamespace(
            id=23,
            thread_id=19,
            mindmap_id=5,
            node_uid='node-1',
            content='需要确认',
            is_thread_starter=True,
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapCommentService,
                '_ensure_comment_access',
                new=AsyncMock(return_value=SimpleNamespace(status=0)),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_by_request_id',
                new=AsyncMock(return_value=existing),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_active_node',
                new=AsyncMock(),
            ) as node_mock,
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.create_thread',
                new=AsyncMock(),
            ) as create_mock,
        ):
            result = await MindmapCommentService.create_thread(
                db,
                MindmapCommentCreateModel(mindmapId=5, nodeUid='node-1', content='需要确认'),
                user_id=7,
                request_id=request_id,
            )

        self.assertEqual(result, {
            'threadId': 19,
            'commentId': 23,
            'idempotentReplay': True,
        })
        node_mock.assert_not_awaited()
        create_mock.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_reused_comment_key_for_different_intent_is_rejected(self) -> None:
        existing = SimpleNamespace(
            id=23,
            thread_id=19,
            mindmap_id=5,
            node_uid='node-1',
            content='原内容',
            is_thread_starter=True,
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapCommentService,
                '_ensure_comment_access',
                new=AsyncMock(return_value=SimpleNamespace(status=0)),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_by_request_id',
                new=AsyncMock(return_value=existing),
            ),
            self.assertRaises(Exception) as context,
        ):
            await MindmapCommentService.create_thread(
                db,
                MindmapCommentCreateModel(mindmapId=5, nodeUid='node-1', content='新内容'),
                user_id=7,
                request_id='comment-request-123456',
            )

        self.assertEqual(context.exception.message, 'Idempotency-Key 已用于不同的评论请求')

    async def test_reply_retry_replays_after_thread_was_deleted(self) -> None:
        existing = SimpleNamespace(
            id=24,
            thread_id=19,
            mindmap_id=5,
            node_uid='node-1',
            content='补充一下',
            is_thread_starter=False,
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapCommentService,
                '_ensure_comment_access',
                new=AsyncMock(return_value=SimpleNamespace(status=0)),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_by_request_id',
                new=AsyncMock(return_value=existing),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_thread_for_update',
                new=AsyncMock(),
            ) as thread_mock,
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.create_reply',
                new=AsyncMock(),
            ) as create_mock,
        ):
            result = await MindmapCommentService.reply_thread(
                db,
                19,
                MindmapCommentReplyModel(content='补充一下'),
                user_id=7,
                request_id='comment-reply-123456',
            )

        self.assertEqual(result, {
            'threadId': 19,
            'commentId': 24,
            'idempotentReplay': True,
        })
        thread_mock.assert_not_awaited()
        create_mock.assert_not_awaited()

    async def test_thread_creation_key_cannot_be_reused_as_reply(self) -> None:
        existing = SimpleNamespace(
            id=23,
            thread_id=19,
            mindmap_id=5,
            node_uid='node-1',
            content='相同内容',
            is_thread_starter=True,
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapCommentService,
                '_ensure_comment_access',
                new=AsyncMock(return_value=SimpleNamespace(status=0)),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_by_request_id',
                new=AsyncMock(return_value=existing),
            ),
            self.assertRaises(Exception) as context,
        ):
            await MindmapCommentService.reply_thread(
                db,
                19,
                MindmapCommentReplyModel(content='相同内容'),
                user_id=7,
                request_id='comment-thread-123456',
            )

        self.assertEqual(context.exception.message, 'Idempotency-Key 已用于不同的评论请求')

    async def test_comment_cannot_target_deleted_node(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapCommentService,
                '_ensure_comment_writable',
                new=AsyncMock(return_value=SimpleNamespace(status=0)),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_active_node',
                new=AsyncMock(return_value=None),
            ),
            self.assertRaises(Exception) as context,
        ):
            await MindmapCommentService.create_thread(
                db,
                MindmapCommentCreateModel(mindmapId=5, nodeUid='deleted', content='还能看到吗'),
                user_id=7,
            )

        self.assertEqual(context.exception.message, '评论节点不存在或已被删除')
        db.commit.assert_not_awaited()

    async def test_reply_reopens_resolved_thread(self) -> None:
        thread = _ExpireAfterCommitRecord(id=19, mindmap_id=5, node_uid='node-1', status=1)
        comment = _ExpireAfterCommitRecord(id=24)
        db = _session_expiring(thread, comment)
        broadcast_mock = AsyncMock()
        with (
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_thread_for_update',
                new=AsyncMock(return_value=thread),
            ),
            patch.object(
                MindmapCommentService,
                '_ensure_comment_writable',
                new=AsyncMock(return_value=SimpleNamespace(status=0)),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.create_reply',
                new=AsyncMock(return_value=comment),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.update_status',
                new=AsyncMock(),
            ) as status_mock,
            patch.object(MindmapCommentService, '_broadcast_change', new=broadcast_mock),
        ):
            result = await MindmapCommentService.reply_thread(
                db, 19, MindmapCommentReplyModel(content='补充一下'), user_id=7,
            )

        status_mock.assert_awaited_once()
        self.assertFalse(status_mock.await_args.kwargs['resolved'])
        db.commit.assert_awaited_once()
        self.assertEqual(result['commentId'], 24)
        broadcast_mock.assert_awaited_once_with(5, 'replied', 19, 'node-1')

    async def test_delete_retry_is_idempotent(self) -> None:
        comment = _ExpireAfterCommitRecord(
            id=23,
            thread_id=19,
            created_by=7,
            del_flag='2',
        )
        thread = _ExpireAfterCommitRecord(
            id=19,
            mindmap_id=5,
            node_uid='node-1',
            created_by=7,
            del_flag='2',
        )
        db = _session_expiring_on_rollback(comment, thread)
        with (
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_comment',
                new=AsyncMock(return_value=comment),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_thread_for_update',
                new=AsyncMock(return_value=thread),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(SimpleNamespace(status=0), 1, False)),
            ),
        ):
            result = await MindmapCommentService.delete_comment(db, 23, user_id=7)

        self.assertEqual(result, {
            'threadId': 19,
            'threadDeleted': True,
            'alreadyDeleted': True,
        })
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

    async def test_view_collaborator_cannot_resolve_other_users_thread(self) -> None:
        thread = SimpleNamespace(
            id=19,
            mindmap_id=5,
            node_uid='node-1',
            status=0,
            created_by=42,
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_thread_for_update',
                new=AsyncMock(return_value=thread),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(SimpleNamespace(status=0), 0, False)),
            ),
            self.assertRaises(Exception) as context,
        ):
            await MindmapCommentService.set_thread_status(db, 19, True, user_id=7)

        self.assertEqual(context.exception.message, '只有线程创建者或可编辑协作者可以处理评论')
        db.rollback.assert_awaited_once()

    async def test_list_returns_author_capabilities_and_open_node_counts(self) -> None:
        now = datetime(2026, 8, 25, 12, 0, 0)
        thread = SimpleNamespace(
            id=19,
            mindmap_id=5,
            node_uid='node-1',
            node_text='核心需求',
            status=0,
            created_by=7,
            created_time=now,
            last_comment_time=now,
            resolved_by=None,
            resolved_time=None,
        )
        message = SimpleNamespace(
            id=23,
            thread_id=19,
            content='需要确认',
            created_by=7,
            created_time=now,
            update_time=None,
            user_name='viewer',
            nick_name='查看者',
            avatar='',
        )
        with (
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapService.resolve_mindmap_access',
                new=AsyncMock(return_value=(SimpleNamespace(status=0), 0, False)),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.list_threads',
                new=AsyncMock(return_value=([thread], 1)),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.list_messages',
                new=AsyncMock(return_value=[message]),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_open_summary',
                new=AsyncMock(return_value=(1, {'node-1': 1})),
            ),
        ):
            result = await MindmapCommentService.list_threads(
                SimpleNamespace(), 5, 7, status='open', page_num=1, page_size=50,
            )

        self.assertTrue(result['canComment'])
        self.assertEqual(result['summary']['nodeCounts'], {'node-1': 1})
        self.assertTrue(result['rows'][0]['canResolve'])
        self.assertTrue(result['rows'][0]['messages'][0]['canDelete'])
        self.assertEqual(result['rows'][0]['messages'][0]['authorName'], '查看者')

    async def test_direct_ai_comment_compensation_keeps_collaborator_reply(self) -> None:
        comment = SimpleNamespace(
            id=23,
            thread_id=19,
            mindmap_id=5,
            created_by=7,
            del_flag='0',
        )
        thread = SimpleNamespace(
            id=19,
            mindmap_id=5,
            node_uid='node-1',
        )
        with (
            patch.object(MindmapCommentDao, 'list_ai_comment_thread_ids', new=AsyncMock(return_value=[19])),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.list_ai_comments_for_update',
                new=AsyncMock(return_value=[comment]),
            ) as list_comments,
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.get_thread_for_update',
                new=AsyncMock(return_value=thread),
            ),
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.soft_delete_comment',
                new=AsyncMock(),
            ) as delete_comment,
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.refresh_thread_after_comment_delete',
                new=AsyncMock(return_value=False),
            ) as refresh_thread,
            patch(
                'module_mindmap.service.mindmap_comment_service.MindmapCommentDao.soft_delete_thread',
                new=AsyncMock(),
            ) as delete_thread,
        ):
            result = await MindmapCommentService.delete_ai_comments_for_job(
                SimpleNamespace(), 5, 7, 'job-1',
            )

        list_comments.assert_awaited_once_with(
            unittest.mock.ANY,
            5,
            7,
            'ai:job-1:',
            thread_id=19,
        )
        delete_comment.assert_awaited_once()
        refresh_thread.assert_awaited_once()
        delete_thread.assert_not_awaited()
        self.assertEqual(result, [{
            'threadId': 19,
            'nodeUid': 'node-1',
            'threadDeleted': False,
        }])

    async def test_manual_delete_and_ai_undo_use_same_lock_order_and_fresh_reads(self) -> None:
        for first in ('manual', 'undo'):
            with self.subTest(first=first):
                harness = _CommentLockHarness(first)
                manual_db = harness.session('manual')
                undo_db = harness.session('undo')
                delete_thread = AsyncMock()
                broadcast = AsyncMock()

                async def undo(db: SimpleNamespace = undo_db) -> list[dict[str, Any]]:
                    result = await MindmapCommentService.delete_ai_comments_for_job(db, 5, 7, 'job-1')
                    db.commit.assert_not_awaited()
                    db.rollback.assert_not_awaited()
                    await db.commit()  # The surrounding AI transaction owns the commit.
                    return result

                with (
                    patch.multiple(
                        MindmapCommentDao,
                        list_ai_comment_thread_ids=AsyncMock(return_value=[19]),
                        list_ai_comments_for_update=harness.list_comments,
                        get_thread_for_update=harness.get_thread,
                        get_comment=harness.get_comment,
                        soft_delete_comment=harness.delete_comment,
                        refresh_thread_after_comment_delete=AsyncMock(return_value=False),
                        soft_delete_thread=delete_thread,
                    ),
                    patch.object(MindmapCommentService, '_ensure_comment_writable', new=AsyncMock()),
                    patch.object(MindmapCommentService, '_broadcast_change', new=broadcast),
                    patch(
                        'module_mindmap.service.mindmap_comment_service.MindmapService.resolve_mindmap_access',
                        new=AsyncMock(return_value=(SimpleNamespace(), 1, False)),
                    ),
                ):
                    calls = {
                        'manual': lambda db=manual_db: MindmapCommentService.delete_comment(db, 23, 7), 'undo': undo,
                    }
                    tasks = [asyncio.create_task(calls[first]())]
                    try:
                        await asyncio.wait_for(harness.first_locked.wait(), timeout=1)
                        second = 'undo' if first == 'manual' else 'manual'
                        tasks.append(asyncio.create_task(calls[second]()))
                        await asyncio.wait_for(harness.second_waiting.wait(), timeout=1)
                        harness.resume_first.set()
                        results = dict(zip(
                            (first, second), await asyncio.wait_for(asyncio.gather(*tasks), timeout=1), strict=True,
                        ))
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        await manual_db.rollback()
                        await undo_db.rollback()
                self.assertEqual(harness.comment.del_flag, '2')
                delete_thread.assert_not_awaited()
                self.assertEqual(results['manual']['alreadyDeleted'], first == 'undo')
                self.assertEqual(results['undo'], [] if first == 'manual' else [{
                    'threadId': 19, 'nodeUid': 'node-1', 'threadDeleted': False,
                }])
                for owner in ('manual', 'undo'):
                    comment_lock = f'{owner}:locked-comment'
                    if comment_lock in harness.trace:
                        self.assertLess(harness.trace.index(f'{owner}:locked-thread'), harness.trace.index(comment_lock))
                self.assertEqual(broadcast.await_count, 1 if first == 'manual' else 0)

    async def test_ai_compensation_locks_threads_in_order_and_leaves_transaction_to_caller(self) -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        trace: list[tuple[str, int]] = []

        async def get_thread(_db: Any, thread_id: int, **_kwargs: Any) -> SimpleNamespace:
            trace.append(('thread', thread_id))
            return SimpleNamespace(id=thread_id, mindmap_id=5, node_uid=f'node-{thread_id}')

        async def list_comments(_db: Any, *_args: Any, thread_id: int) -> list[SimpleNamespace]:
            trace.append(('comments', thread_id))
            return [SimpleNamespace(id=thread_id, del_flag='0')]

        with (
            patch.multiple(
                MindmapCommentDao,
                list_ai_comment_thread_ids=AsyncMock(return_value=[19, 20]),
                get_thread_for_update=get_thread,
                list_ai_comments_for_update=list_comments,
                soft_delete_comment=AsyncMock(),
                refresh_thread_after_comment_delete=AsyncMock(return_value=True),
                soft_delete_thread=AsyncMock(),
            ),
            patch.object(MindmapCommentService, '_broadcast_change', new=AsyncMock()) as broadcast,
        ):
            result = await MindmapCommentService.delete_ai_comments_for_job(db, 5, 7, 'job-1')
            self.assertEqual([item['threadId'] for item in result], [19, 20])
            self.assertTrue(all(item['threadDeleted'] for item in result))
            self.assertEqual(trace, [('thread', 19), ('comments', 19), ('thread', 20), ('comments', 20)])
            db.commit.assert_not_awaited()
            db.rollback.assert_not_awaited()
            broadcast.assert_not_awaited()
            with (
                patch.object(MindmapCommentDao, 'soft_delete_comment', new=AsyncMock(side_effect=RuntimeError('write'))),
                self.assertRaisesRegex(RuntimeError, 'write'),
            ):
                await MindmapCommentService.delete_ai_comments_for_job(db, 5, 7, 'job-1')
            db.commit.assert_not_awaited()
            db.rollback.assert_not_awaited()
            broadcast.assert_not_awaited()

    async def test_ai_comment_dao_discovers_without_locks_then_filters_and_refreshes_locked_rows(self) -> None:
        result = Mock()
        result.scalars.return_value.all.return_value = []
        result.scalars.return_value.first.return_value = None
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        await MindmapCommentDao.list_ai_comment_thread_ids(db, 5, 7, 'ai:job-1:')
        await MindmapCommentDao.get_thread_for_update(db, 19, include_deleted=True)
        await MindmapCommentDao.list_ai_comments_for_update(db, 5, 7, 'ai:job-1:', thread_id=19)
        await MindmapCommentDao.get_comment(db, 23, include_deleted=True, for_update=True)
        statements = [call.args[0] for call in db.execute.await_args_list]
        compiled = [statement.compile(dialect=postgresql.dialect()) for statement in statements]
        self.assertNotIn('FOR UPDATE', str(compiled[0]))
        self.assertIn('DISTINCT', str(compiled[0]))
        self.assertIn('ORDER BY mindmap_comment.thread_id ASC', str(compiled[0]))
        for statement, sql in zip(statements[1:], compiled[1:], strict=True):
            self.assertIn('FOR UPDATE', str(sql))
            self.assertTrue(statement.get_execution_options()['populate_existing'])
        self.assertEqual(compiled[0].params, {
            'mindmap_id_1': 5, 'created_by_1': 7, 'client_request_id_1': 'ai:job-1:%', 'del_flag_1': '0',
        })
        self.assertEqual(compiled[2].params, {**compiled[0].params, 'thread_id_1': 19})

    async def test_delete_preserves_reply_committed_after_repeatable_read_snapshot(self) -> None:
        """A stale COUNT/MAX sees zero rows; a locking read sees the new reply."""
        for actor in ('manual', 'undo'):
            with self.subTest(actor=actor):
                state = {'snapshot_open': False, 'reply_committed': False}
                reply_time = datetime(2026, 9, 25, 16, 0, 0)
                comment = SimpleNamespace(id=23, thread_id=19, created_by=7, del_flag='0')
                thread = SimpleNamespace(id=19, mindmap_id=5, node_uid='node-1', created_by=8, del_flag='0')
                statements: list[Any] = []

                async def initial_read(*_args: Any, state: dict = state, **_kwargs: Any) -> list[int]:
                    state['snapshot_open'] = True
                    return [19]

                async def get_comment(
                    *_args: Any, state: dict = state, comment: SimpleNamespace = comment, **_kwargs: Any,
                ) -> SimpleNamespace:
                    state['snapshot_open'] = True
                    return comment

                async def lock_thread(
                    *_args: Any, state: dict = state, thread: SimpleNamespace = thread, **_kwargs: Any,
                ) -> SimpleNamespace:
                    self.assertTrue(state['snapshot_open'])
                    state['reply_committed'] = True  # Reply transaction commits before releasing the thread lock.
                    return thread

                async def execute(
                    statement: Any, state: dict = state, statements: list = statements, reply_time: datetime = reply_time,
                ) -> Mock:
                    self.assertTrue(state['reply_committed'])
                    statements.append(statement)
                    sql = str(statement.compile(dialect=postgresql.dialect()))
                    # Only a locking current read can escape the initial empty RR snapshot.
                    visible_reply = reply_time if 'FOR UPDATE' in sql else None
                    result = Mock()
                    result.scalar_one_or_none.return_value = visible_reply
                    result.scalar_one.return_value = 0  # Old non-locking COUNT would delete the new reply.
                    return result

                db = SimpleNamespace(execute=AsyncMock(side_effect=execute), commit=AsyncMock(), rollback=AsyncMock())
                with (
                    patch.multiple(
                        MindmapCommentDao,
                        list_ai_comment_thread_ids=initial_read,
                        list_ai_comments_for_update=AsyncMock(return_value=[comment]),
                        get_thread_for_update=lock_thread,
                        get_comment=get_comment,
                        soft_delete_comment=AsyncMock(),
                        soft_delete_thread=AsyncMock(side_effect=AssertionError('must retain collaborator reply')),
                    ),
                    patch.object(MindmapCommentService, '_ensure_comment_writable', new=AsyncMock()),
                    patch.object(MindmapCommentService, '_broadcast_change', new=AsyncMock()),
                    patch(
                        'module_mindmap.service.mindmap_comment_service.MindmapService.resolve_mindmap_access',
                        new=AsyncMock(return_value=(SimpleNamespace(), 1, False)),
                    ),
                ):
                    if actor == 'undo':
                        result = (await MindmapCommentService.delete_ai_comments_for_job(db, 5, 7, 'job-1'))[0]
                        db.commit.assert_not_awaited()
                    else:
                        result = await MindmapCommentService.delete_comment(db, 23, 7)
                        db.commit.assert_awaited_once()
                self.assertFalse(result['threadDeleted'])
                current_read, touch = statements
                sql = str(current_read.compile(dialect=postgresql.dialect()))
                self.assertIn('FOR UPDATE', sql)
                self.assertIn('LIMIT', sql)
                self.assertNotIn('max(', sql)
                self.assertNotIn('count(', sql)
                self.assertEqual(touch.compile().params['last_comment_time'], reply_time)

    async def test_thread_cleanup_soft_deletes_only_when_current_read_is_empty(self) -> None:
        result = Mock()
        result.scalar_one_or_none.return_value = None
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        now = datetime.now()
        with patch.object(MindmapCommentDao, 'soft_delete_thread', new=AsyncMock()) as delete_thread:
            self.assertTrue(await MindmapCommentDao.refresh_thread_after_comment_delete(db, 19, now))
        delete_thread.assert_awaited_once_with(db, 19, now)
        db.execute.assert_awaited_once()
        self.assertIn('FOR UPDATE', str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect())))


if __name__ == '__main__':
    unittest.main()
