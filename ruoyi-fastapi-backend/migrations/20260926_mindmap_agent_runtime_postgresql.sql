-- Consolidated optional Agent runtime migration (PostgreSQL).
-- Prerequisite: 20260910_mindmap_ai_agent_postgresql.sql.
-- Combines the September 25-26 additions; historical migrations are unchanged.
-- Re-running preserves existing Connector settings and user documents.
-- Platform Kimi keeps enabled=1; all device Connectors keep enabled=0.
-- Runtime environment switches and local execution consent remain required.

-- Optional companion discovery. Enable the feature only after applying this migration.
CREATE TABLE IF NOT EXISTS mindmap_ai_device (
    id VARCHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name VARCHAR(80) NOT NULL,
    status VARCHAR(16) NOT NULL,
    pairing_hash VARCHAR(64),
    pairing_expires_time TIMESTAMP NOT NULL,
    credential_hash VARCHAR(64),
    credential_expires_time TIMESTAMP NOT NULL,
    connection_id VARCHAR(36),
    scan_requested INTEGER NOT NULL DEFAULT 1,
    scan_completed INTEGER NOT NULL DEFAULT 0,
    runtimes_json TEXT,
    last_seen_time TIMESTAMP,
    last_scan_time TIMESTAMP,
    created_time TIMESTAMP NOT NULL,
    revoked_time TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mindmap_ai_device_owner ON mindmap_ai_device (user_id, created_time);

-- Optional Kimi ACP runtime. Enable only after provisioning a dedicated CLI account.
INSERT INTO mindmap_ai_connector (
    agent_key, enabled, rollout_percentage, network_policy, health_status,
    conformance_status, create_by, created_time, update_by, update_time
) VALUES ('kimi', 1, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW())
ON CONFLICT (agent_key) DO NOTHING;

-- Opt-in only: preserve all existing administrator settings.
INSERT INTO mindmap_ai_connector (
    agent_key, enabled, rollout_percentage, network_policy, health_status,
    conformance_status, create_by, created_time, update_by, update_time
) VALUES ('device_claude', 0, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW())
ON CONFLICT (agent_key) DO NOTHING;

-- Opt-in only: preserve existing settings. Estimated usage is not a hard cap.
INSERT INTO mindmap_ai_connector (
    agent_key, enabled, rollout_percentage, network_policy, health_status,
    conformance_status, create_by, created_time, update_by, update_time
) VALUES ('device_codex', 0, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW())
ON CONFLICT (agent_key) DO NOTHING;

-- Opt-in only. Preserve existing administrator settings; NO monetary cap.
INSERT INTO mindmap_ai_connector (
    agent_key, enabled, rollout_percentage, network_policy, health_status,
    conformance_status, create_by, created_time, update_by, update_time
) VALUES ('device_kimi', 0, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW())
ON CONFLICT (agent_key) DO NOTHING;
