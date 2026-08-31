"""Yjs 文档持久化管理。"""

import struct

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_ws_state_do import MindmapWsState
from module_mindmap.service.mindmap_metrics import record_mindmap_event

STATE_BUNDLE_MAGIC = b'MMYS2\x00'
MAX_STATE_SOURCE_COUNT = 32
MAX_STATE_SOURCE_ID_BYTES = 128
MAX_STATE_BUNDLE_BYTES = 15 * 1024 * 1024


def normalize_yjs_state_source_ids(values: object) -> list[str] | None:
    """校验客户端声明已合并的有限来源列表；None 表示协议无效。"""
    if not isinstance(values, list) or len(values) > MAX_STATE_SOURCE_COUNT:
        return None
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            return None
        source_id = value.strip()
        if (
            not source_id
            or len(source_id.encode('utf-8')) > MAX_STATE_SOURCE_ID_BYTES
            or source_id in seen
        ):
            return None
        seen.add(source_id)
        result.append(source_id)
    return result


def normalize_yjs_state_source_changes(
    replace_values: object,
    invalid_values: object,
) -> tuple[list[str], list[str], list[str]] | None:
    """校验已合并与损坏来源；返回两组及可原子替换的有界并集。"""
    replace_source_ids = normalize_yjs_state_source_ids(replace_values)
    invalid_source_ids = normalize_yjs_state_source_ids(invalid_values)
    if replace_source_ids is None or invalid_source_ids is None:
        return None
    replacement_ids = [*replace_source_ids, *invalid_source_ids]
    if (
        len(replacement_ids) > MAX_STATE_SOURCE_COUNT
        or len(set(replacement_ids)) != len(replacement_ids)
    ):
        return None
    return replace_source_ids, invalid_source_ids, replacement_ids


def unpack_yjs_state_bundle(blob: bytes | None) -> dict[str, bytes]:
    """读取多源状态包；旧版单状态二进制自动作为 legacy 源兼容。"""
    if not blob:
        return {}
    if len(blob) > MAX_STATE_BUNDLE_BYTES:
        raise ValueError('Yjs 状态包超过持久化上限')
    if not blob.startswith(STATE_BUNDLE_MAGIC):
        return {'legacy': bytes(blob)}
    offset = len(STATE_BUNDLE_MAGIC)
    try:
        (count,) = struct.unpack_from('>H', blob, offset)
        offset += 2
        if count > MAX_STATE_SOURCE_COUNT:
            raise ValueError('Yjs 状态源数量超过限制')
        states = {}
        for _ in range(count):
            (key_length,) = struct.unpack_from('>H', blob, offset)
            offset += 2
            if not key_length or key_length > MAX_STATE_SOURCE_ID_BYTES:
                raise ValueError('Yjs 状态源标识无效')
            key_bytes = blob[offset:offset + key_length]
            if len(key_bytes) != key_length:
                raise ValueError('Yjs 状态源标识不完整')
            offset += key_length
            (state_length,) = struct.unpack_from('>I', blob, offset)
            offset += 4
            if state_length > MAX_STATE_BUNDLE_BYTES:
                raise ValueError('Yjs 状态内容超过持久化上限')
            state = blob[offset:offset + state_length]
            if len(state) != state_length:
                raise ValueError('Yjs 状态内容不完整')
            offset += state_length
            source_id = key_bytes.decode('utf-8')
            if source_id in states:
                raise ValueError('Yjs 状态源标识重复')
            states[source_id] = bytes(state)
        if offset != len(blob):
            raise ValueError('Yjs 状态包包含尾随数据')
        return states
    except (UnicodeDecodeError, struct.error) as exc:
        raise ValueError('Yjs 状态包格式损坏') from exc


def pack_yjs_state_bundle(states: dict[str, bytes]) -> bytes:
    """把多个客户端的完整状态封装为一个可向后识别的二进制包。"""
    if len(states) > MAX_STATE_SOURCE_COUNT:
        raise ValueError('Yjs 状态源数量超过限制')
    chunks = [STATE_BUNDLE_MAGIC, struct.pack('>H', len(states))]
    for source_id, state in states.items():
        key = source_id.encode('utf-8')
        if not key or len(key) > MAX_STATE_SOURCE_ID_BYTES:
            raise ValueError('Yjs 状态源标识无效')
        if not isinstance(state, bytes) or not state or len(state) > MAX_STATE_BUNDLE_BYTES:
            raise ValueError('Yjs 状态内容无效或超过持久化上限')
        chunks.extend((
            struct.pack('>H', len(key)),
            key,
            struct.pack('>I', len(state)),
            state,
        ))
    result = b''.join(chunks)
    if len(result) > MAX_STATE_BUNDLE_BYTES:
        raise ValueError('Yjs 状态包超过持久化上限')
    return result


def merge_yjs_state_bundle(
    blob: bytes | None,
    source_id: str,
    state: bytes,
    replace_source_ids: list[str] | None = None,
) -> bytes:
    """保留并发来源，只替换客户端明确证明已合并的旧来源。"""
    source_id = str(source_id).strip()
    if not source_id or not state:
        raise ValueError('Yjs 状态来源和内容不能为空')
    normalized_replacements = normalize_yjs_state_source_ids(replace_source_ids or [])
    if normalized_replacements is None:
        raise ValueError('Yjs 已合并状态源列表无效')
    states = unpack_yjs_state_bundle(blob)
    for replaced_source_id in normalized_replacements:
        states.pop(replaced_source_id, None)
    # 多个连接可能在合并后提交完全相同的完整状态。保留重复副本只会快速
    # 消耗来源数量和总字节上限，不提供额外恢复信息。
    for key in [key for key, value in states.items() if value == state]:
        states.pop(key, None)
    states.pop(source_id, None)
    states[source_id] = bytes(state)
    return pack_yjs_state_bundle(states)


class YjsDocManager:
    """Yjs 文档的数据库持久化。"""

    @classmethod
    async def load_state_entries(cls, db: AsyncSession, mindmap_id: int) -> dict[str, bytes]:
        """加载与主文件 revision 一致的来源和状态，供安全压缩确认。"""
        result = (await db.execute(
            select(MindmapWsState.yjs_state, MindmapWsState.content_revision, Mindmap.content_revision)
            .join(Mindmap, Mindmap.id == MindmapWsState.mindmap_id)
            .where(MindmapWsState.mindmap_id == mindmap_id)
        )).first()
        if not result:
            return {}
        state_blob, state_revision, file_revision = result
        if state_revision != file_revision:
            record_mindmap_event('yjs_revision_mismatch')
            return {}
        return unpack_yjs_state_bundle(state_blob)

    @classmethod
    async def load_states(cls, db: AsyncSession, mindmap_id: int) -> list[bytes]:
        """兼容只消费状态内容的调用方。"""
        entries = await cls.load_state_entries(db, mindmap_id)
        return list(entries.values())

    @classmethod
    async def load_state(cls, db: AsyncSession, mindmap_id: int) -> bytes | None:
        """兼容旧调用；多源状态请使用 load_states。"""
        states = await cls.load_states(db, mindmap_id)
        return states[-1] if states else None

    @classmethod
    async def save_state(
        cls,
        db: AsyncSession,
        mindmap_id: int,
        state: bytes,
        content_revision: int | None = None,
        source_id: str = 'default',
        replace_source_ids: list[str] | None = None,
    ) -> bool:
        """按来源合并保存同 revision 的完整 Yjs 状态。"""
        for attempt in range(2):
            existing = (await db.execute(
                select(MindmapWsState)
                .where(MindmapWsState.mindmap_id == mindmap_id)
                .with_for_update()
            )).scalar_one_or_none()
            current_revision = (await db.execute(
                select(Mindmap.content_revision).where(
                    Mindmap.id == mindmap_id,
                    Mindmap.del_flag == '0',
                )
            )).scalar_one_or_none()
            if content_revision is None or content_revision != current_revision:
                record_mindmap_event('yjs_revision_mismatch')
                await db.rollback()
                return False
            previous_blob = (
                existing.yjs_state
                if existing and existing.content_revision == content_revision
                else None
            )
            try:
                unpack_yjs_state_bundle(previous_blob)
            except ValueError:
                # 损坏的协作缓存不是主数据；允许当前合法完整状态自愈覆盖。
                previous_blob = None
            try:
                state_bundle = merge_yjs_state_bundle(
                    previous_blob,
                    source_id,
                    state,
                    replace_source_ids,
                )
            except ValueError:
                record_mindmap_event('yjs_state_persist_failure')
                await db.rollback()
                return False

            if existing:
                await db.execute(
                    update(MindmapWsState)
                    .where(MindmapWsState.mindmap_id == mindmap_id)
                    .values(yjs_state=state_bundle, content_revision=content_revision)
                )
            else:
                db.add(MindmapWsState(
                    mindmap_id=mindmap_id,
                    yjs_state=state_bundle,
                    content_revision=content_revision,
                ))
            try:
                await db.commit()
                return True
            except IntegrityError:
                await db.rollback()
                # 两个连接首次写入同一房间时，唯一键只能由一个获胜；
                # 失败方重新锁定胜者行，再把自己的状态合并进去。
                if existing or attempt:
                    record_mindmap_event('yjs_state_persist_failure')
                    return False
        return False
