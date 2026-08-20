"""脑图监控响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

MindmapMetricOperation = Literal[
    'content_batch_save',
    'detail_load',
    'tag_archive',
    'tag_impact',
    'tag_replace',
]
MindmapMetricOutcome = Literal['success', 'replay', 'conflict', 'degraded', 'error']
MindmapMetricEvent = Literal[
    'broadcast_failure',
    'concurrent_merge',
    'conflict',
    'idempotent_replay',
    'integrity_fallback',
    'load_fallback',
    'migration_fallback',
    'redis_transport_degraded',
    'yjs_revision_mismatch',
    'yjs_state_load_failure',
    'yjs_state_persist_failure',
]
MindmapRedisTransportState = Literal['stopped', 'ready', 'degraded']


class MindmapDurationBucketModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    le: float = Field(ge=0, description='耗时桶上界（秒）')
    count: int = Field(ge=0, description='累计调用数')


class MindmapMetricSeriesModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    operation: MindmapMetricOperation = Field(description='固定操作类型')
    outcome: MindmapMetricOutcome = Field(description='固定结果类型')
    count: int = Field(ge=0, description='调用次数')
    duration_seconds_sum: float = Field(ge=0, description='总耗时（秒）')
    duration_buckets: list[MindmapDurationBucketModel] = Field(description='累计耗时桶')
    work_units_sum: int = Field(ge=0, description='总工作单元数')
    work_units_max: int = Field(ge=0, description='单次最大工作单元数')


class MindmapMetricEventModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    event: MindmapMetricEvent = Field(description='固定事件类型')
    count: int = Field(ge=0, description='事件次数')


class MindmapCollaborationRuntimeModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    active_rooms: int = Field(ge=0, description='当前进程活跃协作房间数')
    active_connections: int = Field(ge=0, description='当前进程活跃协作连接数')
    retiring_connections: int = Field(ge=0, description='当前进程正在安全退休的连接数')
    redis_transport_state: MindmapRedisTransportState = Field(description='Redis协作总线状态')


class MindmapMetricsSnapshotModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    scope: Literal['process'] = Field(description='指标聚合范围')
    process_id: int = Field(gt=0, description='当前进程ID')
    started_time: datetime = Field(description='进程指标开始时间')
    generated_time: datetime = Field(description='快照生成时间')
    uptime_seconds: float = Field(ge=0, description='指标运行时长（秒）')
    collaboration: MindmapCollaborationRuntimeModel = Field(description='当前进程协作运行态')
    series: list[MindmapMetricSeriesModel] = Field(description='操作指标序列')
    events: list[MindmapMetricEventModel] = Field(description='固定事件计数')
