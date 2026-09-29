"""Static contracts for the two consolidated optional runtime migrations."""

import re
from pathlib import Path

import pytest

from module_mindmap.entity.do.mindmap_ai_device_do import MindmapAiDevice

MIGRATIONS = Path(__file__).parents[1] / 'migrations'


@pytest.mark.parametrize('suffix', ['', '_postgresql'])
def test_runtime_bundle_preserves_device_schema_and_connector_policy(suffix):
    sql = (MIGRATIONS / f'20260926_mindmap_agent_runtime{suffix}.sql').read_text(encoding='utf-8')
    assert f'Prerequisite: 20260910_mindmap_ai_agent{suffix}.sql' in sql
    assert sql.count('CREATE TABLE IF NOT EXISTS mindmap_ai_device (') == 1
    columns = set(re.findall(r'^    ([a-z_]+) (?:VARCHAR|BIGINT|INT|INTEGER|DATETIME|TIMESTAMP|TEXT)\b', sql, re.M))
    assert columns == set(MindmapAiDevice.__table__.columns.keys())
    assert 'id VARCHAR(36) PRIMARY KEY' in sql
    assert re.search(r'scan_requested (?:INT|INTEGER) NOT NULL DEFAULT 1', sql)
    assert re.search(r'scan_completed (?:INT|INTEGER) NOT NULL DEFAULT 0', sql)
    assert 'idx_mindmap_ai_device_owner' in sql and '(user_id, created_time)' in sql
    seeds = re.findall(r"VALUES \('([^']+)', ([01]), 100, 'adapter_default', 'unknown', 'unknown'", sql)
    assert seeds == [('kimi', '1'), ('device_claude', '0'), ('device_codex', '0'), ('device_kimi', '0')]
    conflict = 'ON CONFLICT (agent_key) DO NOTHING;' if suffix else 'ON DUPLICATE KEY UPDATE agent_key = VALUES(agent_key);'
    assert sql.count(conflict) == 4
    assert not re.search(r'^\s*(ALTER|DELETE|DROP|UPDATE)\b', sql, re.M | re.I)


def test_runtime_setup_documents_only_reference_existing_migrations():
    root = MIGRATIONS.parents[1]
    for name in ('mindmap-agent-bridge/README.md', 'docs/mindmap-agent-runtime.md'):
        document = (root / name).read_text(encoding='utf-8')
        for filename in re.findall(r'202609\d{2}_mindmap_[a-z_]+\.sql', document):
            assert (MIGRATIONS / filename).is_file(), f'{name}: missing {filename}'
