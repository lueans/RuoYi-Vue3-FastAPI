"""脑图评论数据访问层。"""
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from module_admin.entity.do.user_do import SysUser
from module_mindmap.entity.do.mindmap_comment_do import MindmapComment, MindmapCommentThread
from module_mindmap.entity.do.mindmap_content_do import MindmapNode


class MindmapCommentDao:
    """评论线程和消息查询。"""

    @classmethod
    async def get_active_node(cls, db: AsyncSession, mindmap_id: int, node_uid: str) -> MindmapNode | None:
        return (
            await db.execute(
                select(MindmapNode).where(
                    MindmapNode.file_id == mindmap_id,
                    MindmapNode.node_uid == node_uid,
                    MindmapNode.is_deleted == 0,
                )
            )
        ).scalars().first()

    @classmethod
    async def create_thread(
        cls,
        db: AsyncSession,
        *,
        mindmap_id: int,
        node_uid: str,
        node_text: str,
        content: str,
        user_id: int,
        request_id: str | None,
        now: datetime,
    ) -> tuple[MindmapCommentThread, MindmapComment]:
        thread = MindmapCommentThread(
            mindmap_id=mindmap_id,
            node_uid=node_uid,
            node_text=node_text,
            status=0,
            created_by=user_id,
            created_time=now,
            last_comment_time=now,
            del_flag='0',
        )
        db.add(thread)
        await db.flush()
        comment = MindmapComment(
            thread_id=thread.id,
            mindmap_id=mindmap_id,
            content=content,
            created_by=user_id,
            client_request_id=request_id,
            created_time=now,
            del_flag='0',
        )
        db.add(comment)
        await db.flush()
        return thread, comment

    @classmethod
    async def get_thread(cls, db: AsyncSession, thread_id: int) -> MindmapCommentThread | None:
        return (
            await db.execute(
                select(MindmapCommentThread).where(
                    MindmapCommentThread.id == thread_id,
                    MindmapCommentThread.del_flag == '0',
                )
            )
        ).scalars().first()

    @classmethod
    async def get_thread_for_update(
        cls,
        db: AsyncSession,
        thread_id: int,
        *,
        include_deleted: bool = False,
    ) -> MindmapCommentThread | None:
        filters = [MindmapCommentThread.id == thread_id]
        if not include_deleted:
            filters.append(MindmapCommentThread.del_flag == '0')
        return (
            await db.execute(
                select(MindmapCommentThread)
                .where(*filters)
                .with_for_update()
            )
        ).scalars().first()

    @classmethod
    async def create_reply(
        cls,
        db: AsyncSession,
        thread: MindmapCommentThread,
        content: str,
        user_id: int,
        request_id: str | None,
        now: datetime,
    ) -> MindmapComment:
        comment = MindmapComment(
            thread_id=thread.id,
            mindmap_id=thread.mindmap_id,
            content=content,
            created_by=user_id,
            client_request_id=request_id,
            created_time=now,
            del_flag='0',
        )
        db.add(comment)
        thread.last_comment_time = now
        await db.flush()
        return comment

    @classmethod
    async def get_by_request_id(
        cls,
        db: AsyncSession,
        user_id: int,
        request_id: str,
    ) -> Row | None:
        """返回幂等键对应的原始写入；包含软删除记录以保持键不可复用。"""
        first_comment = aliased(MindmapComment)
        first_comment_id = (
            select(func.min(first_comment.id))
            .where(first_comment.thread_id == MindmapComment.thread_id)
            .correlate(MindmapComment)
            .scalar_subquery()
        )
        return (await db.execute(
            select(
                MindmapComment.id,
                MindmapComment.thread_id,
                MindmapComment.mindmap_id,
                MindmapComment.content,
                MindmapCommentThread.node_uid,
                (MindmapComment.id == first_comment_id).label('is_thread_starter'),
            )
            .join(MindmapCommentThread, MindmapCommentThread.id == MindmapComment.thread_id)
            .where(
                MindmapComment.created_by == user_id,
                MindmapComment.client_request_id == request_id,
            )
        )).first()

    @classmethod
    async def list_threads(
        cls,
        db: AsyncSession,
        mindmap_id: int,
        *,
        status: str,
        node_uid: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[MindmapCommentThread], int]:
        filters = [
            MindmapCommentThread.mindmap_id == mindmap_id,
            MindmapCommentThread.del_flag == '0',
        ]
        if status == 'open':
            filters.append(MindmapCommentThread.status == 0)
        elif status == 'resolved':
            filters.append(MindmapCommentThread.status == 1)
        if node_uid:
            filters.append(MindmapCommentThread.node_uid == node_uid)
        total = int((await db.execute(
            select(func.count(MindmapCommentThread.id)).where(*filters)
        )).scalar_one() or 0)
        rows = (
            await db.execute(
                select(MindmapCommentThread)
                .where(*filters)
                .order_by(MindmapCommentThread.last_comment_time.desc(), MindmapCommentThread.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
        return list(rows), total

    @classmethod
    async def list_messages(cls, db: AsyncSession, thread_ids: list[int]) -> list[Row]:
        if not thread_ids:
            return []
        return list((await db.execute(
            select(
                MindmapComment.id,
                MindmapComment.thread_id,
                MindmapComment.content,
                MindmapComment.created_by,
                MindmapComment.created_time,
                MindmapComment.update_time,
                SysUser.user_name,
                SysUser.nick_name,
                SysUser.avatar,
            )
            .outerjoin(SysUser, SysUser.user_id == MindmapComment.created_by)
            .where(
                MindmapComment.thread_id.in_(thread_ids),
                MindmapComment.del_flag == '0',
            )
            .order_by(MindmapComment.created_time.asc(), MindmapComment.id.asc())
        )).all())

    @classmethod
    async def get_open_summary(cls, db: AsyncSession, mindmap_id: int) -> tuple[int, dict[str, int]]:
        rows = (await db.execute(
            select(MindmapCommentThread.node_uid, func.count(MindmapCommentThread.id))
            .where(
                MindmapCommentThread.mindmap_id == mindmap_id,
                MindmapCommentThread.status == 0,
                MindmapCommentThread.del_flag == '0',
            )
            .group_by(MindmapCommentThread.node_uid)
        )).all()
        node_counts = {str(node_uid): int(count) for node_uid, count in rows}
        return sum(node_counts.values()), node_counts

    @classmethod
    async def update_status(
        cls,
        thread: MindmapCommentThread,
        *,
        resolved: bool,
        user_id: int,
        now: datetime,
    ) -> None:
        thread.status = 1 if resolved else 0
        thread.resolved_by = user_id if resolved else None
        thread.resolved_time = now if resolved else None
        thread.last_comment_time = now

    @classmethod
    async def get_comment(
        cls,
        db: AsyncSession,
        comment_id: int,
        *,
        include_deleted: bool = False,
    ) -> MindmapComment | None:
        filters = [MindmapComment.id == comment_id]
        if not include_deleted:
            filters.append(MindmapComment.del_flag == '0')
        return (
            await db.execute(
                select(MindmapComment).where(*filters)
            )
        ).scalars().first()

    @classmethod
    async def soft_delete_comment(cls, db: AsyncSession, comment_id: int, now: datetime) -> None:
        await db.execute(
            update(MindmapComment)
            .where(MindmapComment.id == comment_id, MindmapComment.del_flag == '0')
            .values(del_flag='2', update_time=now)
        )

    @classmethod
    async def soft_delete_thread(cls, db: AsyncSession, thread_id: int, now: datetime) -> None:
        await db.execute(
            update(MindmapCommentThread)
            .where(MindmapCommentThread.id == thread_id, MindmapCommentThread.del_flag == '0')
            .values(del_flag='2', last_comment_time=now)
        )
        await db.execute(
            update(MindmapComment)
            .where(MindmapComment.thread_id == thread_id, MindmapComment.del_flag == '0')
            .values(del_flag='2', update_time=now)
        )

    @classmethod
    async def count_active_messages(cls, db: AsyncSession, thread_id: int) -> int:
        return int((await db.execute(
            select(func.count(MindmapComment.id)).where(
                MindmapComment.thread_id == thread_id,
                MindmapComment.del_flag == '0',
            )
        )).scalar_one() or 0)

    @classmethod
    async def touch_thread_from_latest_comment(
        cls,
        db: AsyncSession,
        thread_id: int,
        fallback: datetime,
    ) -> None:
        latest = (await db.execute(
            select(func.max(MindmapComment.created_time)).where(
                MindmapComment.thread_id == thread_id,
                MindmapComment.del_flag == '0',
            )
        )).scalar_one_or_none()
        await db.execute(
            update(MindmapCommentThread)
            .where(MindmapCommentThread.id == thread_id)
            .values(last_comment_time=latest or fallback)
        )
