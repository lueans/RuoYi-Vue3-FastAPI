"""脑图跨所有者复制时的标签可携带性处理。"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select

from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.entity.do.mindmap_tag_field_do import MindmapTagField, MindmapTagFieldOption

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

PRIVATE_IDENTITY_KEYS = {
    'tagId', 'id', 'uuid', 'tagKey', 'fieldId', 'optionId',
    'definitionRevision', 'status',
}


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != '' else None
    except (TypeError, ValueError):
        return None


def strip_managed_tag_identity(
    raw: dict[str, Any],
    fallback_text: str | None = None,
    fallback_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """保留可见外观和局部布局，移除不可携带的主数据身份。"""
    detached = {
        key: copy.deepcopy(value)
        for key, value in raw.items()
        if key not in PRIVATE_IDENTITY_KEYS
    }
    if not str(detached.get('text') or '').strip():
        detached['text'] = str(fallback_text or raw.get('tagKey') or '迁移待整理')[:200]
    if not isinstance(detached.get('style'), dict) and fallback_style:
        detached['style'] = copy.deepcopy(fallback_style)
    return detached


class MindmapTagPortabilityService:
    """将目标所有者不可见的标签引用转为可重新建立的私有标签。"""

    @classmethod
    async def prepare_tree_for_owner(
        cls,
        db: AsyncSession,
        root: dict[str, Any],
        target_owner_id: int,
        allow_disabled_references: bool = False,
    ) -> dict[str, Any]:
        tree = copy.deepcopy(root)
        tag_objects = cls._collect_tag_objects(tree)
        if not tag_objects:
            return tree

        option_ids = {
            value for raw in tag_objects
            if (value := _optional_int(raw.get('optionId'))) is not None
        }
        option_rows = (await db.execute(
            select(MindmapTagFieldOption, MindmapTagField)
            .join(MindmapTagField, MindmapTagField.id == MindmapTagFieldOption.field_id)
            .where(MindmapTagFieldOption.id.in_(option_ids))
        )).all() if option_ids else []
        options = {option.id: (option, field) for option, field in option_rows}

        tag_ids = {
            value for raw in tag_objects
            if (value := _optional_int(raw.get('tagId') or raw.get('id'))) is not None
        }
        tag_ids.update(option.tag_id for option, _field in option_rows if option.tag_id)
        tag_uuids = {str(raw['uuid']) for raw in tag_objects if raw.get('uuid')}
        conditions = []
        if tag_ids:
            conditions.append(MindmapTag.id.in_(tag_ids))
        if tag_uuids:
            conditions.append(MindmapTag.uuid.in_(tag_uuids))
        tag_models = list((await db.execute(
            select(MindmapTag).where(or_(*conditions))
        )).scalars()) if conditions else []
        tags_by_id = {tag.id: tag for tag in tag_models}
        tags_by_uuid = {tag.uuid: tag for tag in tag_models if tag.uuid}

        for raw in tag_objects:
            tag_id = _optional_int(raw.get('tagId') or raw.get('id'))
            tag = tags_by_id.get(tag_id) if tag_id is not None else None
            if not tag and raw.get('uuid'):
                tag = tags_by_uuid.get(str(raw['uuid']))
            option_id = _optional_int(raw.get('optionId'))
            option_row = options.get(option_id) if option_id is not None else None
            if not tag and option_row and option_row[0].tag_id:
                tag = tags_by_id.get(option_row[0].tag_id)

            if cls._is_reference_portable(
                raw,
                tag,
                option_row,
                target_owner_id,
                allow_disabled_references,
            ):
                continue
            fallback_text, fallback_style = cls._fallback_definition(tag, option_row)
            original = copy.deepcopy(raw)
            raw.clear()
            raw.update(strip_managed_tag_identity(
                original,
                fallback_text=fallback_text,
                fallback_style=fallback_style,
            ))
        return tree

    @staticmethod
    def _collect_tag_objects(root: dict[str, Any]) -> list[dict[str, Any]]:
        result = []
        pending = [root]
        while pending:
            node = pending.pop()
            data = node.get('data') if isinstance(node, dict) else None
            tags = data.get('tag') if isinstance(data, dict) else None
            if isinstance(tags, list):
                result.extend(tag for tag in tags if isinstance(tag, dict))
            pending.extend(child for child in node.get('children') or [] if isinstance(child, dict))
        return result

    @staticmethod
    def _is_reference_portable(
        raw: dict[str, Any],
        tag: MindmapTag | None,
        option_row: tuple[MindmapTagFieldOption, MindmapTagField] | None,
        target_owner_id: int,
        allow_disabled_references: bool = False,
    ) -> bool:
        allowed_statuses = {0, 1} if allow_disabled_references else {0}
        has_tag_identity = bool(raw.get('tagId') or raw.get('id') or raw.get('uuid'))
        if has_tag_identity and (
            not tag or tag.owner_id not in (0, target_owner_id) or tag.status not in allowed_statuses
        ):
            return False
        if raw.get('optionId'):
            if not option_row or option_row[1].owner_id not in (0, target_owner_id):
                return False
            if option_row[0].tag_id and (
                not tag
                or tag.owner_id not in (0, target_owner_id)
                or tag.status not in allowed_statuses
            ):
                return False
        return True

    @staticmethod
    def _fallback_definition(
        tag: MindmapTag | None,
        option_row: tuple[MindmapTagFieldOption, MindmapTagField] | None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        if tag:
            style = dict(option_row[1].style or {}) if option_row else {}
            style.update(tag.style or {})
            return tag.name, style or None
        if not option_row:
            return None, None
        option, field = option_row
        style = dict(field.style or {})
        if option.fill is not None:
            style['fill'] = option.fill
        if option.color is not None:
            style['color'] = option.color
        return option.name, style or None
