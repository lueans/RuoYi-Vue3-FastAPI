-- ============================================================
-- 标签管理菜单配置
-- Generated with IDs: 1103-1108
-- 执行: mysql -u root -proot ruoyi-fastapi < sql/mindmap_tag_menu.sql
-- ============================================================

-- 标签管理菜单（ID: 1103，父菜单: 思维导图 121）
INSERT INTO sys_menu VALUES(1103, '标签管理', 121, 4, 'tags', 'mindmap/tags', '', '', 1, 0, 'C', '0', '0', 'mindmap:tag:query', 'tag', 'admin', NOW(), '', NULL, '标签管理页面');

-- 标签管理按钮权限
INSERT INTO sys_menu VALUES(1104, '标签新增', 1103, 1, '', '', '', '', 1, 0, 'F', '0', '0', 'mindmap:tag:add', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES(1105, '标签修改', 1103, 2, '', '', '', '', 1, 0, 'F', '0', '0', 'mindmap:tag:edit', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES(1106, '标签删除', 1103, 3, '', '', '', '', 1, 0, 'F', '0', '0', 'mindmap:tag:remove', '#', 'admin', NOW(), '', NULL, '');

-- 为普通角色（role_id=2）分配标签管理权限
INSERT INTO sys_role_menu VALUES(2, 1103);
INSERT INTO sys_role_menu VALUES(2, 1104);
INSERT INTO sys_role_menu VALUES(2, 1105);
INSERT INTO sys_role_menu VALUES(2, 1106);
