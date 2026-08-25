"""把 simple-mind-map 历史节点标记收敛为统一标签绑定。"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.service.simple_mind_document_codec import EncodedDocument

MINDMAP_MARKER_GROUP_COUNTS = {
    'priority': 10,
    'progress': 8,
    'expression': 20,
    'sign': 23,
}
MINDMAP_MARKER_ICON_KEYS = frozenset(
    f'{group}_{index}'
    for group, count in MINDMAP_MARKER_GROUP_COUNTS.items()
    for index in range(1, count + 1)
)
MINDMAP_MARKER_TAG_KEY_PREFIX = 'builtin_marker_'


def marker_tag_key(icon_key: Any) -> str | None:
    """返回内置标记对应的保留标签 Key，未知图标保持兼容而不迁移。"""
    normalized = str(icon_key).strip() if isinstance(icon_key, str) else ''
    if normalized not in MINDMAP_MARKER_ICON_KEYS:
        return None
    return f'{MINDMAP_MARKER_TAG_KEY_PREFIX}{normalized}'


def marker_icon_key_from_tag_key(tag_key: Any) -> str | None:
    """从受控的内置标记标签 Key 反解图标 Key。"""
    normalized = str(tag_key).strip() if isinstance(tag_key, str) else ''
    if not normalized.startswith(MINDMAP_MARKER_TAG_KEY_PREFIX):
        return None
    icon_key = normalized[len(MINDMAP_MARKER_TAG_KEY_PREFIX):]
    return icon_key if marker_tag_key(icon_key) == normalized else None


def collect_legacy_marker_tag_keys(document: EncodedDocument) -> set[str]:
    keys: set[str] = set()
    for node in document.nodes:
        content_data = node.get('content_data')
        icons = content_data.get('icon') if isinstance(content_data, dict) else None
        if not isinstance(icons, list):
            continue
        keys.update(key for icon in icons if (key := marker_tag_key(icon)))
    return keys


def _tag_snapshot(tag: MindmapTag) -> dict[str, Any]:
    return {
        'tagId': tag.id,
        'uuid': tag.uuid,
        'tagKey': tag.tag_key,
        'text': tag.name,
        'style': dict(tag.style or {}),
        'status': tag.status,
        'definitionRevision': tag.definition_revision,
    }


def apply_legacy_marker_tags(
    document: EncodedDocument,
    tags: Iterable[MindmapTag],
) -> int:
    """原地把可解析的 ``content_data.icon`` 改为 ``node_tags``。"""
    tags_by_key = {
        tag.tag_key: tag
        for tag in tags
        if tag.id and tag.status == 0 and tag.owner_id == 0
    }
    bindings_by_node: dict[str, list[dict[str, Any]]] = {}
    for binding in document.node_tags:
        bindings_by_node.setdefault(str(binding.get('node_uid')), []).append(binding)

    migrated_count = 0
    for node in document.nodes:
        content_data = node.get('content_data')
        icons = content_data.get('icon') if isinstance(content_data, dict) else None
        if not isinstance(icons, list):
            continue

        node_uid = str(node.get('node_uid'))
        node_bindings = bindings_by_node.setdefault(node_uid, [])
        existing_tag_ids = {
            (binding.get('raw') or {}).get('tagId')
            for binding in node_bindings
            if isinstance(binding.get('raw'), dict)
        }
        next_order = max(
            (int(binding.get('sort_order') or 0) for binding in node_bindings),
            default=-1,
        ) + 1
        remaining_icons: list[Any] = []

        for icon_key in icons:
            tag_key = marker_tag_key(icon_key)
            tag = tags_by_key.get(tag_key) if tag_key else None
            if tag is None:
                remaining_icons.append(icon_key)
                continue
            if tag.id not in existing_tag_ids:
                style = dict(tag.style or {})
                binding = {
                    'node_uid': node_uid,
                    'sort_order': next_order,
                    'placement': style.get('placement'),
                    'align': style.get('align'),
                    'raw': _tag_snapshot(tag),
                }
                document.node_tags.append(binding)
                node_bindings.append(binding)
                existing_tag_ids.add(tag.id)
                next_order += 1
            migrated_count += 1

        if remaining_icons:
            content_data['icon'] = remaining_icons
        else:
            content_data.pop('icon', None)
        if not content_data:
            node['content_data'] = None

    return migrated_count


async def promote_legacy_marker_tags(
    db: AsyncSession,
    document: EncodedDocument,
) -> int:
    """读取系统标记标签，并转换本次保存中的历史节点图标。"""
    tag_keys = collect_legacy_marker_tag_keys(document)
    if not tag_keys:
        return 0
    tags = list((await db.execute(
        select(MindmapTag).where(
            MindmapTag.owner_id == 0,
            MindmapTag.status == 0,
            MindmapTag.tag_key.in_(tag_keys),
        )
    )).scalars())
    return apply_legacy_marker_tags(document, tags)
