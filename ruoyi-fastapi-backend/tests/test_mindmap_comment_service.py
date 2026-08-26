"""脑图节点评论服务测试。"""

import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

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
        comment = SimpleNamespace(
            id=23,
            thread_id=19,
            created_by=7,
            del_flag='2',
        )
        thread = SimpleNamespace(
            id=19,
            mindmap_id=5,
            node_uid='node-1',
            created_by=7,
            del_flag='2',
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
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


if __name__ == '__main__':
    unittest.main()
