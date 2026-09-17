"""AI 脑图任务、Artifact、Proposal 与事件表。"""
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects import mysql

from config.database import Base
from config.env import DataBaseConfig

LONG_TEXT = mysql.LONGTEXT if DataBaseConfig.db_type == 'mysql' else Text
MINDMAP_AI_EVENT_SEQUENCE_MAX = (1 << 31) - 1


class MindmapAiSession(Base):
    __tablename__ = 'mindmap_ai_session'
    __table_args__ = (
        Index('idx_mindmap_ai_session_user_updated', 'user_id', 'update_time'),
        {'comment': 'AI 脑图多轮会话'},
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    current_agent_key = Column(String(64), nullable=False)
    title = Column(String(200), nullable=True)
    status = Column(String(24), nullable=False, server_default='active')
    latest_artifact_id = Column(String(36), nullable=True)
    created_time = Column(DateTime, nullable=False, default=datetime.now)
    update_time = Column(DateTime, nullable=False, default=datetime.now)
    expires_time = Column(DateTime, nullable=False)


class MindmapAiConnector(Base):
    __tablename__ = 'mindmap_ai_connector'
    __table_args__ = ({'comment': 'AI 脑图 Agent 运营配置'},)

    agent_key = Column(String(64), primary_key=True)
    enabled = Column(Integer, nullable=False, server_default='1')
    rollout_percentage = Column(Integer, nullable=False, server_default='100')
    credential_ref = Column(String(255), nullable=True)
    data_region = Column(String(64), nullable=True)
    retention_policy = Column(String(100), nullable=True)
    network_policy = Column(String(24), nullable=False, server_default='adapter_default')
    model_allowlist_json = Column(Text, nullable=True)
    max_budget_usd = Column(Numeric(10, 4), nullable=False, server_default='5.0000')
    timeout_seconds = Column(Integer, nullable=False, server_default='900')
    max_nodes = Column(Integer, nullable=False, server_default='2000')
    max_depth = Column(Integer, nullable=False, server_default='32')
    max_concurrent_jobs = Column(Integer, nullable=False, server_default='4')
    health_status = Column(String(24), nullable=False, server_default='unknown')
    health_reason = Column(String(500), nullable=True)
    conformance_status = Column(String(24), nullable=False, server_default='unknown')
    conformance_report_json = Column(Text, nullable=True)
    last_health_time = Column(DateTime, nullable=True)
    last_conformance_time = Column(DateTime, nullable=True)
    create_by = Column(String(64), nullable=False)
    created_time = Column(DateTime, nullable=False, default=datetime.now)
    update_by = Column(String(64), nullable=False)
    update_time = Column(DateTime, nullable=False, default=datetime.now)


class MindmapAiJob(Base):
    __tablename__ = 'mindmap_ai_job'
    __table_args__ = (
        Index('uk_mindmap_ai_job_user_idempotency', 'user_id', 'idempotency_key', unique=True),
        Index('idx_mindmap_ai_job_user_created', 'user_id', 'created_time'),
        Index('idx_mindmap_ai_job_session_turn', 'session_id', 'turn_index'),
        Index('idx_mindmap_ai_job_status_updated', 'status', 'update_time'),
        Index('idx_mindmap_ai_job_status_expires', 'status', 'expires_time', 'id'),
        {'comment': 'AI 脑图任务'},
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    session_id = Column(String(36), nullable=False)
    parent_job_id = Column(String(36), nullable=True)
    retry_of_job_id = Column(String(36), nullable=True)
    turn_index = Column(Integer, nullable=False, server_default='1')
    execution_epoch = Column(Integer, nullable=False, server_default='0')
    agent_key = Column(String(64), nullable=False)
    adapter_version = Column(String(32), nullable=False)
    sdk_version = Column(String(32), nullable=True)
    runtime_version = Column(String(32), nullable=True)
    model_ref = Column(String(128), nullable=True)
    max_budget_usd = Column(Numeric(10, 4), nullable=False, server_default='5.0000')
    timeout_seconds = Column(Integer, nullable=False, server_default='900')
    max_nodes = Column(Integer, nullable=False, server_default='2000')
    max_depth = Column(Integer, nullable=False, server_default='32')
    retention_days = Column(Integer, nullable=False, server_default='30')
    intent = Column(String(32), nullable=False)
    target = Column(String(16), nullable=False)
    source_type = Column(String(32), nullable=False)
    source_mindmap_id = Column(BigInteger, nullable=True)
    base_revision = Column(BigInteger, nullable=True)
    base_hash = Column(String(80), nullable=True)
    base_room_epoch = Column(String(64), nullable=True)
    request_json = Column(LONG_TEXT, nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    status = Column(String(32), nullable=False, server_default='queued')
    progress = Column(Integer, nullable=False, server_default='0')
    title = Column(String(200), nullable=True)
    artifact_id = Column(String(36), nullable=True)
    proposal_id = Column(String(36), nullable=True)
    response_id = Column(String(36), nullable=True)
    external_session_ref = Column(Text, nullable=True)
    usage_json = Column(Text, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(String(500), nullable=True)
    cancel_requested_time = Column(DateTime, nullable=True)
    completed_time = Column(DateTime, nullable=True)
    expires_time = Column(DateTime, nullable=False)
    created_time = Column(DateTime, nullable=False, default=datetime.now)
    update_time = Column(DateTime, nullable=False, default=datetime.now)


class MindmapAiResponse(Base):
    __tablename__ = 'mindmap_ai_response'
    __table_args__ = (
        Index('uk_mindmap_ai_response_job', 'job_id', unique=True),
        Index('idx_mindmap_ai_response_user_created', 'user_id', 'created_time'),
        Index('idx_mindmap_ai_response_expires', 'expires_time', 'id'),
        {'comment': 'AI 脑图讨论模式文字答复'},
    )

    id = Column(String(36), primary_key=True)
    job_id = Column(String(36), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    content_type = Column(String(32), nullable=False, server_default='text/plain')
    content_text = Column(LONG_TEXT, nullable=False)
    content_hash = Column(String(64), nullable=False)
    byte_size = Column(Integer, nullable=False)
    created_time = Column(DateTime, nullable=False, default=datetime.now)
    expires_time = Column(DateTime, nullable=False)


class MindmapAiArtifact(Base):
    __tablename__ = 'mindmap_ai_artifact'
    __table_args__ = (
        Index('uk_mindmap_ai_artifact_job', 'job_id', unique=True),
        Index('idx_mindmap_ai_artifact_user_created', 'user_id', 'created_time'),
        Index('idx_mindmap_ai_artifact_expires', 'expires_time'),
        {'comment': 'AI 脑图不可变文件结果'},
    )

    id = Column(String(36), primary_key=True)
    job_id = Column(String(36), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    title = Column(String(200), nullable=False)
    content_json = Column(LONG_TEXT, nullable=False)
    document_hash = Column(String(80), nullable=False)
    validation_status = Column(String(16), nullable=False)
    validator_version = Column(String(64), nullable=False)
    node_count = Column(Integer, nullable=False)
    tree_depth = Column(Integer, nullable=False)
    byte_size = Column(Integer, nullable=False)
    created_time = Column(DateTime, nullable=False, default=datetime.now)
    expires_time = Column(DateTime, nullable=False)


class MindmapAiProposal(Base):
    __tablename__ = 'mindmap_ai_proposal'
    __table_args__ = (
        Index('uk_mindmap_ai_proposal_job', 'job_id', unique=True),
        Index('idx_mindmap_ai_proposal_user_status', 'user_id', 'status'),
        {'comment': 'AI 脑图候选变更'},
    )

    id = Column(String(36), primary_key=True)
    job_id = Column(String(36), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    proposal_type = Column(String(24), nullable=False)
    base_document_id = Column(String(64), nullable=True)
    target_mindmap_id = Column(BigInteger, nullable=True)
    base_revision = Column(BigInteger, nullable=True)
    base_hash = Column(String(80), nullable=True)
    base_room_epoch = Column(String(64), nullable=True)
    scope_json = Column(Text, nullable=True)
    operations_json = Column(LONG_TEXT, nullable=False)
    result_artifact_id = Column(String(36), nullable=False)
    result_hash = Column(String(80), nullable=False)
    impact_json = Column(Text, nullable=False)
    warnings_json = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, server_default='ready')
    applied_revision = Column(BigInteger, nullable=True)
    applied_time = Column(DateTime, nullable=True)
    created_time = Column(DateTime, nullable=False, default=datetime.now)
    expires_time = Column(DateTime, nullable=False)


class MindmapAiJobEvent(Base):
    __tablename__ = 'mindmap_ai_job_event'
    __table_args__ = (
        Index('uk_mindmap_ai_event_job_sequence', 'job_id', 'sequence', unique=True),
        Index('idx_mindmap_ai_event_job_id', 'job_id', 'id'),
        {'comment': 'AI 脑图任务可重放事件'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(String(36), nullable=False)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=False)
    created_time = Column(DateTime, nullable=False, default=datetime.now)


class MindmapAiDraftCheckpoint(Base):
    """Durable, encrypted latest draft frame for one AI job.

    The plaintext draft is deliberately kept out of the replayable event table.
    A job row owns at most one checkpoint; short-lived historical frames remain
    a Redis-only concern.
    """

    __tablename__ = 'mindmap_ai_draft_checkpoint'
    __table_args__ = (
        Index('idx_mindmap_ai_draft_checkpoint_expires', 'expires_time', 'job_id'),
        {'comment': 'AI 脑图实时草稿加密检查点'},
    )

    job_id = Column(String(36), primary_key=True)
    preview_version = Column(Integer, nullable=False)
    preview_epoch = Column(Integer, nullable=False)
    document_ciphertext = Column(LONG_TEXT, nullable=False)
    operations_ciphertext = Column(LONG_TEXT, nullable=False)
    initial_state_ciphertext = Column(LONG_TEXT, nullable=True)
    document_hash = Column(String(80), nullable=False)
    summary_json = Column(Text, nullable=False)
    expires_time = Column(DateTime, nullable=False)
    created_time = Column(DateTime, nullable=False, default=datetime.now)
    update_time = Column(DateTime, nullable=False, default=datetime.now)


class MindmapAiUndo(Base):
    __tablename__ = 'mindmap_ai_undo'
    __table_args__ = (
        Index('idx_mindmap_ai_undo_user_created', 'user_id', 'created_time'),
        Index('idx_mindmap_ai_undo_expires', 'expires_time', 'proposal_id'),
        {'comment': 'AI 云端应用条件撤销快照'},
    )

    proposal_id = Column(String(36), primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    mindmap_id = Column(BigInteger, nullable=False)
    before_document_json = Column(LONG_TEXT, nullable=False)
    before_hash = Column(String(80), nullable=False)
    applied_hash = Column(String(80), nullable=False)
    applied_revision = Column(BigInteger, nullable=False)
    status = Column(String(24), nullable=False, server_default='available')
    undone_revision = Column(BigInteger, nullable=True)
    created_time = Column(DateTime, nullable=False, default=datetime.now)
    expires_time = Column(DateTime, nullable=False)
