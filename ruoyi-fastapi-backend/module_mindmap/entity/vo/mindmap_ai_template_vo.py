"""Cloud mindmaps available as AI output templates."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class MindmapAiTemplateSummaryModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: int
    name: str
    description: str | None = None
    folder_id: int
    folder_name: str
    folder_path: str
    owner_name: str | None = None
    node_count: int = 0
    status: int = 0
    content_revision: int = 1
    update_time: datetime | None = None


class MindmapAiTemplateDetailModel(MindmapAiTemplateSummaryModel):
    node_tree: dict[str, Any]
    layout: str
    theme: dict[str, Any] | None = None
