-- Align legacy mind-map permissions with the controller namespace.
-- Safe to run repeatedly: existing role/menu relations are preserved and no
-- role receives additional capabilities.

START TRANSACTION;

-- Some installations created folder function menus under the abandoned 9000
-- menu tree. Keep the existing IDs, but attach the function group to the live
-- mind-map menu so role permission discovery remains coherent.
UPDATE sys_menu
SET parent_id = 121,
    update_by = 'migration',
    update_time = NOW()
WHERE menu_id = 9010
  AND perms = 'mindmap:folder:list'
  AND parent_id <> 121;

-- Older menu data used a flat namespace while the current controllers and
-- frontend permission directives use a resource-qualified namespace.
UPDATE sys_menu
SET perms = CASE perms
    WHEN 'mindmap:list' THEN 'mindmap:mindmap:list'
    WHEN 'mindmap:query' THEN 'mindmap:mindmap:query'
    WHEN 'mindmap:add' THEN 'mindmap:mindmap:add'
    WHEN 'mindmap:edit' THEN 'mindmap:mindmap:edit'
    WHEN 'mindmap:remove' THEN 'mindmap:mindmap:remove'
    ELSE perms
END,
    update_by = 'migration',
    update_time = NOW()
WHERE perms IN (
    'mindmap:list',
    'mindmap:query',
    'mindmap:add',
    'mindmap:edit',
    'mindmap:remove'
);

COMMIT;
