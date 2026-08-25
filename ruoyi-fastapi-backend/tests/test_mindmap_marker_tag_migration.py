"""内置标记数据迁移的静态发布契约。"""

from pathlib import Path

MIGRATION_DIR = Path(__file__).parents[1] / 'migrations'


def test_mysql_marker_migration_seeds_and_rebinds_all_legacy_markers() -> None:
    sql = (MIGRATION_DIR / '20260825_mindmap_markers_to_tags.sql').read_text(encoding='utf-8')

    assert "SELECT 'priority' AS type_name, '优先级' AS category_name, 10" in sql
    assert "UNION ALL SELECT 'progress', '任务', 8" in sql
    assert "UNION ALL SELECT 'expression', '表情', 20" in sql
    assert "UNION ALL SELECT 'sign', '符号', 23" in sql
    assert "JSON_OBJECT('iconKey', marker.`icon_key`" in sql
    assert 'BINARY category.`name` = BINARY marker.`category_name`' in sql
    assert 'BINARY marker.`icon_key` = BINARY legacy_icon.`icon_key`' in sql
    assert 'BINARY tag.`tag_key` = BINARY marker.`tag_key`' in sql
    assert 'CREATE TEMPORARY TABLE `tmp_mindmap_marker_categories`' in sql
    assert 'SET tag.`category_id` = canonical.`category_id`' in sql
    assert 'DELETE category' in sql
    assert 'WHERE existing.`id` IS NULL' in sql
    assert 'INSERT IGNORE INTO `mindmap_node_tag`' in sql
    assert "JSON_SEARCH(node.`content_data`, 'one', marker.`icon_key`" in sql
    assert ') AS tag_usage ON tag_usage.`tag_id` = tag.`id`' in sql
    assert 'COALESCE(tag_usage.`node_count`, 0)' in sql
    assert 'DELETE FROM `mindmap_ws_state`' in sql
    assert sql.index('CREATE PROCEDURE `migrate_mindmap_marker_icon_payload`') < sql.index('START TRANSACTION')
    assert sql.index('START TRANSACTION') < sql.index('CALL `migrate_mindmap_marker_icon_payload`()')
    assert sql.index('CALL `migrate_mindmap_marker_icon_payload`()') < sql.index('DELETE FROM `mindmap_ws_state`')
    assert sql.index('DELETE FROM `mindmap_ws_state`') < sql.index('COMMIT;')


def test_postgresql_marker_migration_has_equivalent_seed_and_payload_rewrite() -> None:
    sql = (
        MIGRATION_DIR / '20260825_mindmap_markers_to_tags_postgresql.sql'
    ).read_text(encoding='utf-8')

    assert "('priority', '优先级', 10, 100)" in sql
    assert "('progress', '任务', 8, 200)" in sql
    assert "('expression', '表情', 20, 300)" in sql
    assert "('sign', '符号', 23, 400)" in sql
    assert "JSONB_BUILD_OBJECT('iconKey', icon_key" in sql
    assert 'INSERT INTO mindmap_node_tag' in sql
    assert "THEN node.content_data - 'icon'" in sql
    assert 'DELETE FROM mindmap_ws_state' in sql
    assert 'DELIMITER' not in sql
    assert '`' not in sql
