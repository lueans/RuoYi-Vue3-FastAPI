-- ============================================================
-- 脑图管理功能 — 完整数据库迁移脚本
-- 执行顺序：先建表，再改表，最后插入菜单数据
-- 适用：MySQL 8.0+
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- 1. 脑图 Yjs 文档持久化状态表（Phase 2: WebSocket 实时协作）
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mindmap_ws_state (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL COMMENT '脑图ID',
    yjs_state MEDIUMBLOB COMMENT 'Yjs文档二进制状态',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE INDEX idx_ws_mindmap (mindmap_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图Yjs文档持久化状态表';

-- ────────────────────────────────────────────────────────────
-- 2. 脑图版本历史表（Phase 3: 版本历史）
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mindmap_version (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL COMMENT '脑图ID',
    version_number INT NOT NULL COMMENT '版本号',
    version_type SMALLINT NOT NULL DEFAULT 0 COMMENT '版本类型: 0=草稿 1=正式',
    name VARCHAR(200) COMMENT '版本名称（仅正式版本）',
    node_tree LONGTEXT NOT NULL COMMENT '节点树快照JSON',
    view_data JSON COMMENT '视图状态快照',
    layout VARCHAR(50) COMMENT '布局类型',
    theme JSON COMMENT '主题配置',
    created_by VARCHAR(64) NOT NULL COMMENT '创建者',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_version_mindmap (mindmap_id, version_type),
    INDEX idx_version_time (mindmap_id, created_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图版本历史表';

-- ────────────────────────────────────────────────────────────
-- 3. 脑图分享链接表（Phase 4: 分享功能）
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mindmap_share (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL COMMENT '脑图ID',
    share_token VARCHAR(64) NOT NULL UNIQUE COMMENT '分享token',
    share_type SMALLINT NOT NULL DEFAULT 0 COMMENT '0=查看 1=编辑',
    expire_time DATETIME COMMENT '过期时间（NULL=永久）',
    created_by BIGINT NOT NULL COMMENT '创建者用户ID',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active SMALLINT NOT NULL DEFAULT 1 COMMENT '是否有效',
    INDEX idx_share_token (share_token),
    INDEX idx_share_mindmap (mindmap_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图分享链接表';

-- ────────────────────────────────────────────────────────────
-- 4. 脑图协作者表（Phase 4: 协作权限）
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mindmap_collaborator (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL COMMENT '脑图ID',
    user_id BIGINT NOT NULL COMMENT '协作用户ID',
    permission SMALLINT NOT NULL DEFAULT 0 COMMENT '0=查看 1=编辑',
    created_by BIGINT NOT NULL COMMENT '添加者用户ID',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_collab_unique (mindmap_id, user_id),
    INDEX idx_collab_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图协作者表';

-- ────────────────────────────────────────────────────────────
-- 5. 菜单和权限数据
-- ────────────────────────────────────────────────────────────
-- 执行前先确认 ID 9000-9005 未被占用：
--   SELECT menu_id FROM sys_menu WHERE menu_id BETWEEN 9000 AND 9010;

-- 脑图管理一级菜单
INSERT INTO sys_menu VALUES('9000', '脑图管理', '0', '6', 'mindmap', NULL, '', '1', '0', 'M', '0', '0', '', 'mindmap', 'admin', NOW(), '', NULL, '脑图管理目录');

-- 脑图列表页
INSERT INTO sys_menu VALUES('9001', '脑图列表', '9000', '1', 'index', 'mindmap/index', '', '1', '0', 'C', '0', '0', 'mindmap:mindmap:list', 'mindmap', 'admin', NOW(), '', NULL, '脑图列表菜单');

-- 脑图管理按钮权限
INSERT INTO sys_menu VALUES('9002', '脑图查询', '9001', '1', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:query', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES('9003', '脑图新增', '9001', '2', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:add', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES('9004', '脑图修改', '9001', '3', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:edit', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES('9005', '脑图删除', '9001', '4', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:remove', '#', 'admin', NOW(), '', NULL, '');
