-- =====================================================
-- 脑图文件夹功能（幂等脚本，可重复执行）
-- =====================================================

-- 1. 新增文件夹表
CREATE TABLE IF NOT EXISTS mindmap_folder (
  id          BIGINT       PRIMARY KEY AUTO_INCREMENT  COMMENT '文件夹ID',
  name        VARCHAR(100) NOT NULL                    COMMENT '文件夹名称',
  parent_id   BIGINT       NOT NULL DEFAULT 0          COMMENT '父文件夹ID（0=顶级）',
  owner_id    BIGINT       NOT NULL                    COMMENT '所有者用户ID',
  sort_order  INT          NOT NULL DEFAULT 0          COMMENT '排序序号',
  del_flag    CHAR(1)      NOT NULL DEFAULT '0'        COMMENT '删除标志（0存在 2删除）',
  create_by   VARCHAR(64)  DEFAULT ''                  COMMENT '创建者',
  create_time DATETIME     DEFAULT CURRENT_TIMESTAMP   COMMENT '创建时间',
  update_by   VARCHAR(64)  DEFAULT ''                  COMMENT '更新者',
  update_time DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  active_name VARCHAR(100) GENERATED ALWAYS AS (CASE WHEN del_flag = '0' THEN name ELSE NULL END) STORED COMMENT '活动目录唯一名称',
  INDEX idx_folder_owner (owner_id, del_flag),
  INDEX idx_folder_parent (parent_id),
  UNIQUE INDEX uq_mindmap_folder_active_sibling (owner_id, parent_id, active_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脑图文件夹表';

-- 2. mindmap 表增加 folder_id 字段（幂等：先判断列是否存在）
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap' AND COLUMN_NAME = 'folder_id');
SET @sql = IF(@col_exists = 0,
  'ALTER TABLE mindmap ADD COLUMN folder_id BIGINT DEFAULT NULL COMMENT ''所属文件夹ID（NULL=根目录）'' AFTER owner_id',
  'SELECT ''folder_id column already exists''');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @owner_folder_idx_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap' AND INDEX_NAME = 'idx_mindmap_owner_folder');
SET @sql = IF(@owner_folder_idx_exists = 0,
  'ALTER TABLE mindmap ADD INDEX idx_mindmap_owner_folder (owner_id, folder_id, del_flag)',
  'SELECT ''owner folder index already exists''');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 添加索引（幂等）
SET @idx_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mindmap' AND INDEX_NAME = 'idx_mindmap_folder');
SET @sql = IF(@idx_exists = 0,
  'ALTER TABLE mindmap ADD INDEX idx_mindmap_folder (folder_id)',
  'SELECT ''index already exists''');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 3. 注册文件夹管理菜单（幂等：INSERT IGNORE）
INSERT IGNORE INTO sys_menu (menu_id, menu_name, parent_id, order_num, path, component, query, route_name, is_frame, is_cache, menu_type, visible, status, perms, icon, create_by, create_time, update_by, update_time, remark)
VALUES
(9010, '文件夹管理', 9000, 5, '', '', NULL, '', 1, 0, 'F', '0', '0', 'mindmap:folder:list',    '#', 'admin', sysdate(), '', NULL, '文件夹查看'),
(9011, '新建文件夹', 9010, 1, '', '', NULL, '', 1, 0, 'F', '0', '0', 'mindmap:folder:add',     '#', 'admin', sysdate(), '', NULL, '新建文件夹'),
(9012, '编辑文件夹', 9010, 2, '', '', NULL, '', 1, 0, 'F', '0', '0', 'mindmap:folder:edit',    '#', 'admin', sysdate(), '', NULL, '编辑文件夹'),
(9013, '删除文件夹', 9010, 3, '', '', NULL, '', 1, 0, 'F', '0', '0', 'mindmap:folder:remove',  '#', 'admin', sysdate(), '', NULL, '删除文件夹');

-- 4. 给管理员角色(1)授权（幂等）
INSERT IGNORE INTO sys_role_menu (role_id, menu_id) VALUES
(1, 9010), (1, 9011), (1, 9012), (1, 9013);
