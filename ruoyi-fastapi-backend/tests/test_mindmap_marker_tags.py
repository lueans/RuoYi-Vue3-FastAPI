"""历史节点标记迁移为统一标签的运行时契约。"""

from types import SimpleNamespace

from module_mindmap.service.mindmap_marker_tags import (
    MINDMAP_MARKER_ICON_KEYS,
    apply_legacy_marker_tags,
    collect_legacy_marker_tag_keys,
    marker_icon_key_from_tag_key,
    marker_tag_key,
)
from module_mindmap.service.simple_mind_document_codec import EncodedDocument

EXPECTED_MARKER_ICON_COUNT = 61
EXPECTED_MIGRATED_COUNT = 2


def _tag(tag_id: int, icon_key: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=tag_id,
        uuid=f'uuid-{tag_id}',
        tag_key=f'builtin_marker_{icon_key}',
        name=icon_key,
        style={'iconKey': icon_key, 'placement': 'right', 'align': 'center'},
        status=0,
        owner_id=0,
        definition_revision=1,
    )


def test_marker_catalog_matches_all_legacy_builtin_icons() -> None:
    assert len(MINDMAP_MARKER_ICON_KEYS) == EXPECTED_MARKER_ICON_COUNT
    assert marker_tag_key('priority_1') == 'builtin_marker_priority_1'
    assert marker_tag_key('sign_23') == 'builtin_marker_sign_23'
    assert marker_tag_key('priority_11') is None
    assert marker_tag_key('custom_1') is None
    assert marker_icon_key_from_tag_key('builtin_marker_priority_1') == 'priority_1'
    assert marker_icon_key_from_tag_key('builtin_marker_priority_11') is None
    assert marker_icon_key_from_tag_key('priority_1') is None


def test_runtime_migration_adds_bindings_and_preserves_unknown_icons() -> None:
    document = EncodedDocument(
        nodes=[{
            'node_uid': 'root',
            'content_data': {'icon': ['priority_1', 'custom_1', 'sign_23'], 'note': '保留'},
        }],
        node_tags=[],
    )

    assert collect_legacy_marker_tag_keys(document) == {
        'builtin_marker_priority_1',
        'builtin_marker_sign_23',
    }
    assert (
        apply_legacy_marker_tags(document, [_tag(1, 'priority_1'), _tag(2, 'sign_23')])
        == EXPECTED_MIGRATED_COUNT
    )
    assert document.nodes[0]['content_data'] == {'icon': ['custom_1'], 'note': '保留'}
    assert [binding['raw']['tagId'] for binding in document.node_tags] == [1, 2]
    assert [binding['sort_order'] for binding in document.node_tags] == [0, 1]


def test_runtime_migration_deduplicates_existing_marker_binding() -> None:
    document = EncodedDocument(
        nodes=[{'node_uid': 'root', 'content_data': {'icon': ['priority_1']}}],
        node_tags=[{
            'node_uid': 'root',
            'sort_order': 0,
            'placement': 'right',
            'align': 'center',
            'raw': {'tagId': 1},
        }],
    )

    assert apply_legacy_marker_tags(document, [_tag(1, 'priority_1')]) == 1
    assert len(document.node_tags) == 1
    assert document.nodes[0]['content_data'] is None
