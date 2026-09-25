"""AI tags through real batch merge, persistence normalization and DAO readback.

Only database I/O and unrelated permission/version bookkeeping are replaced.
The DAO load_document implementation resolves tag snapshots from the in-memory
ORM rows, exactly as it does after a real SQL transaction.
"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from exceptions.exception import ServiceException
from module_mindmap.ai.change_summary import summarize_committed_node_changes
from module_mindmap.ai.document import compute_document_hash, normalize_ai_editable_source_document
from module_mindmap.dao.mindmap_content_dao import MindmapContentDao
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_tag_dao import MindmapTagDao
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.service.mindmap_ai_mutation_gateway import (
    MindmapAiMutationGateway,
    _document_from_detail,
    _find_node,
)
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_service import MindmapService
from module_mindmap.service.simple_mind_document_codec import EncodedDocument, SimpleMindDocumentCodec

INITIAL_REVISION = 8

FULL_TAG = {
    'tagId': 7,
    'categoryId': None,
    'uuid': 'tag-seven',
    'tagKey': 'custom_important',
    'text': '重要',
    'style': {},
    'status': 0,
    'definitionRevision': 1,
}


class _Rows:
    def __init__(self, rows: list) -> None:
        self.rows = rows

    def scalars(self) -> list:
        return self.rows

    def all(self) -> list:
        return self.rows


class _TagPersistence:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, initial_tag: bool = False) -> None:
        self.tag = MindmapTag(
            id=7, owner_id=3, category_id=None, uuid='tag-seven', tag_key='custom_important',
            name='重要', style={}, status=0, definition_revision=1,
        )
        root = {'data': {'uid': 'root', 'text': 'Root'}, 'children': [
            {'data': {'uid': 'existing', 'text': 'Existing'}, 'children': []},
        ]}
        if initial_tag:
            root['children'][0]['data']['tag'] = [deepcopy(FULL_TAG)]
        self.encoded = SimpleMindDocumentCodec.encode(root)
        for binding in self.encoded.node_tags:
            binding['tag_id'] = 7
        self.logs = []
        self.saved_documents = []
        self.file = SimpleNamespace(
            id=9, owner_id=3, content_revision=INITIAL_REVISION, node_tree=root, layout='logicalStructure',
            theme={'template': 'default', 'config': {}}, view_data=None, document_data={},
            schema_version=2, root_node_id=1, node_count=2,
            engine_name='simple-mind-map', engine_version='test',
        )
        self.db = SimpleNamespace(
            execute=self.execute, add=self.add, commit=AsyncMock(), rollback=AsyncMock(), flush=AsyncMock(),
        )
        monkeypatch.setattr(MindmapService, 'get_mindmap_detail_services', self.detail)
        monkeypatch.setattr(MindmapService, 'check_mindmap_access', AsyncMock())
        monkeypatch.setattr(MindmapDao, 'get_mindmap_for_update', AsyncMock(return_value=self.file))
        monkeypatch.setattr(MindmapDao, 'update_content_dao', self.update)
        monkeypatch.setattr(MindmapContentDao, 'get_change_by_mutation', AsyncMock(return_value=None))
        monkeypatch.setattr(MindmapContentDao, 'get_node_revisions', AsyncMock(return_value={}))
        monkeypatch.setattr(MindmapContentDao, 'sync_document', self.sync)
        monkeypatch.setattr(MindmapTagDao, 'get_tag_by_id', self.read_tag)
        monkeypatch.setattr(MindmapService, '_create_draft_version_safely', AsyncMock())

    def add(self, row: object) -> None:
        if hasattr(row, 'operations'):
            self.logs.append(row)

    async def read_tag(self, _db: object, tag_id: int, **_kwargs) -> MindmapTag | None:
        return self.tag if tag_id == self.tag.id else None

    async def execute(self, query: object) -> _Rows:
        descriptions = getattr(query, 'column_descriptions', None)
        if descriptions is None:
            return _Rows([])  # Usage counter UPDATE, with no document content effect.
        names = tuple(description['name'] for description in descriptions)
        ids = {row['node_uid']: index + 1 for index, row in enumerate(self.encoded.nodes)}
        if names == ('MindmapNode',):
            return _Rows([SimpleNamespace(
                **{key: value for key, value in row.items() if key != 'parent_uid'},
                id=ids[row['node_uid']], parent_id=ids.get(row['parent_uid']),
            ) for row in self.encoded.nodes])
        if names == ('MindmapNodeTag', 'MindmapTag'):
            return _Rows([(SimpleNamespace(
                node_id=ids[row['node_uid']], sort_order=row['sort_order'],
                placement=row.get('placement'), align=row.get('align'),
            ), self.tag) for row in self.encoded.node_tags])
        if names == ('MindmapTag',):
            return _Rows([self.tag])
        if names == ('node_uid', 'tag_id'):
            return _Rows([(row['node_uid'], row['tag_id']) for row in self.encoded.node_tags])
        if names == ('tag_id',):
            return _Rows([row['tag_id'] for row in self.encoded.node_tags])
        if names == ('tag_id', 'file_id'):
            return _Rows([(row['tag_id'], 9) for row in self.encoded.node_tags])
        if names in {('MindmapRelation',), ('MindmapSummary',), ('MindmapGroup',), ('MindmapAsset',)}:
            return _Rows([])
        raise AssertionError(f'Unexpected database read: {names}')

    async def detail(self, *_args, **_kwargs) -> SimpleNamespace:
        # Keep actual DAO.load_document and codec.decode. In particular, never
        # synthesize a raw-tag readback that skips the production resolved data.
        root = await MindmapDocumentService.load_tree(self.db, 9, required=True)
        return SimpleNamespace(**{**self.file.__dict__, 'node_tree': root})

    async def sync(self, _db: object, _mindmap_id: int, encoded: EncodedDocument, *_args, **_kwargs) -> dict:
        self.encoded = deepcopy(encoded)
        self.saved_documents.append(deepcopy(encoded))
        return {
            'root_node_id': 1, 'node_count': len(encoded.nodes),
            'changed_nodes': [row['node_uid'] for row in encoded.nodes],
        }

    async def update(self, _db: object, _mindmap_id: int, data: dict) -> None:
        for key, value in data.items():
            setattr(self.file, key, value)

    async def run(self, operations: list[dict], *, user_id: int = 3) -> dict:
        result = await MindmapAiMutationGateway.apply_draft_operations(
            self.db, 9, operations, user_id, mutation_id=f'tag-projection:{len(self.logs)}',
            commit=False, broadcast=False,
        )
        self.db.commit.assert_not_awaited()
        return result

    async def normalized_document(self) -> dict:
        return normalize_ai_editable_source_document(_document_from_detail(await self.detail()))[0]


def _create(tag: dict | None = None) -> dict:
    data = {'uid': 'new', 'text': 'New'}
    if tag is not None:
        data['tag'] = [deepcopy(tag)]
    return {'type': 'create_node', 'nodeUid': 'new', 'payload': {'parentUid': 'root', 'data': data}}


def _set_tag(uid: str = 'existing', tag: dict | None = None) -> dict:
    return {'type': 'update_node', 'nodeUid': uid, 'payload': {
        'set': {'tag': [deepcopy(FULL_TAG if tag is None else tag)]},
    }}


def _bind() -> dict:
    return {'type': 'node.tag.bind', 'nodeUid': 'new', 'payload': {
        'key': 'new:7', 'tagKey': '7', 'tag': {'tagId': 7},
    }}


@pytest.mark.asyncio
@pytest.mark.parametrize(('operations', 'target', 'summary_kind'), [
    ([_create(FULL_TAG)], 'new', 'added'),
    ([_create({'tagId': 7})], 'new', 'added'),
    ([_create(), _set_tag('new')], 'new', 'added'),
    ([_create(), _bind()], 'new', 'added'),
    ([_create(FULL_TAG), _bind()], 'new', 'added'),
    ([_set_tag()], 'existing', 'updated'),
    ([_set_tag(tag={'tagId': 7})], 'existing', 'updated'),
])
async def test_gateway_tags_match_real_persistence_and_readback(
    monkeypatch: pytest.MonkeyPatch, operations: list[dict], target: str, summary_kind: str,
) -> None:
    state = _TagPersistence(monkeypatch)
    result = await state.run(operations)
    document = await state.normalized_document()
    assert _find_node(document, target)['data']['tag'] == [FULL_TAG]
    assert [(row['node_uid'], row['tag_id']) for row in state.encoded.node_tags] == [(target, 7)]
    assert result['documentHash'] == compute_document_hash(document)
    assert result['_committedDocument'] == document
    expected = {'added': 0, 'updated': 0, 'moved': 0, 'deleted': 0, 'total': 1, summary_kind: 1}
    assert result['changeSummary'] == expected
    assert summarize_committed_node_changes([row.operations for row in state.logs]) == expected


@pytest.mark.asyncio
async def test_existing_tag_unset_removes_the_real_binding_and_hashes_readback(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _TagPersistence(monkeypatch, initial_tag=True)
    result = await state.run([{'type': 'update_node', 'nodeUid': 'existing', 'payload': {'unset': ['tag']}}])
    document = await state.normalized_document()
    assert 'tag' not in _find_node(document, 'existing')['data']
    assert state.encoded.node_tags == []
    assert result['documentHash'] == compute_document_hash(document)
    assert result['changeSummary'] == {'added': 0, 'updated': 1, 'moved': 0, 'deleted': 0, 'total': 1}


@pytest.mark.asyncio
async def test_existing_full_snapshot_to_same_minimal_identity_is_a_real_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _TagPersistence(monkeypatch, initial_tag=True)
    before = await state.normalized_document()
    result = await state.run([_set_tag(tag={'tagId': 7})])
    assert await state.normalized_document() == before
    assert result['changeSummary'] == {'added': 0, 'updated': 0, 'moved': 0, 'deleted': 0, 'total': 0}
    assert result['operationCount'] == 0
    assert state.logs == []
    assert state.saved_documents == []
    assert state.file.content_revision == INITIAL_REVISION


@pytest.mark.asyncio
async def test_later_batch_tag_binding_remains_available_and_same_binding_is_not_recounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _TagPersistence(monkeypatch)
    await state.run([_create()])
    result = await state.run([_set_tag('new', {'tagId': 7})])
    document = await state.normalized_document()
    assert _find_node(document, 'new')['data']['tag'] == [FULL_TAG]
    assert result['documentHash'] == compute_document_hash(document)
    assert result['changeSummary']['updated'] == 1
    repeated = await state.run([_set_tag('new', {'tagId': 7})])
    assert repeated['changeSummary']['total'] == 0
    assert state.file.content_revision == INITIAL_REVISION + len(state.logs)
    assert summarize_committed_node_changes([row.operations for row in state.logs]) == {
        'added': 1, 'updated': 0, 'moved': 0, 'deleted': 0, 'total': 1,
    }


@pytest.mark.asyncio
async def test_authorized_collaborator_can_retain_same_node_owner_private_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _TagPersistence(monkeypatch, initial_tag=True)
    before = await state.normalized_document()
    result = await state.run([_set_tag(tag={'tagId': 7})], user_id=4)
    assert result['changeSummary']['total'] == 0
    assert result['documentHash'] == compute_document_hash(before)
    assert await state.normalized_document() == before
    assert state.logs == []


@pytest.mark.asyncio
@pytest.mark.parametrize('operations', [
    [_create({'tagId': 7})],
    [_set_tag('root', {'tagId': 7})],
    # A permitted retention may cache a definition, but it must not expand
    # authorization for a subsequent new binding elsewhere in the same batch.
    [_set_tag(tag={'tagId': 7}), _create({'tagId': 7})],
    [_set_tag(tag={'tagId': 7}), _set_tag('root', {'tagId': 7})],
])
async def test_collaborator_cannot_reuse_owner_private_tag_on_another_node(
    monkeypatch: pytest.MonkeyPatch, operations: list[dict],
) -> None:
    state = _TagPersistence(monkeypatch, initial_tag=True)
    before = await state.normalized_document()
    with pytest.raises(ServiceException):
        await state.run(operations, user_id=4)
    assert await state.normalized_document() == before
    assert state.saved_documents == []
    assert state.logs == []
    state.db.commit.assert_not_awaited()
