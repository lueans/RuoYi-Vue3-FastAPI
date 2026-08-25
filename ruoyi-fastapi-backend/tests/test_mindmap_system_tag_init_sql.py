"""系统标签初始化 SQL 的静态契约。"""

import re
from pathlib import Path

from module_mindmap.service.mindmap_marker_tags import MINDMAP_MARKER_GROUP_COUNTS


SQL_DIR = Path(__file__).resolve().parents[2] / 'sql'


def _expected_group_catalog() -> dict[str, tuple[str, int]]:
    return {
        'priority': ('优先级', MINDMAP_MARKER_GROUP_COUNTS['priority']),
        'progress': ('任务', MINDMAP_MARKER_GROUP_COUNTS['progress']),
        'expression': ('表情', MINDMAP_MARKER_GROUP_COUNTS['expression']),
        'sign': ('符号', MINDMAP_MARKER_GROUP_COUNTS['sign']),
    }


def _assert_pure_seed_script(sql: str) -> None:
    assert sum(MINDMAP_MARKER_GROUP_COUNTS.values()) == 61
    assert 'builtin_marker_' in sql
    assert 'mindmap-marker-' in sql
    assert 'mindmap_node_tag' not in sql
    assert 'UPDATE mindmap_node' not in sql
    assert 'DELETE FROM mindmap_ws_state' not in sql


def test_mysql_system_tag_init_contains_the_complete_marker_catalog() -> None:
    sql = (SQL_DIR / 'mindmap_system_tags.sql').read_text(encoding='utf-8')

    catalog = {
        group: (label, count)
        for group, label, count in re.findall(
            r"(?:SELECT|UNION ALL SELECT) '([^']+)'(?: AS type_name)?, '([^']+)'"
            r"(?: AS category_name)?, (\d+)",
            sql,
        )
    }

    assert catalog == {
        group: (label, str(count))
        for group, (label, count) in _expected_group_catalog().items()
    }
    assert "JSON_OBJECT('iconKey', icon_key" in sql
    assert 'ON DUPLICATE KEY UPDATE' in sql
    _assert_pure_seed_script(sql)


def test_postgresql_system_tag_init_contains_the_complete_marker_catalog() -> None:
    sql = (SQL_DIR / 'mindmap_system_tags_postgresql.sql').read_text(encoding='utf-8')

    catalog = {
        group: (label, count)
        for group, label, count in re.findall(r"\('([^']+)', '([^']+)', (\d+)\)", sql)
    }

    assert catalog == {
        group: (label, str(count))
        for group, (label, count) in _expected_group_catalog().items()
    }
    assert "JSONB_BUILD_OBJECT('iconKey', icon_key" in sql
    assert 'ON CONFLICT (owner_id, tag_key) DO NOTHING' in sql
    assert 'DELIMITER' not in sql
    assert '`' not in sql
    _assert_pure_seed_script(sql)
