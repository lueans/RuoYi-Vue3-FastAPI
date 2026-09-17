-- AI 脑图 Agent 需求合并迁移（MySQL 8+）
-- 按开发顺序拼接：基础表与菜单 -> Connector 治理策略 -> 到期索引补齐
--   -> 讨论模式文字结果 -> 实时草稿加密检查点。各段保留幂等守卫，可安全重复执行。
-- AI 脑图任务、Artifact、Proposal 与事件

CREATE TABLE IF NOT EXISTS `mindmap_ai_session` (
    `id` VARCHAR(36) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `current_agent_key` VARCHAR(64) NOT NULL,
    `title` VARCHAR(200) NULL,
    `status` VARCHAR(24) NOT NULL DEFAULT 'active',
    `latest_artifact_id` VARCHAR(36) NULL,
    `created_time` DATETIME NOT NULL,
    `update_time` DATETIME NOT NULL,
    `expires_time` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    KEY `idx_mindmap_ai_session_user_updated` (`user_id`, `update_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 脑图多轮会话';

CREATE TABLE IF NOT EXISTS `mindmap_ai_connector` (
    `agent_key` VARCHAR(64) NOT NULL,
    `enabled` TINYINT NOT NULL DEFAULT 1,
    `rollout_percentage` INT NOT NULL DEFAULT 100,
    `credential_ref` VARCHAR(255) NULL,
    `data_region` VARCHAR(64) NULL,
    `retention_policy` VARCHAR(100) NULL,
    `network_policy` VARCHAR(24) NOT NULL DEFAULT 'adapter_default',
    `health_status` VARCHAR(24) NOT NULL DEFAULT 'unknown',
    `health_reason` VARCHAR(500) NULL,
    `conformance_status` VARCHAR(24) NOT NULL DEFAULT 'unknown',
    `conformance_report_json` TEXT NULL,
    `last_health_time` DATETIME NULL,
    `last_conformance_time` DATETIME NULL,
    `create_by` VARCHAR(64) NOT NULL,
    `created_time` DATETIME NOT NULL,
    `update_by` VARCHAR(64) NOT NULL,
    `update_time` DATETIME NOT NULL,
    PRIMARY KEY (`agent_key`),
    CONSTRAINT `chk_mindmap_ai_connector_rollout` CHECK (`rollout_percentage` BETWEEN 0 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 脑图 Agent 运营配置';

CREATE TABLE IF NOT EXISTS `mindmap_ai_job` (
    `id` VARCHAR(36) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `session_id` VARCHAR(36) NOT NULL,
    `parent_job_id` VARCHAR(36) NULL,
    `retry_of_job_id` VARCHAR(36) NULL,
    `turn_index` INT NOT NULL DEFAULT 1,
    `agent_key` VARCHAR(64) NOT NULL,
    `adapter_version` VARCHAR(32) NOT NULL,
    `sdk_version` VARCHAR(32) NULL,
    `runtime_version` VARCHAR(32) NULL,
    `model_ref` VARCHAR(128) NULL,
    `intent` VARCHAR(32) NOT NULL,
    `target` VARCHAR(16) NOT NULL,
    `source_type` VARCHAR(32) NOT NULL,
    `source_mindmap_id` BIGINT NULL,
    `base_revision` BIGINT NULL,
    `base_hash` VARCHAR(80) NULL,
    `base_room_epoch` VARCHAR(64) NULL,
    `request_json` LONGTEXT NOT NULL,
    `request_fingerprint` CHAR(64) NOT NULL,
    `idempotency_key` VARCHAR(100) NOT NULL,
    `status` VARCHAR(32) NOT NULL DEFAULT 'queued',
    `progress` INT NOT NULL DEFAULT 0,
    `title` VARCHAR(200) NULL,
    `artifact_id` VARCHAR(36) NULL,
    `proposal_id` VARCHAR(36) NULL,
    `external_session_ref` TEXT NULL,
    `usage_json` TEXT NULL,
    `error_code` VARCHAR(64) NULL,
    `error_message` VARCHAR(500) NULL,
    `cancel_requested_time` DATETIME NULL,
    `completed_time` DATETIME NULL,
    `expires_time` DATETIME NOT NULL,
    `created_time` DATETIME NOT NULL,
    `update_time` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_ai_job_user_idempotency` (`user_id`, `idempotency_key`),
    KEY `idx_mindmap_ai_job_user_created` (`user_id`, `created_time`),
    KEY `idx_mindmap_ai_job_session_turn` (`session_id`, `turn_index`),
    KEY `idx_mindmap_ai_job_status_updated` (`status`, `update_time`),
    KEY `idx_mindmap_ai_job_status_expires` (`status`, `expires_time`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 脑图任务';

CREATE TABLE IF NOT EXISTS `mindmap_ai_artifact` (
    `id` VARCHAR(36) NOT NULL,
    `job_id` VARCHAR(36) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `title` VARCHAR(200) NOT NULL,
    `content_json` LONGTEXT NOT NULL,
    `document_hash` VARCHAR(80) NOT NULL,
    `validation_status` VARCHAR(16) NOT NULL,
    `validator_version` VARCHAR(64) NOT NULL,
    `node_count` INT NOT NULL,
    `tree_depth` INT NOT NULL,
    `byte_size` INT NOT NULL,
    `created_time` DATETIME NOT NULL,
    `expires_time` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_ai_artifact_job` (`job_id`),
    KEY `idx_mindmap_ai_artifact_user_created` (`user_id`, `created_time`),
    KEY `idx_mindmap_ai_artifact_expires` (`expires_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 脑图不可变文件结果';

CREATE TABLE IF NOT EXISTS `mindmap_ai_proposal` (
    `id` VARCHAR(36) NOT NULL,
    `job_id` VARCHAR(36) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `proposal_type` VARCHAR(24) NOT NULL,
    `base_document_id` VARCHAR(64) NULL,
    `target_mindmap_id` BIGINT NULL,
    `base_revision` BIGINT NULL,
    `base_hash` VARCHAR(80) NULL,
    `base_room_epoch` VARCHAR(64) NULL,
    `scope_json` TEXT NULL,
    `operations_json` LONGTEXT NOT NULL,
    `result_artifact_id` VARCHAR(36) NOT NULL,
    `result_hash` VARCHAR(80) NOT NULL,
    `impact_json` TEXT NOT NULL,
    `warnings_json` TEXT NOT NULL,
    `status` VARCHAR(24) NOT NULL DEFAULT 'ready',
    `applied_revision` BIGINT NULL,
    `applied_time` DATETIME NULL,
    `created_time` DATETIME NOT NULL,
    `expires_time` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_ai_proposal_job` (`job_id`),
    KEY `idx_mindmap_ai_proposal_user_status` (`user_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 脑图候选变更';

CREATE TABLE IF NOT EXISTS `mindmap_ai_job_event` (
    `id` BIGINT NOT NULL AUTO_INCREMENT,
    `job_id` VARCHAR(36) NOT NULL,
    `sequence` INT NOT NULL,
    `event_type` VARCHAR(64) NOT NULL,
    `payload_json` TEXT NOT NULL,
    `created_time` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_ai_event_job_sequence` (`job_id`, `sequence`),
    KEY `idx_mindmap_ai_event_job_id` (`job_id`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 脑图任务事件';

CREATE TABLE IF NOT EXISTS `mindmap_ai_undo` (
    `proposal_id` VARCHAR(36) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `mindmap_id` BIGINT NOT NULL,
    `before_document_json` LONGTEXT NOT NULL,
    `before_hash` VARCHAR(80) NOT NULL,
    `applied_hash` VARCHAR(80) NOT NULL,
    `applied_revision` BIGINT NOT NULL,
    `status` VARCHAR(24) NOT NULL DEFAULT 'available',
    `undone_revision` BIGINT NULL,
    `created_time` DATETIME NOT NULL,
    `expires_time` DATETIME NOT NULL,
    PRIMARY KEY (`proposal_id`),
    KEY `idx_mindmap_ai_undo_user_created` (`user_id`, `created_time`),
    KEY `idx_mindmap_ai_undo_expires` (`expires_time`, `proposal_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI 云端应用条件撤销快照';

-- AI 使用权限独立于脑图查看/编辑权限。升级时只继承给已经拥有脑图查询
-- 能力的角色，管理员仍可在角色管理中单独撤销。
INSERT INTO `sys_menu` (
    `menu_id`, `menu_name`, `parent_id`, `order_num`, `path`, `component`,
    `query`, `route_name`, `is_frame`, `is_cache`, `menu_type`, `visible`,
    `status`, `perms`, `icon`, `create_by`, `create_time`, `update_by`,
    `update_time`, `remark`
)
SELECT GREATEST(
    COALESCE((SELECT MAX(`menu_id`) FROM `sys_menu`), 9019) + 1,
    9020
), 'AI 脑图使用', COALESCE(
    (SELECT `menu_id` FROM `sys_menu` WHERE `perms` = 'mindmap:list' LIMIT 1),
    121
), 90, '', '', '', '', 1, 0, 'F', '0', '0', 'mindmap:ai:use', '#',
    'migration', NOW(), '', NULL, '独立控制 AI 脑图 Agent 使用权限'
WHERE NOT EXISTS (SELECT 1 FROM `sys_menu` WHERE `perms` = 'mindmap:ai:use');

INSERT IGNORE INTO `sys_role_menu` (`role_id`, `menu_id`)
SELECT DISTINCT role_menu.`role_id`, ai_menu.`menu_id`
FROM `sys_role_menu` role_menu
JOIN `sys_menu` source_menu ON source_menu.`menu_id` = role_menu.`menu_id`
JOIN `sys_menu` ai_menu ON ai_menu.`perms` = 'mindmap:ai:use'
WHERE source_menu.`perms` IN (
    'mindmap:list', 'mindmap:query',
    'mindmap:mindmap:list', 'mindmap:mindmap:query'
);

INSERT IGNORE INTO `sys_role_menu` (`role_id`, `menu_id`)
SELECT 1, ai_menu.`menu_id`
FROM `sys_menu` ai_menu
WHERE ai_menu.`perms` = 'mindmap:ai:use';

INSERT INTO `sys_menu` (
    `menu_id`, `menu_name`, `parent_id`, `order_num`, `path`, `component`,
    `query`, `route_name`, `is_frame`, `is_cache`, `menu_type`, `visible`,
    `status`, `perms`, `icon`, `create_by`, `create_time`, `update_by`,
    `update_time`, `remark`
)
SELECT GREATEST(
    COALESCE((SELECT MAX(`menu_id`) FROM `sys_menu`), 9020) + 1,
    9021
), 'AI Agent 管理', COALESCE(
    (SELECT `menu_id` FROM `sys_menu` WHERE `perms` = 'mindmap:list' LIMIT 1),
    121
), 91, 'ai-agents', 'mindmap/ai-agents', '', 'MindmapAiAgents', 1, 0, 'C', '0', '0', 'mindmap:ai:admin', 'monitor',
    'migration', NOW(), '', NULL, '管理 Agent Connector、健康状态和一致性检查'
WHERE NOT EXISTS (SELECT 1 FROM `sys_menu` WHERE `perms` = 'mindmap:ai:admin');

UPDATE `sys_menu`
SET `menu_name` = 'AI Agent 管理', `path` = 'ai-agents',
    `component` = 'mindmap/ai-agents', `route_name` = 'MindmapAiAgents',
    `menu_type` = 'C', `icon` = 'monitor', `update_by` = 'migration',
    `update_time` = NOW()
WHERE `perms` = 'mindmap:ai:admin';

INSERT IGNORE INTO `sys_role_menu` (`role_id`, `menu_id`)
SELECT role.`role_id`, menu.`menu_id`
FROM `sys_role` role
JOIN `sys_menu` menu ON menu.`perms` = 'mindmap:ai:admin'
WHERE role.`role_id` = 1;


-- ===================================================================
-- AI 脑图 Connector 运行治理与任务策略快照（MySQL 8+）

DROP PROCEDURE IF EXISTS `upgrade_mindmap_ai_connector_policy`;
DELIMITER $$
CREATE PROCEDURE `upgrade_mindmap_ai_connector_policy`()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_connector'
          AND COLUMN_NAME = 'model_allowlist_json'
    ) THEN
        ALTER TABLE `mindmap_ai_connector` ADD COLUMN `model_allowlist_json` TEXT NULL AFTER `network_policy`;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_connector'
          AND COLUMN_NAME = 'max_budget_usd'
    ) THEN
        ALTER TABLE `mindmap_ai_connector` ADD COLUMN `max_budget_usd` DECIMAL(10,4) NOT NULL DEFAULT 5.0000 AFTER `model_allowlist_json`;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_connector'
          AND COLUMN_NAME = 'timeout_seconds'
    ) THEN
        ALTER TABLE `mindmap_ai_connector` ADD COLUMN `timeout_seconds` INT NOT NULL DEFAULT 900 AFTER `max_budget_usd`;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_connector'
          AND COLUMN_NAME = 'max_nodes'
    ) THEN
        ALTER TABLE `mindmap_ai_connector` ADD COLUMN `max_nodes` INT NOT NULL DEFAULT 2000 AFTER `timeout_seconds`;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_connector'
          AND COLUMN_NAME = 'max_depth'
    ) THEN
        ALTER TABLE `mindmap_ai_connector` ADD COLUMN `max_depth` INT NOT NULL DEFAULT 32 AFTER `max_nodes`;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_connector'
          AND COLUMN_NAME = 'max_concurrent_jobs'
    ) THEN
        ALTER TABLE `mindmap_ai_connector` ADD COLUMN `max_concurrent_jobs` INT NOT NULL DEFAULT 4 AFTER `max_depth`;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_job'
          AND COLUMN_NAME = 'max_budget_usd'
    ) THEN
        ALTER TABLE `mindmap_ai_job` ADD COLUMN `max_budget_usd` DECIMAL(10,4) NOT NULL DEFAULT 5.0000 AFTER `model_ref`;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_job'
          AND COLUMN_NAME = 'timeout_seconds'
    ) THEN
        ALTER TABLE `mindmap_ai_job` ADD COLUMN `timeout_seconds` INT NOT NULL DEFAULT 900 AFTER `max_budget_usd`;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_job'
          AND COLUMN_NAME = 'max_nodes'
    ) THEN
        ALTER TABLE `mindmap_ai_job` ADD COLUMN `max_nodes` INT NOT NULL DEFAULT 2000 AFTER `timeout_seconds`;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_job'
          AND COLUMN_NAME = 'max_depth'
    ) THEN
        ALTER TABLE `mindmap_ai_job` ADD COLUMN `max_depth` INT NOT NULL DEFAULT 32 AFTER `max_nodes`;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_job'
          AND COLUMN_NAME = 'retention_days'
    ) THEN
        ALTER TABLE `mindmap_ai_job` ADD COLUMN `retention_days` INT NOT NULL DEFAULT 30 AFTER `max_depth`;
    END IF;
END$$
DELIMITER ;
CALL `upgrade_mindmap_ai_connector_policy`();
DROP PROCEDURE IF EXISTS `upgrade_mindmap_ai_connector_policy`;

INSERT INTO `mindmap_ai_connector` (
    `agent_key`, `enabled`, `rollout_percentage`, `network_policy`,
    `health_status`, `conformance_status`, `create_by`, `created_time`,
    `update_by`, `update_time`
) VALUES
    ('native_mindmap', 1, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW()),
    ('codex', 1, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW()),
    ('claude', 1, 100, 'adapter_default', 'unknown', 'unknown', 'migration', NOW(), 'migration', NOW())
ON DUPLICATE KEY UPDATE `agent_key` = VALUES(`agent_key`);


-- ===================================================================
-- AI 脑图安全热修：补齐到期扫描索引，并给既有脑图角色新增 AI 使用权限。
-- 仅执行幂等的 ADD INDEX / INSERT，不删除或改写既有业务数据。

DROP PROCEDURE IF EXISTS `ensure_mindmap_ai_retention_indexes`;
DELIMITER $$
CREATE PROCEDURE `ensure_mindmap_ai_retention_indexes`()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_ai_job'
          AND INDEX_NAME = 'idx_mindmap_ai_job_status_expires'
    ) THEN
        ALTER TABLE `mindmap_ai_job`
            ADD INDEX `idx_mindmap_ai_job_status_expires` (`status`, `expires_time`, `id`);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'mindmap_ai_undo'
          AND INDEX_NAME = 'idx_mindmap_ai_undo_expires'
    ) THEN
        ALTER TABLE `mindmap_ai_undo`
            ADD INDEX `idx_mindmap_ai_undo_expires` (`expires_time`, `proposal_id`);
    END IF;
END$$
DELIMITER ;

CALL `ensure_mindmap_ai_retention_indexes`();
DROP PROCEDURE IF EXISTS `ensure_mindmap_ai_retention_indexes`;

INSERT IGNORE INTO `sys_role_menu` (`role_id`, `menu_id`)
SELECT DISTINCT source_role_menu.`role_id`, ai_menu.`menu_id`
FROM `sys_role_menu` source_role_menu
JOIN `sys_menu` source_menu ON source_menu.`menu_id` = source_role_menu.`menu_id`
JOIN `sys_menu` ai_menu ON ai_menu.`perms` = 'mindmap:ai:use'
WHERE source_menu.`perms` IN (
    'mindmap:list', 'mindmap:query',
    'mindmap:mindmap:list', 'mindmap:mindmap:query'
);

INSERT IGNORE INTO `sys_role_menu` (`role_id`, `menu_id`)
SELECT 1, ai_menu.`menu_id`
FROM `sys_menu` ai_menu
WHERE ai_menu.`perms` = 'mindmap:ai:use';


-- ===================================================================
-- AI 脑图零工具讨论模式与独立文字结果（MySQL 8+）

DROP PROCEDURE IF EXISTS `upgrade_mindmap_ai_discussion`;
DELIMITER $$
CREATE PROCEDURE `upgrade_mindmap_ai_discussion`()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_job'
          AND COLUMN_NAME = 'response_id'
    ) THEN
        ALTER TABLE `mindmap_ai_job`
            ADD COLUMN `response_id` VARCHAR(36) NULL AFTER `proposal_id`;
    END IF;
END$$
DELIMITER ;
CALL `upgrade_mindmap_ai_discussion`();
DROP PROCEDURE IF EXISTS `upgrade_mindmap_ai_discussion`;

CREATE TABLE IF NOT EXISTS `mindmap_ai_response` (
    `id` VARCHAR(36) NOT NULL,
    `job_id` VARCHAR(36) NOT NULL,
    `user_id` BIGINT NOT NULL,
    `content_type` VARCHAR(32) NOT NULL DEFAULT 'text/plain',
    `content_text` LONGTEXT NOT NULL,
    `content_hash` CHAR(64) NOT NULL,
    `byte_size` INT NOT NULL,
    `created_time` DATETIME NOT NULL,
    `expires_time` DATETIME NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_mindmap_ai_response_job` (`job_id`),
    KEY `idx_mindmap_ai_response_user_created` (`user_id`, `created_time`),
    KEY `idx_mindmap_ai_response_expires` (`expires_time`, `id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='AI 脑图讨论模式文字答复';


-- ===================================================================
-- AI 脑图实时草稿持久检查点（MySQL 8+）
-- 正文、增量与初始帧均以应用层 Fernet 密文保存；事件表只保留元数据。

DROP PROCEDURE IF EXISTS `upgrade_mindmap_ai_draft_checkpoint`;
DELIMITER $$
CREATE PROCEDURE `upgrade_mindmap_ai_draft_checkpoint`()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap_ai_job'
          AND COLUMN_NAME = 'execution_epoch'
    ) THEN
        ALTER TABLE `mindmap_ai_job`
            ADD COLUMN `execution_epoch` INT NOT NULL DEFAULT 0 AFTER `turn_index`;
    END IF;
END$$
DELIMITER ;
CALL `upgrade_mindmap_ai_draft_checkpoint`();
DROP PROCEDURE IF EXISTS `upgrade_mindmap_ai_draft_checkpoint`;

CREATE TABLE IF NOT EXISTS `mindmap_ai_draft_checkpoint` (
    `job_id` VARCHAR(36) NOT NULL COMMENT 'AI 任务 ID（一对一）',
    `preview_version` INT NOT NULL COMMENT '任务内单调预览版本',
    `preview_epoch` INT NOT NULL COMMENT '执行轮次',
    `document_ciphertext` LONGTEXT NOT NULL COMMENT '加密后的完整草稿文档',
    `operations_ciphertext` LONGTEXT NOT NULL COMMENT '加密后的本帧操作',
    `initial_state_ciphertext` LONGTEXT NULL COMMENT '加密后的初始帧',
    `document_hash` VARCHAR(80) NOT NULL COMMENT '解密文档规范哈希',
    `summary_json` TEXT NOT NULL COMMENT '不含正文的结构摘要',
    `expires_time` DATETIME NOT NULL COMMENT '到期时间',
    `created_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`job_id`),
    KEY `idx_mindmap_ai_draft_checkpoint_expires` (`expires_time`, `job_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='AI 脑图实时草稿加密检查点';
