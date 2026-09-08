"""脑图公开分享权限策略测试。"""
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import mysql, postgresql

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_collaborator_dao import MindmapCollaboratorDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_share_dao import (
    MindmapOwnershipSnapshot,
    MindmapShareAccessSnapshot,
    MindmapShareDao,
    MindmapShareListSnapshot,
    SharedMindmapSnapshot,
)
from module_mindmap.entity.vo.mindmap_share_vo import MindmapShareCreateModel
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_share_service import MindmapShareService


class MindmapSharePolicyTest(unittest.IsolatedAsyncioTestCase):
    async def test_public_snapshot_queries_hold_shared_row_locks(self) -> None:
        class _Result:
            def __init__(self, row: SimpleNamespace) -> None:
                self.row = row

            def one_or_none(self) -> SimpleNamespace:
                return self.row

        class _CaptureDb:
            def __init__(self, row: SimpleNamespace) -> None:
                self.row = row
                self.statement: Any = None

            async def execute(self, statement: Any) -> _Result:
                self.statement = statement
                return _Result(self.row)

        mindmap_db = _CaptureDb(SimpleNamespace(
            mindmap_id=8,
            name='revision-4',
            node_tree='{}',
            layout='logicalStructure',
            theme=None,
            view_data=None,
            document_data=None,
            schema_version=2,
            content_revision=4,
        ))
        share_db = _CaptureDb(SimpleNamespace(
            mindmap_id=8,
            share_type=0,
            expire_time=None,
            created_by=7,
            is_active=1,
        ))

        await MindmapShareDao.get_shared_mindmap_snapshot(
            mindmap_db,
            8,
            for_share=True,
        )
        await MindmapShareDao.get_share_access_snapshot(
            share_db,
            'a' * 32,
            for_share=True,
        )

        mindmap_sql = str(mindmap_db.statement.compile(dialect=postgresql.dialect()))
        share_sql = str(share_db.statement.compile(dialect=postgresql.dialect()))
        mysql_mindmap_sql = str(mindmap_db.statement.compile(dialect=mysql.dialect()))
        mysql_share_sql = str(share_db.statement.compile(dialect=mysql.dialect()))
        self.assertIn('FOR SHARE', mindmap_sql)
        self.assertIn('FOR SHARE', share_sql)
        self.assertIn('LOCK IN SHARE MODE', mysql_mindmap_sql)
        self.assertIn('LOCK IN SHARE MODE', mysql_share_sql)

    async def test_edit_link_is_persisted_as_authenticated_invitation(self) -> None:
        mindmap = MindmapOwnershipSnapshot(mindmap_id=1, owner_id=7, status=0)
        captured: dict = {}

        async def capture_share(_db: object, data: dict) -> None:
            captured.update(data)

        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(MindmapShareDao, 'add_share', new=capture_share),
        ):
            result = await MindmapShareService.create_share_link(
                db,
                MindmapShareCreateModel(mindmapId=1, shareType=1),
                user_id=7,
            )

        self.assertTrue(result.is_success)
        self.assertEqual(captured['share_type'], 1)
        db.commit.assert_awaited_once()

    async def test_past_expiry_is_rejected_before_database_access(self) -> None:
        with self.assertRaises(ServiceException) as context:
            await MindmapShareService.create_share_link(
                None,
                MindmapShareCreateModel(
                    mindmapId=1,
                    expireTime=datetime.now() - timedelta(minutes=1),
                ),
                user_id=1,
            )

        self.assertIn('晚于当前时间', context.exception.message)

    async def test_timezone_aware_future_expiry_is_accepted_and_normalized(self) -> None:
        mindmap = MindmapOwnershipSnapshot(mindmap_id=1, owner_id=7, status=0)
        captured: dict = {}

        async def capture_share(_db: object, data: dict) -> None:
            captured.update(data)

        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(MindmapShareDao, 'add_share', new=capture_share),
        ):
            result = await MindmapShareService.create_share_link(
                db,
                MindmapShareCreateModel(
                    mindmapId=1,
                    expireTime=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
                user_id=7,
            )

        self.assertTrue(result.is_success)
        self.assertIsNone(captured['expire_time'].tzinfo)
        db.commit.assert_awaited_once()

    async def test_share_list_is_materialized_from_scalar_snapshots(self) -> None:
        ownership = MindmapOwnershipSnapshot(
            mindmap_id=8,
            owner_id=7,
            status=0,
        )
        created_time = datetime.now()
        share = MindmapShareListSnapshot(
            id=12,
            mindmap_id=8,
            share_token='a' * 32,
            share_type=0,
            expire_time=None,
            created_by=7,
            created_time=created_time,
            is_active=1,
        )
        with (
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=ownership),
            ),
            patch.object(
                MindmapShareDao,
                'get_shares_by_mindmap_id',
                new=AsyncMock(return_value=[share]),
            ),
        ):
            result = await MindmapShareService.get_share_list(
                SimpleNamespace(),
                mindmap_id=8,
                user_id=7,
            )

        self.assertEqual(result[0].mindmap_id, 8)
        self.assertEqual(result[0].share_token, 'a' * 32)
        self.assertEqual(result[0].created_time, created_time)

    async def test_delete_share_uses_scalar_snapshots_through_commit(self) -> None:
        share = MindmapShareAccessSnapshot(
            mindmap_id=8,
            share_type=0,
            expire_time=None,
            created_by=7,
            is_active=1,
        )
        ownership = MindmapOwnershipSnapshot(
            mindmap_id=8,
            owner_id=7,
            status=0,
        )
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        deactivate = AsyncMock()
        with (
            patch.object(
                MindmapShareDao,
                'get_share_by_id',
                new=AsyncMock(return_value=share),
            ),
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=ownership),
            ),
            patch.object(MindmapShareDao, 'deactivate_share', new=deactivate),
        ):
            result = await MindmapShareService.delete_share_link(
                db,
                share_id=12,
                user_id=7,
            )

        self.assertTrue(result.is_success)
        deactivate.assert_awaited_once_with(db, 12)
        db.commit.assert_awaited_once()

    async def test_invalid_public_token_is_rejected_without_database_query(self) -> None:
        lookup = AsyncMock()
        with (
            patch.object(MindmapShareDao, 'get_share_access_snapshot', new=lookup),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapShareService.view_by_share_token(None, '../invalid-token')

        self.assertIn('不存在', context.exception.message)
        lookup.assert_not_awaited()

    async def test_failed_migration_public_view_uses_legacy_snapshot(self) -> None:
        legacy_tree = {'data': {'uid': 'root', 'text': '旧快照'}, 'children': []}
        share = MindmapShareAccessSnapshot(
            is_active=1,
            expire_time=None,
            mindmap_id=8,
            share_type=0,
            created_by=7,
        )
        mindmap = SharedMindmapSnapshot(
            mindmap_id=8,
            name='迁移保护文件',
            schema_version=2,
            content_revision=4,
            node_tree=legacy_tree,
            layout='logicalStructure',
            theme=None,
            view_data=None,
            document_data={'simpleMindMap': {'config': {'imgTextMargin': 11}}},
        )
        structured_loader = AsyncMock(return_value={
            'data': {'uid': 'root', 'text': '不完整新表'}, 'children': [],
        })
        db = SimpleNamespace(rollback=AsyncMock())
        with (
            patch.object(
                MindmapShareDao,
                'get_share_access_snapshot',
                new=AsyncMock(side_effect=[share, share]),
            ),
            patch.object(
                MindmapShareDao,
                'get_shared_mindmap_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(MindmapDao, 'get_migration_status', new=AsyncMock(return_value='failed')),
            patch.object(MindmapDocumentService, 'load_tree', new=structured_loader),
        ):
            result = await MindmapShareService.view_by_share_token(db, 'a' * 32)

        self.assertEqual(result['documentData']['simpleMindMap']['config']['imgTextMargin'], 11)

        self.assertEqual(result['nodeTree'], legacy_tree)
        structured_loader.assert_not_awaited()
        self.assertEqual(db.rollback.await_count, 2)

    async def test_edit_link_public_view_only_exposes_join_metadata(self) -> None:
        share = MindmapShareAccessSnapshot(
            is_active=1,
            expire_time=None,
            mindmap_id=8,
            share_type=1,
            created_by=7,
        )
        mindmap = SharedMindmapSnapshot(
            mindmap_id=8,
            name='协作邀请',
            node_tree='{}',
            layout='logicalStructure',
            theme=None,
            view_data=None,
            document_data=None,
            schema_version=2,
            content_revision=4,
        )
        structured_loader = AsyncMock()
        db = SimpleNamespace(rollback=AsyncMock())
        with (
            patch.object(
                MindmapShareDao,
                'get_share_access_snapshot',
                new=AsyncMock(side_effect=[share, share]),
            ),
            patch.object(
                MindmapShareDao,
                'get_shared_mindmap_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(MindmapDocumentService, 'load_tree', new=structured_loader),
        ):
            result = await MindmapShareService.view_by_share_token(db, 'b' * 32)

        self.assertEqual(result, {
            'name': '协作邀请',
            'shareType': 1,
            'requiresLogin': True,
        })
        structured_loader.assert_not_awaited()
        self.assertEqual(db.rollback.await_count, 2)

    async def test_public_view_materializes_tree_before_releasing_locked_revision(self) -> None:
        old_tree = {'data': {'uid': 'root', 'text': 'revision-4'}, 'children': []}
        share = MindmapShareAccessSnapshot(
            is_active=1,
            expire_time=None,
            mindmap_id=8,
            share_type=0,
            created_by=7,
        )
        mindmap = SharedMindmapSnapshot(
            mindmap_id=8,
            name='revision-4',
            node_tree='{}',
            layout='logicalStructure',
            theme={'template': 'revision-4'},
            view_data=None,
            document_data=None,
            schema_version=2,
            content_revision=4,
        )
        main_row_locked = asyncio.Event()
        read_transaction_released = asyncio.Event()
        writer_committed = asyncio.Event()
        final_rollback_number = 2

        async def lock_mindmap(*_args: Any, **_kwargs: Any) -> SharedMindmapSnapshot:
            self.assertEqual(rollback_count, 1)
            main_row_locked.set()
            return mindmap

        async def load_tree(*_args: Any, **_kwargs: Any) -> dict:
            await asyncio.sleep(0)
            self.assertFalse(writer_committed.is_set())
            return old_tree

        rollback_count = 0

        async def rollback() -> None:
            nonlocal rollback_count
            rollback_count += 1
            if rollback_count == final_rollback_number:
                read_transaction_released.set()

        async def writer() -> None:
            await main_row_locked.wait()
            await read_transaction_released.wait()
            writer_committed.set()

        db = SimpleNamespace(rollback=AsyncMock(side_effect=rollback))
        writer_task = asyncio.create_task(writer())
        with (
            patch.object(
                MindmapShareDao,
                'get_share_access_snapshot',
                new=AsyncMock(side_effect=[share, share]),
            ),
            patch.object(
                MindmapShareDao,
                'get_shared_mindmap_snapshot',
                new=lock_mindmap,
            ),
            patch.object(MindmapDao, 'get_migration_status', new=AsyncMock(return_value='done')),
            patch.object(MindmapDocumentService, 'load_tree', new=load_tree),
        ):
            result = await MindmapShareService.view_by_share_token(db, '2' * 32)
        await writer_task

        self.assertEqual(result['name'], 'revision-4')
        self.assertEqual(result['theme'], {'template': 'revision-4'})
        self.assertEqual(result['nodeTree'], old_tree)
        self.assertTrue(writer_committed.is_set())
        self.assertEqual(db.rollback.await_count, 2)

    async def test_join_freezes_response_before_commit_invalidates_snapshots(self) -> None:
        share = SimpleNamespace(
            mindmap_id=8,
            share_type=1,
            is_active=1,
            expire_time=None,
            created_by=7,
        )
        mindmap = SimpleNamespace(mindmap_id=8, owner_id=7, status=0)
        async def expire_mindmap_after_commit() -> None:
            for attribute in ('mindmap_id', 'owner_id', 'status'):
                delattr(mindmap, attribute)
            for attribute in ('mindmap_id', 'share_type', 'created_by', 'is_active'):
                delattr(share, attribute)

        db = SimpleNamespace(
            commit=AsyncMock(side_effect=expire_mindmap_after_commit),
            rollback=AsyncMock(),
        )
        add_collaborator = AsyncMock()
        with (
            patch.object(
                MindmapShareDao,
                'get_share_access_snapshot',
                new=AsyncMock(side_effect=[share, share]),
            ),
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(MindmapCollaboratorDao, 'is_active_user', new=AsyncMock(return_value=True)),
            patch.object(MindmapCollaboratorDao, 'get_collaborator', new=AsyncMock(return_value=None)),
            patch.object(MindmapCollaboratorDao, 'add_collaborator', new=add_collaborator),
        ):
            result = await MindmapShareService.join_edit_share(db, 'c' * 32, user_id=9)

        self.assertEqual(result.mindmap_id, 8)
        self.assertEqual(result.permission, 1)
        self.assertFalse(result.already_joined)
        self.assertEqual(add_collaborator.await_args.args[1]['created_by'], 7)
        self.assertEqual(add_collaborator.await_args.args[1]['permission'], 1)
        db.commit.assert_awaited_once()
        db.rollback.assert_awaited_once()

    async def test_edit_invitation_upgrades_an_existing_viewer(self) -> None:
        share = SimpleNamespace(
            mindmap_id=8,
            share_type=1,
            is_active=1,
            expire_time=None,
            created_by=7,
        )
        mindmap = MindmapOwnershipSnapshot(mindmap_id=8, owner_id=7, status=0)
        collaborator = SimpleNamespace(id=12, permission=0)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        update_permission = AsyncMock()
        with (
            patch.object(
                MindmapShareDao,
                'get_share_access_snapshot',
                new=AsyncMock(side_effect=[share, share]),
            ),
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(MindmapCollaboratorDao, 'is_active_user', new=AsyncMock(return_value=True)),
            patch.object(
                MindmapCollaboratorDao,
                'get_collaborator',
                new=AsyncMock(return_value=collaborator),
            ),
            patch.object(MindmapCollaboratorDao, 'update_permission', new=update_permission),
        ):
            result = await MindmapShareService.join_edit_share(db, 'd' * 32, user_id=9)

        self.assertFalse(result.already_joined)
        update_permission.assert_awaited_once_with(db, 12, 1)
        db.commit.assert_awaited_once()
        db.rollback.assert_awaited_once()

    async def test_existing_editor_can_reuse_an_edit_invitation_idempotently(self) -> None:
        share = SimpleNamespace(
            mindmap_id=8,
            share_type=1,
            is_active=1,
            expire_time=None,
            created_by=7,
        )
        mindmap = MindmapOwnershipSnapshot(mindmap_id=8, owner_id=7, status=0)
        collaborator = SimpleNamespace(id=12, permission=1)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        update_permission = AsyncMock()
        add_collaborator = AsyncMock()
        with (
            patch.object(
                MindmapShareDao,
                'get_share_access_snapshot',
                new=AsyncMock(side_effect=[share, share]),
            ),
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(MindmapCollaboratorDao, 'is_active_user', new=AsyncMock(return_value=True)),
            patch.object(
                MindmapCollaboratorDao,
                'get_collaborator',
                new=AsyncMock(return_value=collaborator),
            ),
            patch.object(MindmapCollaboratorDao, 'update_permission', new=update_permission),
            patch.object(MindmapCollaboratorDao, 'add_collaborator', new=add_collaborator),
        ):
            result = await MindmapShareService.join_edit_share(db, 'f' * 32, user_id=9)

        self.assertTrue(result.already_joined)
        update_permission.assert_not_awaited()
        add_collaborator.assert_not_awaited()
        db.commit.assert_awaited_once()
        db.rollback.assert_awaited_once()

    async def test_owner_uses_edit_invitation_without_creating_a_collaborator(self) -> None:
        share = SimpleNamespace(
            mindmap_id=8,
            share_type=1,
            is_active=1,
            expire_time=None,
            created_by=7,
        )
        mindmap = SimpleNamespace(mindmap_id=8, owner_id=7, status=0)
        rollback_count = 0
        final_rollback_number = 2

        async def expire_mindmap_after_rollback() -> None:
            nonlocal rollback_count
            rollback_count += 1
            if rollback_count == final_rollback_number:
                for attribute in ('mindmap_id', 'owner_id', 'status'):
                    delattr(mindmap, attribute)

        db = SimpleNamespace(
            commit=AsyncMock(),
            rollback=AsyncMock(side_effect=expire_mindmap_after_rollback),
        )
        active_user = AsyncMock()
        with (
            patch.object(
                MindmapShareDao,
                'get_share_access_snapshot',
                new=AsyncMock(side_effect=[share, share]),
            ),
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            patch.object(MindmapCollaboratorDao, 'is_active_user', new=active_user),
        ):
            result = await MindmapShareService.join_edit_share(db, '1' * 32, user_id=7)

        self.assertTrue(result.already_joined)
        active_user.assert_not_awaited()
        self.assertEqual(db.rollback.await_count, 2)
        db.commit.assert_not_awaited()

    async def test_archived_mindmap_rejects_edit_invitation_join(self) -> None:
        share = SimpleNamespace(
            mindmap_id=8,
            share_type=1,
            is_active=1,
            expire_time=None,
            created_by=7,
        )
        mindmap = MindmapOwnershipSnapshot(mindmap_id=8, owner_id=7, status=1)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapShareDao,
                'get_share_access_snapshot',
                new=AsyncMock(side_effect=[share, share]),
            ),
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapShareService.join_edit_share(db, '2' * 32, user_id=9)

        self.assertIn('已归档', context.exception.message)
        self.assertEqual(db.rollback.await_count, 2)
        db.commit.assert_not_awaited()

    async def test_readonly_link_cannot_be_claimed_as_edit_permission(self) -> None:
        share = SimpleNamespace(
            mindmap_id=8,
            share_type=0,
            is_active=1,
            expire_time=None,
            created_by=7,
        )
        mindmap = MindmapOwnershipSnapshot(mindmap_id=8, owner_id=7, status=0)
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        with (
            patch.object(
                MindmapShareDao,
                'get_share_access_snapshot',
                new=AsyncMock(side_effect=[share, share]),
            ),
            patch.object(
                MindmapShareDao,
                'get_mindmap_ownership_snapshot',
                new=AsyncMock(return_value=mindmap),
            ),
            self.assertRaises(ServiceException) as context,
        ):
            await MindmapShareService.join_edit_share(db, 'e' * 32, user_id=9)

        self.assertIn('仅支持查看', context.exception.message)
        self.assertEqual(db.rollback.await_count, 2)
        db.commit.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
