-- Consolidated optional Agent runtime migration (MySQL).
-- Prerequisite: 20260910_mindmap_ai_agent.sql.
-- Combines the September 25-26 additions; historical migrations are unchanged.
-- Re-running preserves existing Connector settings and user documents.
-- Platform Kimi keeps enabled=1; all device Connectors keep enabled=0.
-- Runtime environment switches and local execution consent remain required.

-- Optional companion discovery. Does not enable execution or migrate any user document.
CREATE TABLE IF NOT EXISTS mindmap_ai_device (
    id VARCHAR(36) PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name VARCHAR(80) NOT NULL,
    status VARCHAR(16) NOT NULL,
    pairing_hash VARCHAR(64) NULL,
    pairing_expires_time DATETIME NOT NULL,
    credential_hash VARCHAR(64) NULL,
    credential_expires_time DATETIME NOT NULL,
    connection_id VARCHAR(36) NULL,
    scan_requested INT NOT NULL DEFAULT 1,
    scan_completed INT NOT NULL DEFAULT 0,
    runtimes_json TEXT NULL,
    last_seen_time DATETIME NULL,
    last_scan_time DATETIME NULL,
    created_time DATETIME NOT NULL,
    revoked_time DATETIME NULL,
    INDEX idx_mindmap_ai_device_owner (user_id, created_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Optional Kimi ACP runtime. Enable only after provisioning a dedicated CLI account.
INSERT INTO mindmap_ai_connector (
    agent_key, enabled, rollout_percentage, network_policy, health_status,
    conformance_status, create_by, created_time, update_by, update_time
) VALUES ('kimi', 1, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW())
ON DUPLICATE KEY UPDATE agent_key = VALUES(agent_key);

-- Opt-in only: leave disabled until the device bridge has been provisioned.
INSERT INTO mindmap_ai_connector (
    agent_key, enabled, rollout_percentage, network_policy, health_status,
    conformance_status, create_by, created_time, update_by, update_time
) VALUES ('device_claude', 0, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW())
ON DUPLICATE KEY UPDATE agent_key = VALUES(agent_key);

-- Opt-in only. Codex reports estimated usage; it has no USD hard spend cap.
-- Also requires MINDMAP_AI_DEVICE_CODEX_ENABLED and explicit local consent.
INSERT INTO mindmap_ai_connector (
    agent_key, enabled, rollout_percentage, network_policy, health_status,
    conformance_status, create_by, created_time, update_by, update_time
) VALUES ('device_codex', 0, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW())
ON DUPLICATE KEY UPDATE agent_key = VALUES(agent_key);

-- Opt-in only. Kimi has NO monetary spend cap or reported-usage estimator.
-- Requires MINDMAP_AI_DEVICE_KIMI_ENABLED and explicit local unmetered consent.
INSERT INTO mindmap_ai_connector (
    agent_key, enabled, rollout_percentage, network_policy, health_status,
    conformance_status, create_by, created_time, update_by, update_time
) VALUES ('device_kimi', 0, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW())
ON DUPLICATE KEY UPDATE agent_key = VALUES(agent_key);
