-- AI 脑图 Agent 需求合并迁移（PostgreSQL 14+）
-- 按开发顺序拼接：基础表与菜单 -> Connector 治理策略 -> 到期索引补齐
--   -> 讨论模式文字结果 -> 实时草稿加密检查点。各段保留幂等守卫，可安全重复执行。
-- AI 脑图任务、Artifact、Proposal 与事件

BEGIN;

CREATE TABLE IF NOT EXISTS mindmap_ai_session (
    id VARCHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    current_agent_key VARCHAR(64) NOT NULL,
    title VARCHAR(200),
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    latest_artifact_id VARCHAR(36),
    created_time TIMESTAMP NOT NULL,
    update_time TIMESTAMP NOT NULL,
    expires_time TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_session_user_updated
    ON mindmap_ai_session (user_id, update_time);

CREATE TABLE IF NOT EXISTS mindmap_ai_connector (
    agent_key VARCHAR(64) PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    rollout_percentage INTEGER NOT NULL DEFAULT 100 CHECK (rollout_percentage BETWEEN 0 AND 100),
    credential_ref VARCHAR(255),
    data_region VARCHAR(64),
    retention_policy VARCHAR(100),
    network_policy VARCHAR(24) NOT NULL DEFAULT 'adapter_default',
    health_status VARCHAR(24) NOT NULL DEFAULT 'unknown',
    health_reason VARCHAR(500),
    conformance_status VARCHAR(24) NOT NULL DEFAULT 'unknown',
    conformance_report_json TEXT,
    last_health_time TIMESTAMP,
    last_conformance_time TIMESTAMP,
    create_by VARCHAR(64) NOT NULL,
    created_time TIMESTAMP NOT NULL,
    update_by VARCHAR(64) NOT NULL,
    update_time TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS mindmap_ai_job (
    id VARCHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    session_id VARCHAR(36) NOT NULL,
    parent_job_id VARCHAR(36),
    retry_of_job_id VARCHAR(36),
    turn_index INTEGER NOT NULL DEFAULT 1,
    agent_key VARCHAR(64) NOT NULL,
    adapter_version VARCHAR(32) NOT NULL,
    sdk_version VARCHAR(32),
    runtime_version VARCHAR(32),
    model_ref VARCHAR(128),
    intent VARCHAR(32) NOT NULL,
    target VARCHAR(16) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_mindmap_id BIGINT,
    base_revision BIGINT,
    base_hash VARCHAR(80),
    base_room_epoch VARCHAR(64),
    request_json TEXT NOT NULL,
    request_fingerprint CHAR(64) NOT NULL,
    idempotency_key VARCHAR(100) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    title VARCHAR(200),
    artifact_id VARCHAR(36),
    proposal_id VARCHAR(36),
    external_session_ref TEXT,
    usage_json TEXT,
    error_code VARCHAR(64),
    error_message VARCHAR(500),
    cancel_requested_time TIMESTAMP,
    completed_time TIMESTAMP,
    expires_time TIMESTAMP NOT NULL,
    created_time TIMESTAMP NOT NULL,
    update_time TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_ai_job_user_idempotency
    ON mindmap_ai_job (user_id, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_job_user_created
    ON mindmap_ai_job (user_id, created_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_job_session_turn
    ON mindmap_ai_job (session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_job_status_updated
    ON mindmap_ai_job (status, update_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_job_status_expires
    ON mindmap_ai_job (status, expires_time, id);

CREATE TABLE IF NOT EXISTS mindmap_ai_artifact (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    user_id BIGINT NOT NULL,
    title VARCHAR(200) NOT NULL,
    content_json TEXT NOT NULL,
    document_hash VARCHAR(80) NOT NULL,
    validation_status VARCHAR(16) NOT NULL,
    validator_version VARCHAR(64) NOT NULL,
    node_count INTEGER NOT NULL,
    tree_depth INTEGER NOT NULL,
    byte_size INTEGER NOT NULL,
    created_time TIMESTAMP NOT NULL,
    expires_time TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_ai_artifact_job ON mindmap_ai_artifact (job_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_artifact_user_created
    ON mindmap_ai_artifact (user_id, created_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_artifact_expires ON mindmap_ai_artifact (expires_time);

CREATE TABLE IF NOT EXISTS mindmap_ai_proposal (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    user_id BIGINT NOT NULL,
    proposal_type VARCHAR(24) NOT NULL,
    base_document_id VARCHAR(64),
    target_mindmap_id BIGINT,
    base_revision BIGINT,
    base_hash VARCHAR(80),
    base_room_epoch VARCHAR(64),
    scope_json TEXT,
    operations_json TEXT NOT NULL,
    result_artifact_id VARCHAR(36) NOT NULL,
    result_hash VARCHAR(80) NOT NULL,
    impact_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'ready',
    applied_revision BIGINT,
    applied_time TIMESTAMP,
    created_time TIMESTAMP NOT NULL,
    expires_time TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_ai_proposal_job ON mindmap_ai_proposal (job_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_proposal_user_status
    ON mindmap_ai_proposal (user_id, status);

CREATE TABLE IF NOT EXISTS mindmap_ai_job_event (
    id BIGSERIAL PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    sequence INTEGER NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    payload_json TEXT NOT NULL,
    created_time TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_ai_event_job_sequence
    ON mindmap_ai_job_event (job_id, sequence);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_event_job_id ON mindmap_ai_job_event (job_id, id);

CREATE TABLE IF NOT EXISTS mindmap_ai_undo (
    proposal_id VARCHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    mindmap_id BIGINT NOT NULL,
    before_document_json TEXT NOT NULL,
    before_hash VARCHAR(80) NOT NULL,
    applied_hash VARCHAR(80) NOT NULL,
    applied_revision BIGINT NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'available',
    undone_revision BIGINT,
    created_time TIMESTAMP NOT NULL,
    expires_time TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_undo_user_created
    ON mindmap_ai_undo (user_id, created_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_undo_expires
    ON mindmap_ai_undo (expires_time, proposal_id);

COMMENT ON TABLE mindmap_ai_job IS 'AI 脑图任务';
COMMENT ON TABLE mindmap_ai_session IS 'AI 脑图多轮会话';
COMMENT ON TABLE mindmap_ai_connector IS 'AI 脑图 Agent 运营配置';
COMMENT ON TABLE mindmap_ai_artifact IS 'AI 脑图不可变文件结果';
COMMENT ON TABLE mindmap_ai_proposal IS 'AI 脑图候选变更';
COMMENT ON TABLE mindmap_ai_job_event IS 'AI 脑图任务事件';
COMMENT ON TABLE mindmap_ai_undo IS 'AI 云端应用条件撤销快照';

INSERT INTO sys_menu (
    menu_id, menu_name, parent_id, order_num, path, component,
    query_param, route_name, is_frame, is_cache, menu_type, visible,
    status, perms, icon, create_by, create_time, update_by, update_time, remark
)
SELECT GREATEST(
    COALESCE((SELECT MAX(menu_id) FROM sys_menu), 9019) + 1,
    9020
), 'AI 脑图使用', COALESCE(
    (SELECT menu_id FROM sys_menu WHERE perms = 'mindmap:list' LIMIT 1),
    121
), 90, '', '', '', '', 1, 0, 'F', '0', '0', 'mindmap:ai:use', '#',
    'migration', CURRENT_TIMESTAMP, '', NULL, '独立控制 AI 脑图 Agent 使用权限'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'mindmap:ai:use');

INSERT INTO sys_role_menu (role_id, menu_id)
SELECT DISTINCT role_menu.role_id, ai_menu.menu_id
FROM sys_role_menu role_menu
JOIN sys_menu source_menu ON source_menu.menu_id = role_menu.menu_id
JOIN sys_menu ai_menu ON ai_menu.perms = 'mindmap:ai:use'
WHERE source_menu.perms IN (
    'mindmap:list', 'mindmap:query',
    'mindmap:mindmap:list', 'mindmap:mindmap:query'
)
ON CONFLICT DO NOTHING;

INSERT INTO sys_role_menu (role_id, menu_id)
SELECT 1, ai_menu.menu_id
FROM sys_menu ai_menu
WHERE ai_menu.perms = 'mindmap:ai:use'
ON CONFLICT DO NOTHING;

INSERT INTO sys_menu (
    menu_id, menu_name, parent_id, order_num, path, component,
    query_param, route_name, is_frame, is_cache, menu_type, visible,
    status, perms, icon, create_by, create_time, update_by, update_time, remark
)
SELECT GREATEST(
    COALESCE((SELECT MAX(menu_id) FROM sys_menu), 9020) + 1,
    9021
), 'AI Agent 管理', COALESCE(
    (SELECT menu_id FROM sys_menu WHERE perms = 'mindmap:list' LIMIT 1),
    121
), 91, 'ai-agents', 'mindmap/ai-agents', '', 'MindmapAiAgents', 1, 0, 'C', '0', '0', 'mindmap:ai:admin', 'monitor',
    'migration', CURRENT_TIMESTAMP, '', NULL, '管理 Agent Connector、健康状态和一致性检查'
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE perms = 'mindmap:ai:admin');

UPDATE sys_menu
SET menu_name = 'AI Agent 管理', path = 'ai-agents',
    component = 'mindmap/ai-agents', route_name = 'MindmapAiAgents',
    menu_type = 'C', icon = 'monitor', update_by = 'migration',
    update_time = CURRENT_TIMESTAMP
WHERE perms = 'mindmap:ai:admin';

INSERT INTO sys_role_menu (role_id, menu_id)
SELECT role.role_id, menu.menu_id
FROM sys_role role
JOIN sys_menu menu ON menu.perms = 'mindmap:ai:admin'
WHERE role.role_id = 1
ON CONFLICT DO NOTHING;

COMMIT;


-- ===================================================================
-- AI 脑图 Connector 运行治理与任务策略快照（PostgreSQL 14+）

BEGIN;

ALTER TABLE mindmap_ai_connector
    ADD COLUMN IF NOT EXISTS model_allowlist_json TEXT,
    ADD COLUMN IF NOT EXISTS max_budget_usd NUMERIC(10,4) NOT NULL DEFAULT 5.0000,
    ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 900,
    ADD COLUMN IF NOT EXISTS max_nodes INTEGER NOT NULL DEFAULT 2000,
    ADD COLUMN IF NOT EXISTS max_depth INTEGER NOT NULL DEFAULT 32,
    ADD COLUMN IF NOT EXISTS max_concurrent_jobs INTEGER NOT NULL DEFAULT 4;

ALTER TABLE mindmap_ai_job
    ADD COLUMN IF NOT EXISTS max_budget_usd NUMERIC(10,4) NOT NULL DEFAULT 5.0000,
    ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 900,
    ADD COLUMN IF NOT EXISTS max_nodes INTEGER NOT NULL DEFAULT 2000,
    ADD COLUMN IF NOT EXISTS max_depth INTEGER NOT NULL DEFAULT 32,
    ADD COLUMN IF NOT EXISTS retention_days INTEGER NOT NULL DEFAULT 30;

INSERT INTO mindmap_ai_connector (
    agent_key, enabled, rollout_percentage, network_policy,
    health_status, conformance_status, create_by, created_time,
    update_by, update_time
) VALUES
    ('native_mindmap', 1, 100, 'adapter_default', 'unknown', 'unknown', 'migration', CURRENT_TIMESTAMP, 'migration', CURRENT_TIMESTAMP),
    ('codex', 1, 100, 'adapter_default', 'unknown', 'unknown', 'migration', CURRENT_TIMESTAMP, 'migration', CURRENT_TIMESTAMP),
    ('claude', 1, 100, 'adapter_default', 'unknown', 'unknown', 'migration', CURRENT_TIMESTAMP, 'migration', CURRENT_TIMESTAMP)
ON CONFLICT (agent_key) DO NOTHING;

COMMIT;


-- ===================================================================
-- AI 脑图安全热修：补齐到期扫描索引，并给既有脑图角色新增 AI 使用权限。
-- 仅执行幂等的 CREATE INDEX / INSERT，不删除或改写既有业务数据。

BEGIN;

CREATE INDEX IF NOT EXISTS idx_mindmap_ai_job_status_expires
    ON mindmap_ai_job (status, expires_time, id);

CREATE INDEX IF NOT EXISTS idx_mindmap_ai_undo_expires
    ON mindmap_ai_undo (expires_time, proposal_id);

INSERT INTO sys_role_menu (role_id, menu_id)
SELECT DISTINCT source_role_menu.role_id, ai_menu.menu_id
FROM sys_role_menu source_role_menu
JOIN sys_menu source_menu ON source_menu.menu_id = source_role_menu.menu_id
JOIN sys_menu ai_menu ON ai_menu.perms = 'mindmap:ai:use'
WHERE source_menu.perms IN (
    'mindmap:list', 'mindmap:query',
    'mindmap:mindmap:list', 'mindmap:mindmap:query'
)
ON CONFLICT DO NOTHING;

INSERT INTO sys_role_menu (role_id, menu_id)
SELECT 1, ai_menu.menu_id
FROM sys_menu ai_menu
WHERE ai_menu.perms = 'mindmap:ai:use'
ON CONFLICT DO NOTHING;

COMMIT;


-- ===================================================================
-- AI 脑图零工具讨论模式与独立文字结果（PostgreSQL 14+）

BEGIN;

ALTER TABLE mindmap_ai_job
    ADD COLUMN IF NOT EXISTS response_id VARCHAR(36);

CREATE TABLE IF NOT EXISTS mindmap_ai_response (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    user_id BIGINT NOT NULL,
    content_type VARCHAR(32) NOT NULL DEFAULT 'text/plain',
    content_text TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    byte_size INTEGER NOT NULL,
    created_time TIMESTAMP NOT NULL,
    expires_time TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_ai_response_job
    ON mindmap_ai_response (job_id);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_response_user_created
    ON mindmap_ai_response (user_id, created_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_response_expires
    ON mindmap_ai_response (expires_time, id);

COMMENT ON TABLE mindmap_ai_response IS 'AI 脑图讨论模式文字答复';

COMMIT;


-- ===================================================================
-- AI 脑图实时草稿持久检查点（PostgreSQL 14+）
-- 正文、增量与初始帧均以应用层 Fernet 密文保存；事件表只保留元数据。

BEGIN;

ALTER TABLE mindmap_ai_job
    ADD COLUMN IF NOT EXISTS execution_epoch INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS mindmap_ai_draft_checkpoint (
    job_id VARCHAR(36) PRIMARY KEY,
    preview_version INTEGER NOT NULL,
    preview_epoch INTEGER NOT NULL,
    document_ciphertext TEXT NOT NULL,
    operations_ciphertext TEXT NOT NULL,
    initial_state_ciphertext TEXT NULL,
    document_hash VARCHAR(80) NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    expires_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mindmap_ai_draft_checkpoint_expires
    ON mindmap_ai_draft_checkpoint (expires_time, job_id);

COMMENT ON TABLE mindmap_ai_draft_checkpoint IS 'AI 脑图实时草稿加密检查点';

COMMIT;
