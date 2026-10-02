"""Exercise template directory and read-access predicates on an isolated SQL database."""

import sqlite3
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import mysql, postgresql, sqlite

from common.vo import PageModel
from exceptions.exception import ServiceException
from module_mindmap.service.mindmap_ai_template_service import MAX_TEMPLATE_PATH_LENGTH, MindmapAiTemplateService
from module_mindmap.service.mindmap_service import MindmapService
from utils.page_util import PageUtil


@pytest.fixture
def database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.executescript('''
        CREATE TABLE mindmap_folder (id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER, owner_id INTEGER, del_flag TEXT);
        CREATE TABLE mindmap (id INTEGER PRIMARY KEY, name TEXT, description TEXT, owner_id INTEGER,
            folder_id INTEGER, node_count INTEGER DEFAULT 3, content_revision INTEGER DEFAULT 1,
            status INTEGER DEFAULT 0, del_flag TEXT DEFAULT '0', update_time TEXT DEFAULT '2026-10-01',
            node_tree TEXT DEFAULT 'private raw tree');
        CREATE TABLE mindmap_collaborator (id INTEGER PRIMARY KEY, mindmap_id INTEGER, user_id INTEGER, permission INTEGER);
        CREATE TABLE sys_user (user_id INTEGER PRIMARY KEY, nick_name TEXT);
        INSERT INTO sys_user VALUES (7, 'Me'), (8, 'Other');
        INSERT INTO mindmap_folder VALUES
            (1, '私有上层', 0, 7, '0'), (2, '模版', 1, 7, '0'), (3, '产品', 2, 7, '0'),
            (4, '模板', 3, 7, '0'), (5, '工作', 1, 7, '0'),
            (6, '已删除', 2, 7, '2'), (7, '孤立模版', 6, 7, '0'),
            (8, '模版', 999, 7, '0'), (9, '模版', 10, 7, '0'), (10, '循环', 9, 7, '0'),
            (20, '对方私有上层', 0, 8, '0'), (21, '模板', 20, 8, '0'), (22, '需求', 21, 8, '0'),
            (23, '跨所有者损坏目录', 2, 8, '0'), (24, '模版备份', 0, 7, '0');
        INSERT INTO mindmap (id, name, description, owner_id, folder_id) VALUES
            (101, '登录用例', '验证码与流程', 7, 3), (102, '嵌套模版', '', 7, 4),
            (103, '只读共享', '登录参考', 8, 22), (104, '私有不可见', '', 8, 22),
            (105, '普通目录', '', 7, 5), (106, '删除祖先', '', 7, 7),
            (107, '目录不存在', '', 7, 999), (108, '孤儿目录', '', 7, 8),
            (109, '循环目录', '', 7, 9), (110, '跨所有者目录', '', 8, 23),
            (111, '仅名称含模版', '', 7, 24), (112, '脑图与目录所有者不同', '', 7, 22),
            (113, '100%_覆盖', '', 7, 2), (114, '100XX覆盖', '', 7, 2);
        INSERT INTO mindmap (id, name, owner_id, folder_id, status, del_flag) VALUES
            (115, '归档共享', 8, 22, 1, '0'), (116, '已删除', 7, 2, 0, '2');
        INSERT INTO mindmap_collaborator VALUES (1, 103, 7, 0), (2, 115, 7, 0), (3, 110, 7, 1);
    ''')
    try:
        yield connection
    finally:
        connection.close()


def fetch(database: sqlite3.Connection, keyword: str | None = None, offset: int = 0, limit: int = 50) -> list[dict]:
    query = MindmapAiTemplateService._query(7, keyword).offset(offset).limit(limit)
    sql = str(query.compile(dialect=sqlite.dialect(), compile_kwargs={'literal_binds': True}))
    return [dict(row) for row in database.execute(sql).fetchall()]


@pytest.mark.parametrize(('dialect', 'cast_type'), [(mysql.dialect, 'CHAR'), (postgresql.dialect, 'VARCHAR')])
def test_recursive_template_paths_have_matching_explicit_types(dialect: type, cast_type: str) -> None:
    query = MindmapAiTemplateService._query(7)
    sql = str(query.compile(dialect=dialect(), compile_kwargs={'literal_binds': True}))
    # PostgreSQL requires the recursive term to match the anchor's varchar
    # typmod; merely compiling a differently typed query does not detect it.
    recursive_terms = 2
    assert sql.count(f'AS {cast_type}({MAX_TEMPLATE_PATH_LENGTH})') == recursive_terms


def test_template_scope_includes_owned_shared_and_archived_without_private_or_broken_directories(database: sqlite3.Connection) -> None:
    rows = fetch(database)
    assert {row['id'] for row in rows} == {101, 102, 103, 113, 114, 115}
    by_id = {row['id']: row for row in rows}
    assert by_id[101]['folder_path'] == '模版 / 产品'
    assert by_id[102]['folder_path'] == '模板'
    assert by_id[103]['folder_path'] == '模板 / 需求'
    assert by_id[115]['status'] == 1
    assert all('node_tree' not in row for row in rows)
    assert all('私有上层' not in row['folder_path'] for row in rows)


def test_template_search_uses_name_and_description_and_escapes_wildcards(database: sqlite3.Connection) -> None:
    assert {row['id'] for row in fetch(database, ' 登录 ')} == {101, 103}
    assert [row['id'] for row in fetch(database, '%_')] == [113]
    assert fetch(database, '不存在') == []
    first = fetch(database, offset=0, limit=2)
    second = fetch(database, offset=2, limit=2)
    assert {row['id'] for row in first}.isdisjoint(row['id'] for row in second)
    assert first + second == fetch(database, limit=4)


def test_template_directory_depth_is_bounded(database: sqlite3.Connection) -> None:
    for depth in range(1, 22):
        database.execute('INSERT INTO mindmap_folder VALUES (?, ?, ?, 7, ?)',
            (1000 + depth, '模版' if depth == 1 else f'层级{depth}', 1000 + depth - 1 if depth > 1 else 0, '0'))
    database.execute("INSERT INTO mindmap (id, name, owner_id, folder_id) VALUES (120, '最深有效', 7, 1020), (121, '超出深度', 7, 1021)")
    ids = {row['id'] for row in fetch(database)}
    assert ids.intersection({120, 121}) == {120}


@pytest.mark.asyncio
async def test_template_list_returns_paginated_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    paginate = AsyncMock(return_value=PageModel(rows=[{
        'id': 101, 'name': '登录', 'folderId': 3, 'folderName': '产品', 'folderPath': '模版 / 产品',
        'nodeTree': {'private': 'must not leak'},
    }], total=1, pageNum=2, pageSize=10, hasNext=False))
    monkeypatch.setattr(PageUtil, 'paginate', paginate)
    result = await MindmapAiTemplateService.list_templates(object(), 7, '登录', 2, 10)
    assert (result.page_num, result.page_size, result.total) == (2, 10, 1)
    assert 'nodeTree' not in result.rows[0]
    assert paginate.await_args.args[-3:] == (2, 10, True)


def template_row() -> dict:
    return {'id': 103, 'name': '共享模版', 'folder_id': 22, 'folder_name': '需求',
        'folder_path': '模板 / 需求', 'content_revision': 1}


def template_db(row: dict | None) -> SimpleNamespace:
    return SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        mappings=lambda: SimpleNamespace(first=lambda: row))))


@pytest.mark.asyncio
async def test_template_detail_rejects_outside_directory_or_inaccessible_map_before_loading_content(monkeypatch: pytest.MonkeyPatch) -> None:
    load = AsyncMock()
    monkeypatch.setattr(MindmapService, 'get_mindmap_detail_services', load)
    with pytest.raises(ServiceException) as error:
        await MindmapAiTemplateService.get_template(template_db(None), 104, 7)
    assert '模版不存在' in error.value.message
    load.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [0, 1])
async def test_template_detail_uses_authoritative_tree_and_rechecks_read_access(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    tree = {'data': {'text': '结构化权威树'}, 'children': []}
    revision = 9
    load = AsyncMock(return_value=SimpleNamespace(status=status, folder_id=22, content_state='ready',
        name='最新名称', content_revision=revision, node_tree=tree, layout='logicalStructure', theme={}))
    monkeypatch.setattr(MindmapService, 'get_mindmap_detail_services', load)
    db = template_db(template_row())
    result = await MindmapAiTemplateService.get_template(db, 103, 7)
    load.assert_awaited_once_with(db, 103, 7)
    assert result['nodeTree'] == tree
    assert result['name'] == '最新名称'
    assert result['contentRevision'] == revision
    assert result['folderPath'] == '模板 / 需求'
    assert result['status'] == status


@pytest.mark.asyncio
@pytest.mark.parametrize(('folder_id', 'content_state'), [(99, 'ready'), (22, 'load_failed')])
async def test_template_detail_rejects_moved_or_unreadable_content(monkeypatch: pytest.MonkeyPatch, folder_id: int, content_state: str) -> None:
    monkeypatch.setattr(MindmapService, 'get_mindmap_detail_services', AsyncMock(return_value=SimpleNamespace(
        status=0, folder_id=folder_id, content_state=content_state)))
    with pytest.raises(ServiceException):
        await MindmapAiTemplateService.get_template(template_db(template_row()), 103, 7)
