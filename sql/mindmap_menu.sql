-- 脑图管理菜单（parent_id=0 为一级菜单）
INSERT INTO sys_menu VALUES('9000', '脑图管理', '0', '6', 'mindmap', NULL, '', '1', '0', 'M', '0', '0', '', 'mindmap', 'admin', NOW(), '', NULL, '脑图管理目录');

-- 脑图列表页（parent_id=9000）
INSERT INTO sys_menu VALUES('9001', '脑图列表', '9000', '1', 'index', 'mindmap/index', '', '1', '0', 'C', '0', '0', 'mindmap:mindmap:list', 'mindmap', 'admin', NOW(), '', NULL, '脑图列表菜单');

-- 脑图管理按钮权限
INSERT INTO sys_menu VALUES('9002', '脑图查询', '9001', '1', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:query', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES('9003', '脑图新增', '9001', '2', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:add', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES('9004', '脑图修改', '9001', '3', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:edit', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES('9005', '脑图删除', '9001', '4', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:remove', '#', 'admin', NOW(), '', NULL, '');
