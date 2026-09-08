"""Yjs 文档持久化管理。"""

import base64
import hashlib
import struct

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_ws_state_do import MindmapWsState
from module_mindmap.service.mindmap_metrics import record_mindmap_event

# MMYS2 已经可能被多个版本的 worker 同时读写。继续使用该物理格式，
# 避免旧 worker 把未知的新 magic 当成一份原始 Yjs update 下发给客户端。
STATE_BUNDLE_MAGIC = b'MMYS2\x00'
# 仅用于读取本分支早期产生的未发布草案；新代码永远不再写 MMYS3。
DRAFT_STATE_BUNDLE_MAGIC = b'MMYS3\x00'
MAX_STATE_SOURCE_COUNT = 32
MAX_STATE_SOURCE_ID_BYTES = 128
MAX_STATE_BUNDLE_BYTES = 15 * 1024 * 1024
STATE_DIGEST_HEX_LENGTH = 64
MAX_LINEAGE_ID_BYTES = 128
LINEAGE_SOURCE_ID_PREFIX = '~mmyl1:'
ESCAPED_SOURCE_ID_PREFIX = '~mmyr1:'


def get_yjs_state_digest(state: bytes) -> str:
    return hashlib.sha256(state).hexdigest()


def normalize_yjs_lineage_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized.encode('utf-8')) > MAX_LINEAGE_ID_BYTES
    ):
        return None
    return normalized


def get_yjs_lineage_digest(lineage_id: object) -> str | None:
    """返回协议 lineage 的稳定摘要；持久化层不保存客户端原始标识。"""
    normalized = normalize_yjs_lineage_id(lineage_id)
    if normalized is None:
        return None
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def normalize_yjs_lineage_digest(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) != STATE_DIGEST_HEX_LENGTH
        or any(character not in '0123456789abcdef' for character in value)
    ):
        return None
    return value


def _encode_opaque_source_id(source_id: str, lineage_digest: str | None) -> str:
    """把 lineage 摘要放进 MMYS2 source id，旧 worker 可将其视作普通来源。"""
    if lineage_digest is not None:
        encoded = f'{LINEAGE_SOURCE_ID_PREFIX}{lineage_digest}:{source_id}'
        if len(encoded.encode('utf-8')) <= MAX_STATE_SOURCE_ID_BYTES:
            return encoded
        # source id 的公开上限仍为 128 bytes。极长的非运行时来源宁可退化为
        # 未知 lineage，也不能因增加元数据而破坏原有状态持久化 API。
        return source_id

    # 保留前缀属于物理编码命名空间。只有调用方真的使用了该外观时才转义，
    # 常规 UUID 来源不会增加任何体积。
    if source_id.startswith((LINEAGE_SOURCE_ID_PREFIX, ESCAPED_SOURCE_ID_PREFIX)):
        encoded_value = base64.urlsafe_b64encode(source_id.encode('utf-8')).decode().rstrip('=')
        encoded = f'{ESCAPED_SOURCE_ID_PREFIX}{encoded_value}'
        if len(encoded.encode('utf-8')) > MAX_STATE_SOURCE_ID_BYTES:
            raise ValueError('Yjs 状态源标识无法安全转义')
        return encoded
    return source_id


def _decode_opaque_source_id(persisted_source_id: str) -> tuple[str, str | None]:
    if persisted_source_id.startswith(ESCAPED_SOURCE_ID_PREFIX):
        encoded = persisted_source_id[len(ESCAPED_SOURCE_ID_PREFIX):]
        if not encoded:
            return persisted_source_id, None
        try:
            padding = '=' * (-len(encoded) % 4)
            source_id = base64.b64decode(
                f'{encoded}{padding}',
                altchars=b'-_',
                validate=True,
            ).decode('utf-8')
        except (UnicodeDecodeError, ValueError):
            # 此前 MMYS2 的 source id 没有保留命名空间。形似新前缀但并非
            # 本编码生成的旧来源必须继续按 opaque id 暴露，不能损坏整包。
            return persisted_source_id, None
        if (
            not source_id
            or len(source_id.encode('utf-8')) > MAX_STATE_SOURCE_ID_BYTES
            or not source_id.startswith((
                LINEAGE_SOURCE_ID_PREFIX,
                ESCAPED_SOURCE_ID_PREFIX,
            ))
        ):
            return persisted_source_id, None
        return source_id, None

    if persisted_source_id.startswith(LINEAGE_SOURCE_ID_PREFIX):
        encoded = persisted_source_id[len(LINEAGE_SOURCE_ID_PREFIX):]
        lineage_digest, separator, source_id = encoded.partition(':')
        if separator and normalize_yjs_lineage_digest(lineage_digest) is not None:
            if (
                not source_id
                or len(source_id.encode('utf-8')) > MAX_STATE_SOURCE_ID_BYTES
            ):
                raise ValueError('Yjs lineage 来源标识无效')
            return source_id, lineage_digest
    return persisted_source_id, None


def normalize_yjs_state_source_digests(
    values: object,
    source_ids: list[str],
) -> dict[str, str] | None:
    if not isinstance(values, dict) or set(values) != set(source_ids):
        return None
    result = {}
    for source_id in source_ids:
        digest = values.get(source_id)
        if (
            not isinstance(digest, str)
            or len(digest) != STATE_DIGEST_HEX_LENGTH
            or any(character not in '0123456789abcdef' for character in digest)
        ):
            return None
        result[source_id] = digest
    return result


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


def _unpack_yjs_state_entry(
    blob: bytes,
    offset: int,
    *,
    is_mmys3_draft: bool,
) -> tuple[str, bytes, str | None, int]:
    (key_length,) = struct.unpack_from('>H', blob, offset)
    offset += 2
    if not key_length or key_length > MAX_STATE_SOURCE_ID_BYTES:
        raise ValueError('Yjs 状态源标识无效')
    key_bytes = blob[offset:offset + key_length]
    if len(key_bytes) != key_length:
        raise ValueError('Yjs 状态源标识不完整')
    offset += key_length
    persisted_source_id = key_bytes.decode('utf-8')
    lineage_digest = None
    if is_mmys3_draft:
        # MMYS3 是本分支未发布过的短暂草案，key 仍是调用方可见的
        # source id，lineage 字段保存的是原始标识。只保留读取能力，
        # 下一次写入会自动降回滚动升级安全的 MMYS2。
        (lineage_length,) = struct.unpack_from('>H', blob, offset)
        offset += 2
        if lineage_length > MAX_LINEAGE_ID_BYTES:
            raise ValueError('Yjs lineage 标识无效')
        lineage_bytes = blob[offset:offset + lineage_length]
        if len(lineage_bytes) != lineage_length:
            raise ValueError('Yjs lineage 标识不完整')
        offset += lineage_length
        lineage_id = lineage_bytes.decode('utf-8')
        if lineage_id:
            lineage_digest = get_yjs_lineage_digest(lineage_id)
            if lineage_digest is None:
                raise ValueError('Yjs lineage 标识无效')
        source_id = persisted_source_id
    else:
        source_id, lineage_digest = _decode_opaque_source_id(persisted_source_id)

    (state_length,) = struct.unpack_from('>I', blob, offset)
    offset += 4
    if state_length > MAX_STATE_BUNDLE_BYTES:
        raise ValueError('Yjs 状态内容超过持久化上限')
    state = blob[offset:offset + state_length]
    if len(state) != state_length:
        raise ValueError('Yjs 状态内容不完整')
    return source_id, bytes(state), lineage_digest, offset + state_length


def unpack_yjs_state_bundle_with_lineages(
    blob: bytes | None,
) -> tuple[dict[str, bytes], dict[str, str]]:
    """读取多源状态及 lineage 摘要；兼容 MMYS2/MMYS3/单状态。"""
    if not blob:
        return {}, {}
    if len(blob) > MAX_STATE_BUNDLE_BYTES:
        raise ValueError('Yjs 状态包超过持久化上限')
    is_mmys2_bundle = blob.startswith(STATE_BUNDLE_MAGIC)
    is_mmys3_draft = blob.startswith(DRAFT_STATE_BUNDLE_MAGIC)
    if not is_mmys2_bundle and not is_mmys3_draft:
        return {'legacy': bytes(blob)}, {}
    magic = STATE_BUNDLE_MAGIC if is_mmys2_bundle else DRAFT_STATE_BUNDLE_MAGIC
    offset = len(magic)
    try:
        (count,) = struct.unpack_from('>H', blob, offset)
        offset += 2
        if count > MAX_STATE_SOURCE_COUNT:
            raise ValueError('Yjs 状态源数量超过限制')
        states = {}
        lineages = {}
        for _ in range(count):
            source_id, state, lineage_digest, offset = _unpack_yjs_state_entry(
                blob,
                offset,
                is_mmys3_draft=is_mmys3_draft,
            )
            if source_id in states:
                raise ValueError('Yjs 状态源标识重复')
            states[source_id] = state
            if lineage_digest is not None:
                lineages[source_id] = lineage_digest
        if offset != len(blob):
            raise ValueError('Yjs 状态包包含尾随数据')
        return states, lineages
    except (UnicodeDecodeError, struct.error) as exc:
        raise ValueError('Yjs 状态包格式损坏') from exc


def unpack_yjs_state_bundle(blob: bytes | None) -> dict[str, bytes]:
    """读取多源状态包；旧版单状态二进制自动作为 legacy 源兼容。"""
    states, _ = unpack_yjs_state_bundle_with_lineages(blob)
    return states


def pack_yjs_state_bundle(
    states: dict[str, bytes],
    source_lineages: dict[str, str] | None = None,
) -> bytes:
    """写 MMYS2 状态包；lineage 摘要编码在旧 worker 可读的 source id。"""
    if len(states) > MAX_STATE_SOURCE_COUNT:
        raise ValueError('Yjs 状态源数量超过限制')
    normalized_lineages = {}
    for source_id, lineage_digest in (source_lineages or {}).items():
        if source_id not in states:
            raise ValueError('Yjs lineage 来源不存在')
        normalized = normalize_yjs_lineage_digest(lineage_digest)
        if normalized is None:
            raise ValueError('Yjs lineage 摘要无效')
        normalized_lineages[source_id] = normalized
    chunks = [STATE_BUNDLE_MAGIC, struct.pack('>H', len(states))]
    for source_id, state in states.items():
        if not isinstance(source_id, str):
            raise ValueError('Yjs 状态源标识无效')
        opaque_source_id = source_id.strip()
        source_key = opaque_source_id.encode('utf-8')
        if not source_key or len(source_key) > MAX_STATE_SOURCE_ID_BYTES:
            raise ValueError('Yjs 状态源标识无效')
        if not isinstance(state, bytes) or not state or len(state) > MAX_STATE_BUNDLE_BYTES:
            raise ValueError('Yjs 状态内容无效或超过持久化上限')
        persisted_source_id = _encode_opaque_source_id(
            opaque_source_id,
            normalized_lineages.get(source_id),
        )
        key = persisted_source_id.encode('utf-8')
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


def _verify_yjs_state_replacement_digests(
    states: dict[str, bytes],
    replacement_ids: list[str],
    values: dict[str, str] | None,
) -> dict[str, str] | None:
    if values is None:
        return None
    normalized_digests = normalize_yjs_state_source_digests(
        values,
        replacement_ids,
    )
    if normalized_digests is None:
        raise ValueError('Yjs 状态源摘要无效')
    for replaced_source_id in replacement_ids:
        current_state = states.get(replaced_source_id)
        if (
            current_state is None
            or get_yjs_state_digest(current_state)
            != normalized_digests[replaced_source_id]
        ):
            raise ValueError('Yjs 状态源已在握手后变化')
    return normalized_digests


def merge_yjs_state_bundle(
    blob: bytes | None,
    source_id: str,
    state: bytes,
    replace_source_ids: list[str] | None = None,
    replace_source_digests: dict[str, str] | None = None,
    source_lineage_id: str | None = None,
) -> bytes:
    """保留并发来源，并用 lineage + CAS 阻止独立 Y.Doc 被误合并。"""
    source_id = str(source_id).strip()
    if not source_id or not state:
        raise ValueError('Yjs 状态来源和内容不能为空')
    normalized_replacements = normalize_yjs_state_source_ids(replace_source_ids or [])
    if normalized_replacements is None:
        raise ValueError('Yjs 已合并状态源列表无效')
    states, source_lineages = unpack_yjs_state_bundle_with_lineages(blob)
    lineage_digest = None
    if source_lineage_id is not None:
        lineage_digest = get_yjs_lineage_digest(source_lineage_id)
        if lineage_digest is None:
            raise ValueError('Yjs lineage 标识无效')

    normalized_digests = _verify_yjs_state_replacement_digests(
        states,
        normalized_replacements,
        replace_source_digests,
    )

    # 未携带 lineage 的旧 worker 状态保持可共存；只有两个已知且不同的
    # lineage 才能确定来自独立的 Y.Doc 创建历史。此时必须用同一行锁内
    # 验证过的 CAS 替换覆盖全部现存来源（包括旧 worker 写入的未知来源），
    # 才能原子切换基线；否则并发 legacy 状态可能被遗留成第二条分支。
    mismatched_source_ids = {
        existing_source_id
        for existing_source_id, existing_lineage in source_lineages.items()
        if lineage_digest is not None and existing_lineage != lineage_digest
    }
    if mismatched_source_ids and (
        normalized_digests is None
        or not set(states).issubset(normalized_replacements)
    ):
        raise ValueError('Yjs lineage 不一致，缺少完整 CAS 替换证明')

    for replaced_source_id in normalized_replacements:
        states.pop(replaced_source_id, None)
        source_lineages.pop(replaced_source_id, None)
    # 多个连接可能在合并后提交完全相同的完整状态。保留重复副本只会快速
    # 消耗来源数量和总字节上限，不提供额外恢复信息。
    for key in [key for key, value in states.items() if value == state]:
        if lineage_digest is None and key in source_lineages:
            lineage_digest = source_lineages[key]
        states.pop(key, None)
        source_lineages.pop(key, None)
    states.pop(source_id, None)
    source_lineages.pop(source_id, None)
    states[source_id] = bytes(state)
    if lineage_digest is not None:
        source_lineages[source_id] = lineage_digest
    return pack_yjs_state_bundle(states, source_lineages)


class YjsDocManager:
    """Yjs 文档的数据库持久化。"""

    @classmethod
    async def load_state_snapshot_with_lineages(
        cls,
        db: AsyncSession,
        mindmap_id: int,
        *,
        lock_for_update: bool = False,
    ) -> tuple[int | None, dict[str, bytes], dict[str, str]]:
        """原子读取主文件 revision、同 revision 状态及其 lineage。"""
        if lock_for_update:
            # 与 save/reset 保持 Mindmap -> MindmapWsState 的显式锁序。调用方
            # 可在两把锁仍持有时修复 Redis lineage fence，避免旧 DB 快照
            # 反向覆盖并发完成的新权威 seed。
            file_revision = (await db.execute(
                select(Mindmap.content_revision)
                .where(Mindmap.id == mindmap_id, Mindmap.del_flag == '0')
                .with_for_update()
            )).scalar_one_or_none()
            if file_revision is None:
                return None, {}, {}
            state_row = (await db.execute(
                select(
                    MindmapWsState.yjs_state,
                    MindmapWsState.content_revision,
                )
                .where(MindmapWsState.mindmap_id == mindmap_id)
                .with_for_update()
            )).first()
            if state_row:
                state_blob, state_revision = state_row
            else:
                state_blob, state_revision = None, None
        else:
            result = (await db.execute(
                select(
                    Mindmap.content_revision,
                    MindmapWsState.yjs_state,
                    MindmapWsState.content_revision,
                )
                .outerjoin(MindmapWsState, MindmapWsState.mindmap_id == Mindmap.id)
                .where(Mindmap.id == mindmap_id, Mindmap.del_flag == '0')
            )).first()
            if not result:
                return None, {}, {}
            file_revision, state_blob, state_revision = result
        if not state_blob:
            return file_revision, {}, {}
        if state_revision != file_revision:
            record_mindmap_event('yjs_revision_mismatch')
            return file_revision, {}, {}
        try:
            states, lineages = unpack_yjs_state_bundle_with_lineages(state_blob)
            return file_revision, states, lineages
        except ValueError:
            # 协作缓存不是主数据。即便缓存损坏，也必须把同一原子快照中
            # 读到的文件 revision 交给握手层，禁止退回旧 HTTP revision
            # 后把旧画布重新播种成当前版本。
            record_mindmap_event('yjs_state_load_failure')
            return file_revision, {}, {}

    @classmethod
    async def load_state_snapshot(
        cls,
        db: AsyncSession,
        mindmap_id: int,
    ) -> tuple[int | None, dict[str, bytes]]:
        """兼容调用方：原子读取 revision 与状态内容。"""
        revision, states, _ = await cls.load_state_snapshot_with_lineages(
            db,
            mindmap_id,
        )
        return revision, states

    @classmethod
    async def load_state_entries(cls, db: AsyncSession, mindmap_id: int) -> dict[str, bytes]:
        """加载与主文件 revision 一致的来源和状态，供安全压缩确认。"""
        _, entries = await cls.load_state_snapshot(db, mindmap_id)
        return entries

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
        replace_source_digests: dict[str, str] | None = None,
        lineage_id: str | None = None,
    ) -> bool:
        """按来源合并保存同 revision 的完整 Yjs 状态。"""
        for attempt in range(2):
            # 唯一键竞争只能在完整事务回滚后重试；两次有界重试的异常边界
            # 必须包住整次锁定/写入，拆到循环外会丢失第二次事务上下文。
            try:
                # 所有会同时触碰正文 revision 与协作检查点的事务统一遵循
                # Mindmap -> MindmapWsState 的锁序。reset、版本恢复和永久删除都
                # 先锁 Mindmap；这里若反向先锁 WsState，在高并发下会形成环路。
                current_revision = (await db.execute(
                    select(Mindmap.content_revision)
                    .where(Mindmap.id == mindmap_id, Mindmap.del_flag == '0')
                    .with_for_update()
                )).scalar_one_or_none()
                if content_revision is None or content_revision != current_revision:
                    record_mindmap_event('yjs_revision_mismatch')
                    await db.rollback()
                    return False
                existing = (await db.execute(
                    select(MindmapWsState)
                    .where(MindmapWsState.mindmap_id == mindmap_id)
                    .with_for_update()
                )).scalar_one_or_none()
                same_revision_bundle = bool(
                    existing and existing.content_revision == content_revision
                )
                previous_blob = existing.yjs_state if same_revision_bundle else None
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
                        replace_source_ids if same_revision_bundle else [],
                        replace_source_digests if same_revision_bundle else {},
                        lineage_id,
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
                await db.commit()
                return True
            except IntegrityError:  # noqa: PERF203
                await db.rollback()
                # 两个连接首次写入同一房间时，唯一键只能由一个获胜；
                # 失败方重新锁定胜者行，再把自己的状态合并进去。
                if existing or attempt:
                    record_mindmap_event('yjs_state_persist_failure')
                    return False
            except Exception:
                await db.rollback()
                record_mindmap_event('yjs_state_persist_failure')
                raise
        return False
