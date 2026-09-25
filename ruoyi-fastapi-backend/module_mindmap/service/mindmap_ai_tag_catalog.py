"""Read-only, actor-visible tag choices that can be bound to the target map."""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.service.mindmap_service import MindmapService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

TAG_CATALOG_PAGE_SIZE = 500


async def load_ai_tag_catalog(
    db: AsyncSession, user_id: int, *, mindmap_id: int | None = None,
) -> list[dict[str, Any]]:
    """Intersect library visibility and binding ownership, with no silent cap.

    Shared-map editors can see their own private library but cannot bind those
    tags to someone else's file. Conversely, edit permission does not expose
    the owner's private library. Only global tags satisfy both rules there.
    Keyset pages bound each query; every matching page is loaded so a tool's
    negative search result never means merely "outside the first page".
    """
    owner_id = user_id
    if mindmap_id is not None:
        mindmap, _permission, _is_owner = await MindmapService.resolve_mindmap_access(
            db, mindmap_id, user_id, require_edit=False,
        )
        owner_id = int(mindmap.owner_id)
    allowed_owners = {0, int(user_id)} & {0, owner_id}
    catalog: list[dict[str, Any]] = []
    cursor = 0
    while True:
        rows = list((await db.execute(
            select(MindmapTag)
            .where(
                MindmapTag.owner_id.in_(sorted(allowed_owners)),
                MindmapTag.status == 0,
                MindmapTag.id > cursor,
            )
            .order_by(MindmapTag.id.asc())
            .limit(TAG_CATALOG_PAGE_SIZE)
        )).scalars().all())
        catalog.extend(
            {
                'tagId': int(tag.id),
                'categoryId': tag.category_id,
                'uuid': tag.uuid,
                'tagKey': tag.tag_key,
                'text': tag.name,
                'name': tag.name,
                'description': tag.description or '',
                'style': deepcopy(tag.style or {}),
                'status': int(tag.status),
                'definitionRevision': int(tag.definition_revision or 1),
            }
            for tag in rows
        )
        if len(rows) < TAG_CATALOG_PAGE_SIZE:
            return catalog
        cursor = int(rows[-1].id)
