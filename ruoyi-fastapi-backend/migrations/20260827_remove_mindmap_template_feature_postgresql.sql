-- Remove the retired mindmap template market and administration feature.
-- PostgreSQL 14+; safe to run repeatedly on the current application schema.

BEGIN;

CREATE TEMPORARY TABLE tmp_removed_mindmap_template_ids (
    id BIGINT PRIMARY KEY
) ON COMMIT DROP;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'mindmap'
          AND column_name = 'is_template'
    ) THEN
        EXECUTE 'INSERT INTO tmp_removed_mindmap_template_ids (id) '
                'SELECT id FROM mindmap WHERE is_template = 1';
    END IF;
END $$;

DELETE FROM mindmap_comment AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.mindmap_id;
DELETE FROM mindmap_comment_thread AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.mindmap_id;
DELETE FROM mindmap_version AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.mindmap_id;
DELETE FROM mindmap_share AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.mindmap_id;
DELETE FROM mindmap_collaborator AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.mindmap_id;
DELETE FROM mindmap_ws_state AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.mindmap_id;
DELETE FROM mindmap_group_member AS member
USING mindmap_group AS group_row, tmp_removed_mindmap_template_ids AS removed
WHERE member.group_id = group_row.id AND removed.id = group_row.file_id;
DELETE FROM mindmap_node_tag AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.file_id;
DELETE FROM mindmap_relation AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.file_id;
DELETE FROM mindmap_summary AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.file_id;
DELETE FROM mindmap_group AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.file_id;
DELETE FROM mindmap_asset AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.file_id;
DELETE FROM mindmap_node AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.file_id;
DELETE FROM mindmap_change_log AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.file_id;
DELETE FROM mindmap_migration_record AS child
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = child.file_id;
DELETE FROM mindmap_creation_request AS request_row
USING tmp_removed_mindmap_template_ids AS removed
WHERE request_row.operation = 'template' OR removed.id = request_row.result_file_id;
DELETE FROM mindmap_creation_request WHERE operation = 'template';
DELETE FROM mindmap AS file_row
USING tmp_removed_mindmap_template_ids AS removed
WHERE removed.id = file_row.id;

CREATE TEMPORARY TABLE tmp_mindmap_template_menu_ids (
    menu_id BIGINT PRIMARY KEY
) ON COMMIT DROP;
INSERT INTO tmp_mindmap_template_menu_ids (menu_id)
SELECT menu_id
FROM sys_menu
WHERE component IN ('mindmap/templates', 'mindmap/templateAdmin')
   OR perms LIKE 'mindmap:template:%'
   OR (menu_name IN ('模板市场', '模板管理') AND path IN ('templates', 'templateAdmin'))
ON CONFLICT DO NOTHING;
DELETE FROM sys_role_menu AS role_menu
USING tmp_mindmap_template_menu_ids AS removed
WHERE removed.menu_id = role_menu.menu_id;
DELETE FROM sys_menu AS menu_row
USING tmp_mindmap_template_menu_ids AS removed
WHERE removed.menu_id = menu_row.menu_id;

ALTER TABLE mindmap DROP CONSTRAINT IF EXISTS fk_mindmap_template_category;
DROP INDEX IF EXISTS idx_mindmap_template_market;
DROP INDEX IF EXISTS idx_mindmap_owner_folder;
DROP INDEX IF EXISTS idx_mindmap_owner_status;
CREATE INDEX idx_mindmap_owner_folder ON mindmap(owner_id, folder_id, del_flag);
CREATE INDEX idx_mindmap_owner_status ON mindmap(owner_id, status, del_flag, update_time);
ALTER TABLE mindmap DROP COLUMN IF EXISTS template_category_id;
ALTER TABLE mindmap DROP COLUMN IF EXISTS is_template;
DROP TABLE IF EXISTS mindmap_template_category;

COMMIT;
