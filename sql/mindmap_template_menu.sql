-- ============================================================
-- 模板功能菜单配置
-- Generated with IDs: 1099-1102
-- ============================================================


INSERT INTO sys_menu VALUES(1099, '模板市场', 121, 2, 'templates', 'mindmap/templates', '', '', 1, 0, 'C', '0', '0', 'mindmap:template:list', 'template', 'admin', NOW(), '', NULL, '模板市场页面');

INSERT INTO sys_menu VALUES(1100, '模板管理', 121, 3, 'templateAdmin', 'mindmap/templateAdmin', '', '', 1, 0, 'C', '0', '0', 'mindmap:template:manage', 'template', 'admin', NOW(), '', NULL, '模板管理页面');

INSERT INTO sys_menu VALUES(1101, '发布模板', 1100, 1, '', '', '', '', 1, 0, 'F', '0', '0', 'mindmap:template:add', '#', 'admin', NOW(), '', NULL, '');

INSERT INTO sys_menu VALUES(1102, '下架模板', 1100, 2, '', '', '', '', 1, 0, 'F', '0', '0', 'mindmap:template:remove', '#', 'admin', NOW(), '', NULL, '');
