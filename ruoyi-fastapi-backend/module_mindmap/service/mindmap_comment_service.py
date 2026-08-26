"""脑图评论业务层。"""
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_comment_dao import MindmapCommentDao
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.vo.mindmap_comment_vo import (
    MindmapCommentCreateModel,
    MindmapCommentReplyModel,
)
from module_mindmap.service.mindmap_service import MindmapService
from utils.log_util import logger

MIN_COMMENT_REQUEST_ID_LENGTH = 16
MAX_COMMENT_REQUEST_ID_LENGTH = 100
COMMENT_REQUEST_ID_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9._:-]*$'
_COMMENT_REQUEST_ID_RE = re.compile(COMMENT_REQUEST_ID_PATTERN)


class MindmapCommentService:
    """评论线程读写与访问控制。"""

    @classmethod
    async def list_threads(
        cls,
        db: AsyncSession,
        mindmap_id: int,
        user_id: int,
        *,
        status: Literal['open', 'resolved', 'all'] = 'open',
        node_uid: str | None = None,
        page_num: int = 1,
        page_size: int = 50,
    ) -> dict:
        mindmap, permission, is_owner = await MindmapService.resolve_mindmap_access(
            db, mindmap_id, user_id, require_edit=False,
        )
        normalized_node_uid = node_uid.strip() if node_uid else None
        rows, total = await MindmapCommentDao.list_threads(
            db,
            mindmap_id,
            status=status,
            node_uid=normalized_node_uid,
            offset=(page_num - 1) * page_size,
            limit=page_size,
        )
        messages = await MindmapCommentDao.list_messages(db, [row.id for row in rows])
        messages_by_thread = defaultdict(list)
        for message in messages:
            author_name = message.nick_name or message.user_name or str(message.created_by)
            messages_by_thread[message.thread_id].append({
                'id': message.id,
                'threadId': message.thread_id,
                'content': message.content,
                'createdBy': message.created_by,
                'authorName': author_name,
                'avatar': message.avatar or '',
                'createdTime': message.created_time,
                'updateTime': message.update_time,
                'canDelete': is_owner or message.created_by == user_id,
            })
        open_count, node_counts = await MindmapCommentDao.get_open_summary(db, mindmap_id)
        can_comment = mindmap.status == 0
        result_rows = []
        for row in rows:
            can_resolve = is_owner or permission >= 1 or row.created_by == user_id
            result_rows.append({
                'id': row.id,
                'mindmapId': row.mindmap_id,
                'nodeUid': row.node_uid,
                'nodeText': row.node_text or '',
                'status': row.status,
                'createdBy': row.created_by,
                'createdTime': row.created_time,
                'lastCommentTime': row.last_comment_time,
                'resolvedBy': row.resolved_by,
                'resolvedTime': row.resolved_time,
                'messages': messages_by_thread.get(row.id, []),
                'canResolve': can_comment and can_resolve,
                'canReply': can_comment,
            })
        return {
            'rows': result_rows,
            'total': total,
            'pageNum': page_num,
            'pageSize': page_size,
            'canComment': can_comment,
            'summary': {
                'openCount': open_count,
                'nodeCounts': node_counts,
            },
        }

    @classmethod
    async def create_thread(
        cls,
        db: AsyncSession,
        model: MindmapCommentCreateModel,
        user_id: int,
        request_id: str | None = None,
    ) -> dict:
        normalized_request_id = cls._normalize_request_id(request_id)
        if normalized_request_id:
            existing = await MindmapCommentDao.get_by_request_id(
                db, user_id, normalized_request_id,
            )
            if existing:
                await cls._ensure_comment_access(db, model.mindmap_id, user_id)
                return cls._resolve_replay(
                    existing,
                    mindmap_id=model.mindmap_id,
                    node_uid=model.node_uid,
                    content=model.content,
                    kind='thread',
                )
        await cls._ensure_comment_writable(db, model.mindmap_id, user_id)
        node = await MindmapCommentDao.get_active_node(db, model.mindmap_id, model.node_uid)
        if not node:
            raise ServiceException(message='评论节点不存在或已被删除')
        now = datetime.now()
        node_text = (node.text_plain or '').strip()[:500]
        try:
            thread, comment = await MindmapCommentDao.create_thread(
                db,
                mindmap_id=model.mindmap_id,
                node_uid=model.node_uid,
                node_text=node_text,
                content=model.content,
                user_id=user_id,
                request_id=normalized_request_id,
                now=now,
            )
            # AsyncSession 默认会在 commit 后过期 ORM 实例。提前保存响应和广播所需的
            # 标量，避免提交后访问属性触发异步上下文外的隐式查询（MissingGreenlet）。
            thread_id = thread.id
            comment_id = comment.id
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if not normalized_request_id:
                raise
            existing = await MindmapCommentDao.get_by_request_id(
                db, user_id, normalized_request_id,
            )
            if not existing:
                raise
            return cls._resolve_replay(
                existing,
                mindmap_id=model.mindmap_id,
                node_uid=model.node_uid,
                content=model.content,
                kind='thread',
            )
        except Exception:
            await db.rollback()
            raise
        await cls._broadcast_change(model.mindmap_id, 'created', thread_id, model.node_uid)
        return {'threadId': thread_id, 'commentId': comment_id, 'idempotentReplay': False}

    @classmethod
    async def reply_thread(
        cls,
        db: AsyncSession,
        thread_id: int,
        model: MindmapCommentReplyModel,
        user_id: int,
        request_id: str | None = None,
    ) -> dict:
        normalized_request_id = cls._normalize_request_id(request_id)
        if normalized_request_id:
            existing = await MindmapCommentDao.get_by_request_id(
                db, user_id, normalized_request_id,
            )
            if existing:
                await cls._ensure_comment_access(db, existing.mindmap_id, user_id)
                return cls._resolve_replay(
                    existing,
                    mindmap_id=existing.mindmap_id,
                    thread_id=thread_id,
                    content=model.content,
                    kind='reply',
                )
        thread = await MindmapCommentDao.get_thread_for_update(db, thread_id)
        if not thread:
            await db.rollback()
            raise ServiceException(message='评论线程不存在')
        await cls._ensure_comment_writable(db, thread.mindmap_id, user_id)
        mindmap_id = thread.mindmap_id
        node_uid = thread.node_uid
        persisted_thread_id = thread.id
        now = datetime.now()
        try:
            comment = await MindmapCommentDao.create_reply(
                db,
                thread,
                model.content,
                user_id,
                normalized_request_id,
                now,
            )
            if thread.status == 1:
                await MindmapCommentDao.update_status(
                    thread, resolved=False, user_id=user_id, now=now,
                )
            comment_id = comment.id
            await db.commit()
        except IntegrityError:
            await db.rollback()
            if not normalized_request_id:
                raise
            existing = await MindmapCommentDao.get_by_request_id(
                db, user_id, normalized_request_id,
            )
            if not existing:
                raise
            return cls._resolve_replay(
                existing,
                mindmap_id=mindmap_id,
                thread_id=persisted_thread_id,
                content=model.content,
                kind='reply',
            )
        except Exception:
            await db.rollback()
            raise
        await cls._broadcast_change(mindmap_id, 'replied', persisted_thread_id, node_uid)
        return {
            'threadId': persisted_thread_id,
            'commentId': comment_id,
            'idempotentReplay': False,
        }

    @classmethod
    async def set_thread_status(
        cls,
        db: AsyncSession,
        thread_id: int,
        resolved: bool,
        user_id: int,
    ) -> None:
        thread = await MindmapCommentDao.get_thread_for_update(db, thread_id)
        if not thread:
            await db.rollback()
            raise ServiceException(message='评论线程不存在')
        _, permission, is_owner = await MindmapService.resolve_mindmap_access(
            db, thread.mindmap_id, user_id, require_edit=False,
        )
        if not (is_owner or permission >= 1 or thread.created_by == user_id):
            await db.rollback()
            raise ServiceException(message='只有线程创建者或可编辑协作者可以处理评论')
        await cls._ensure_comment_writable(db, thread.mindmap_id, user_id)
        mindmap_id = thread.mindmap_id
        node_uid = thread.node_uid
        persisted_thread_id = thread.id
        target_status = 1 if resolved else 0
        if thread.status == target_status:
            await db.rollback()
            return
        now = datetime.now()
        try:
            await MindmapCommentDao.update_status(
                thread, resolved=resolved, user_id=user_id, now=now,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        await cls._broadcast_change(
            mindmap_id,
            'resolved' if resolved else 'reopened',
            persisted_thread_id,
            node_uid,
        )

    @classmethod
    async def delete_comment(
        cls,
        db: AsyncSession,
        comment_id: int,
        user_id: int,
    ) -> dict:
        comment = await MindmapCommentDao.get_comment(db, comment_id, include_deleted=True)
        if not comment:
            raise ServiceException(message='评论不存在')
        thread = await MindmapCommentDao.get_thread_for_update(
            db, comment.thread_id, include_deleted=True,
        )
        if not thread:
            await db.rollback()
            raise ServiceException(message='评论线程不存在')
        _, _, is_owner = await MindmapService.resolve_mindmap_access(
            db, thread.mindmap_id, user_id, require_edit=False,
        )
        if not (is_owner or comment.created_by == user_id):
            await db.rollback()
            raise ServiceException(message='只能删除自己的评论')
        if comment.del_flag != '0' or thread.del_flag != '0':
            await db.rollback()
            return {
                'threadId': thread.id,
                'threadDeleted': thread.del_flag != '0',
                'alreadyDeleted': True,
            }
        await cls._ensure_comment_writable(db, thread.mindmap_id, user_id)
        mindmap_id = thread.mindmap_id
        node_uid = thread.node_uid
        persisted_thread_id = thread.id
        now = datetime.now()
        action = 'deleted'
        try:
            if comment.created_by == thread.created_by and comment.id == (
                min(
                    message.id
                    for message in await cls._active_thread_messages(db, thread.id)
                )
            ):
                await MindmapCommentDao.soft_delete_thread(db, thread.id, now)
                action = 'thread_deleted'
            else:
                await MindmapCommentDao.soft_delete_comment(db, comment.id, now)
                remaining = await MindmapCommentDao.count_active_messages(db, thread.id)
                if remaining == 0:
                    await MindmapCommentDao.soft_delete_thread(db, thread.id, now)
                    action = 'thread_deleted'
                else:
                    await MindmapCommentDao.touch_thread_from_latest_comment(db, thread.id, now)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        await cls._broadcast_change(mindmap_id, action, persisted_thread_id, node_uid)
        return {
            'threadId': persisted_thread_id,
            'threadDeleted': action == 'thread_deleted',
            'alreadyDeleted': False,
        }

    @staticmethod
    def _normalize_request_id(request_id: str | None) -> str | None:
        if request_id is None:
            return None
        value = request_id.strip() if isinstance(request_id, str) else ''
        if not (
            MIN_COMMENT_REQUEST_ID_LENGTH <= len(value) <= MAX_COMMENT_REQUEST_ID_LENGTH
            and _COMMENT_REQUEST_ID_RE.fullmatch(value)
        ):
            raise ServiceException(message='Idempotency-Key 格式无效')
        return value

    @staticmethod
    def _resolve_replay(
        existing: Row[Any],
        *,
        mindmap_id: int,
        content: str,
        kind: Literal['thread', 'reply'],
        node_uid: str | None = None,
        thread_id: int | None = None,
    ) -> dict:
        same_target = (
            existing.mindmap_id == mindmap_id
            and existing.content == content
            and bool(existing.is_thread_starter) == (kind == 'thread')
            and (node_uid is None or existing.node_uid == node_uid)
            and (thread_id is None or existing.thread_id == thread_id)
        )
        if not same_target:
            raise ServiceException(message='Idempotency-Key 已用于不同的评论请求')
        return {
            'threadId': existing.thread_id,
            'commentId': existing.id,
            'idempotentReplay': True,
        }

    @classmethod
    async def _active_thread_messages(cls, db: AsyncSession, thread_id: int) -> list:
        rows = await MindmapCommentDao.list_messages(db, [thread_id])
        if not rows:
            raise ServiceException(message='评论线程没有可用消息')
        return rows

    @classmethod
    async def _ensure_comment_writable(
        cls, db: AsyncSession, mindmap_id: int, user_id: int,
    ) -> Mindmap:
        mindmap = await cls._ensure_comment_access(db, mindmap_id, user_id)
        if mindmap.status == 1:
            raise ServiceException(message='脑图已归档，不能继续评论')
        return mindmap

    @staticmethod
    async def _ensure_comment_access(
        db: AsyncSession, mindmap_id: int, user_id: int,
    ) -> Mindmap:
        return await MindmapService.check_mindmap_access(
            db, mindmap_id, user_id, require_edit=False,
        )

    @staticmethod
    async def _broadcast_change(mindmap_id: int, action: str, thread_id: int, node_uid: str) -> None:
        try:
            from module_mindmap.websocket.room_manager import room_manager  # noqa: PLC0415

            await room_manager.broadcast(mindmap_id, {
                'type': 'comment_changed',
                'mindmapId': mindmap_id,
                'action': action,
                'threadId': thread_id,
                'nodeUid': node_uid,
            })
        except Exception as exc:
            logger.warning(
                '广播脑图评论变更失败: '
                f'mindmap_id={mindmap_id}, thread_id={thread_id}, error={exc}'
            )
