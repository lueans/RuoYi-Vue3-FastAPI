"""Trusted template fields survive strict replay and canonical domain saves."""
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from exceptions.exception import ServiceException
from module_mindmap.ai.diff import build_document_diff
from module_mindmap.ai.document import MindmapArtifactError, compute_document_hash, normalize_ai_document
from module_mindmap.ai.proposal_operations import (
    materialize_editor_document_from_proposal,
    normalize_proposal_operations_for_apply,
    strict_replay_document_operations,
    verify_proposal_document_integrity,
)
from module_mindmap.ai.template_profile import apply_template_node_format, build_template_profile
from module_mindmap.entity.vo.mindmap_vo import MindmapContentBatchModel
from module_mindmap.service.mindmap_ai_mutation_gateway import MindmapAiMutationConstraints, MindmapAiMutationGateway
from module_mindmap.service.mindmap_service import merge_node_operations


def _node(uid: str, text: str, **data: Any) -> dict[str, Any]:
    return {'data': {'uid': uid, 'text': text, **data}, 'children': []}


def _fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    tag = {'tagId': 7, 'text': 'Priority', 'style': {'fill': '#663399'}, 'placement': 'left', 'align': 'center'}
    source_root = _node('template-root', 'Example topic', fillColor='#abcdef', fontSize=28)
    source_root['children'] = [_node('template-child', 'Example child', fillColor='#fedcba', fontSize=16, tag=[tag])]
    profile = build_template_profile({
        'id': 41, 'contentRevision': 3, 'nodeTree': source_root, 'layout': 'mindMap',
        'theme': {'template': 'default', 'config': {'lineColor': '#123456', 'root': {'fontSize': 28}}},
    })
    base = normalize_ai_document({'root': _node('root', 'User topic')}, content_policy='source')[0]
    artifact = deepcopy(base)
    artifact['root']['data'] = apply_template_node_format(artifact['root']['data'], profile, 'r')
    child = _node('new', 'Generated content unrelated to example', tag=[tag])
    child['data'] = apply_template_node_format(child['data'], profile, 'r.0')
    artifact['root']['children'] = [child]
    artifact['layout'] = profile['layout']
    artifact['theme'] = deepcopy(profile['theme'])
    artifact = normalize_ai_document(artifact, content_policy='source')[0]
    return profile, base, artifact


def test_template_proposal_replays_verifies_and_materializes_exact_format() -> None:
    profile, base, artifact = _fixture()
    base['root']['data']['richText'] = True
    artifact['root']['data']['richText'] = True
    operations, _ = build_document_diff(base, artifact)
    expected_hash = compute_document_hash(artifact)
    frozen = deepcopy((base, artifact, operations, profile))

    assert strict_replay_document_operations(base, operations, template_profile=profile) == artifact
    assert normalize_proposal_operations_for_apply(
        base_document=base, operations=operations, artifact_document=artifact, template_profile=profile,
    ) == operations
    assert verify_proposal_document_integrity(
        base_document=base, operations=operations, artifact_document=artifact,
        proposal_result_hash=expected_hash, manifest_document_hash=expected_hash, template_profile=profile,
    ) == artifact
    editor_source = deepcopy(base)
    editor_source['view'] = {'transform': {'scale': 1.7}}
    editor_source['root']['data']['text'] = '<b>User topic</b>'
    editor_source['root']['data']['richText'] = True
    result = materialize_editor_document_from_proposal(
        source_document=editor_source, operations=operations, artifact_document=artifact, template_profile=profile,
    )
    assert result['root']['data']['text'] == '<b>User topic</b>'
    assert result['root']['children'] == artifact['root']['children']
    assert result['theme'] == profile['theme']
    assert result['view'] == editor_source['view']
    assert (base, artifact, operations, profile) == frozen


@pytest.mark.parametrize('tamper', ['no_profile', 'unknown_profile', 'style', 'missing_style', 'tag_placement', 'theme', 'layout'])
def test_template_proposal_rejects_untrusted_or_incomplete_format(tamper: str) -> None:
    profile, base, artifact = _fixture()
    if tamper == 'unknown_profile':
        artifact['root']['data']['aiTemplateRole'] = 'untrusted:r'
    elif tamper == 'style':
        artifact['root']['data']['fillColor'] = '#000000'
    elif tamper == 'missing_style':
        artifact['root']['data'].pop('fillColor')
    elif tamper == 'tag_placement':
        artifact['root']['children'][0]['data']['tag'][0]['placement'] = 'right'
    elif tamper == 'theme':
        artifact['theme']['config']['lineColor'] = '#000000'
    elif tamper == 'layout':
        artifact['layout'] = 'timeline'
    operations, _ = build_document_diff(base, artifact)
    frozen = deepcopy(base)
    with pytest.raises(MindmapArtifactError):
        strict_replay_document_operations(base, operations, template_profile=None if tamper == 'no_profile' else profile)
    assert base == frozen


@pytest.mark.parametrize('valid_role', [False, True])
def test_template_relationships_allow_content_growth_only_through_compatible_roles(valid_role: bool) -> None:
    profile, _base, before = _fixture()
    artifact = deepcopy(before)
    # A small template can describe many generated nodes, but a child role
    # cannot host the template's root role in a forged frozen operation.
    child = _node('deeper', 'Additional original content')
    child['data'] = apply_template_node_format(child['data'], profile, 'r.0' if valid_role else 'r')
    artifact['root']['children'][0]['children'].append(child)
    artifact = normalize_ai_document(artifact, content_policy='source')[0]
    operations, _ = build_document_diff(before, artifact)
    if valid_role:
        assert strict_replay_document_operations(before, operations, template_profile=profile) == artifact
    else:
        with pytest.raises(MindmapArtifactError, match='父节点关系'):
            strict_replay_document_operations(before, operations, template_profile=profile)


async def _gateway(
    monkeypatch: pytest.MonkeyPatch, operations: list[dict[str, Any]], profile: dict[str, Any] | None,
    base: dict[str, Any], *, scope: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[MindmapContentBatchModel]]:
    detail = SimpleNamespace(
        content_revision=8, owner_id=3, node_tree=deepcopy(base['root']),
        layout=base['layout'], theme=deepcopy(base['theme']), document_data={}, view_data=None,
    )
    batches = []

    async def save(_db: object, _id: int, batch: MindmapContentBatchModel, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        batches.append(batch)
        # Use the real domain projection, including independent tag bindings.
        detail.node_tree = merge_node_operations(detail.node_tree, batch.node_tree, [
            op.model_dump(by_alias=True, exclude_none=True) for op in batch.operations
            if not op.type.startswith('file.')
        ])
        detail.layout, detail.theme = batch.layout, batch.theme
        detail.content_revision = 9
        return {'contentRevision': 9, 'changedNodes': [], 'idempotentReplay': False}

    monkeypatch.setattr('module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.get_mindmap_detail_services', AsyncMock(return_value=detail))
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_mutation_gateway.MindmapService.update_content_batch_services', save)
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_mutation_gateway.MindmapTagService.get_tag_detail', AsyncMock(return_value={
        'id': 7, 'ownerId': 3, 'categoryId': None, 'uuid': 'tag-7', 'tagKey': 'tag-7',
        'name': 'Current authoritative name', 'style': {'fill': '#663399'}, 'status': 0, 'definitionRevision': 4,
    }))
    result = await MindmapAiMutationGateway.apply_draft_operations(
        SimpleNamespace(commit=AsyncMock()), 9, operations, 3, mutation_id='template:test',
        constraints=MindmapAiMutationConstraints(scope=scope, template_profile=profile), commit=False, broadcast=False,
    )
    return result, batches


@pytest.mark.asyncio
async def test_gateway_persists_theme_node_styles_tag_positions_and_relationships(monkeypatch: pytest.MonkeyPatch) -> None:
    profile, base, artifact = _fixture()
    operations, _ = build_document_diff(base, artifact)
    result, batches = await _gateway(monkeypatch, operations, profile, base)
    assert len(batches) == 1
    assert {'file.layout.update', 'file.theme.update', 'node.create', 'node.tag.bind'} <= {op.type for op in batches[0].operations}
    document = result['_committedDocument']
    assert document['layout'] == profile['layout']
    assert document['theme'] == profile['theme']
    assert document['root']['data']['fillColor'] == '#abcdef'
    child = document['root']['children'][0]
    assert child['data']['uid'] == 'new'
    assert child['data']['fontSize'] == profile['roles']['r.0']['style']['fontSize']
    assert child['data']['tag'][0]['text'] == 'Current authoritative name'
    assert child['data']['tag'][0]['style'] == {'fill': '#663399'}
    assert child['data']['tag'][0]['placement'] == 'left'
    assert child['data']['tag'][0]['align'] == 'center'


@pytest.mark.asyncio
@pytest.mark.parametrize('tamper', ['no_profile', 'style', 'missing_style', 'tag_placement', 'theme', 'layout'])
async def test_gateway_rejects_forged_template_format_before_saving(monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    profile, base, artifact = _fixture()
    if tamper == 'style':
        artifact['root']['data']['fillColor'] = '#000000'
    elif tamper == 'missing_style':
        artifact['root']['data'].pop('fillColor')
    elif tamper == 'tag_placement':
        artifact['root']['children'][0]['data']['tag'][0]['placement'] = 'right'
    elif tamper == 'theme':
        artifact['theme']['config']['lineColor'] = '#000000'
    elif tamper == 'layout':
        artifact['layout'] = 'timeline'
    operations, _ = build_document_diff(base, artifact)
    with pytest.raises(ServiceException):
        await _gateway(monkeypatch, operations, None if tamper == 'no_profile' else profile, base)


@pytest.mark.asyncio
async def test_gateway_branch_scope_cannot_apply_template_global_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    profile, base, _ = _fixture()
    operations = [{'type': 'set_document_meta', 'nodeUid': None, 'payload': {
        'set': {'layout': profile['layout'], 'theme': profile['theme']}, 'unset': [],
    }}]
    with pytest.raises(ServiceException) as error:
        await _gateway(monkeypatch, operations, profile, base, scope={'type': 'branch', 'rootUid': 'root'})
    assert '局部授权范围' in error.value.message


@pytest.mark.asyncio
async def test_gateway_cannot_smuggle_arbitrary_style_into_created_node(monkeypatch: pytest.MonkeyPatch) -> None:
    _profile, base, _artifact = _fixture()
    operations = [{'type': 'create_node', 'nodeUid': 'new', 'payload': {
        'parentUid': 'root', 'data': {'uid': 'new', 'text': 'Untrusted', 'fillColor': 'red'},
    }}]
    with pytest.raises(ServiceException) as error:
        await _gateway(monkeypatch, operations, None, base)
    assert '不允许的字段' in error.value.message


@pytest.mark.asyncio
async def test_replay_and_gateway_clear_previous_overrides_when_assigning_a_theme_based_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, base, _artifact = _fixture()
    profile['roles']['r']['style'] = {}
    base['root']['data'].update(fontSize=44, borderWidth=9)
    result = deepcopy(base)
    result['root']['data'] = apply_template_node_format(result['root']['data'], profile, 'r')
    result['theme'] = deepcopy(profile['theme'])
    result['layout'] = profile['layout']
    operations, _ = build_document_diff(base, result)
    assert strict_replay_document_operations(base, operations, template_profile=profile) == result
    committed, _batches = await _gateway(monkeypatch, operations, profile, base)
    assert 'fontSize' not in committed['_committedDocument']['root']['data']
    assert 'borderWidth' not in committed['_committedDocument']['root']['data']
    # Keeping an old inline value unchanged while assigning a new role must
    # not pass the "changed fields only" loophole in either apply boundary.
    result['root']['data']['borderWidth'] = base['root']['data']['borderWidth']
    forged, _ = build_document_diff(base, result)
    with pytest.raises(MindmapArtifactError, match='样式与本轮可信模版'):
        strict_replay_document_operations(base, forged, template_profile=profile)
    with pytest.raises(ServiceException):
        await _gateway(monkeypatch, forged, profile, base)


@pytest.mark.asyncio
async def test_replay_and_gateway_preserve_unchanged_manual_template_edits_outside_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, _base, baseline = _fixture()
    outside = baseline['root']['children'][0]
    editable = deepcopy(outside)
    editable['data']['uid'] = 'edit'
    baseline['root']['children'].append(editable)
    outside['data']['tag'][0]['placement'] = 'bottom'  # Historical manual label placement.
    moved = _node('manual-move', 'Manually moved root role')
    moved['data'] = apply_template_node_format(moved['data'], profile, 'r')
    outside['children'].append(moved)  # Historical incompatible edge, outside this turn.
    baseline = normalize_ai_document(baseline, content_policy='source')[0]
    outside = baseline['root']['children'][0]
    result = deepcopy(baseline)
    result['root']['children'][1]['data']['text'] = 'Updated authorized content'
    operations, _ = build_document_diff(baseline, result)
    assert strict_replay_document_operations(baseline, operations, template_profile=profile) == result
    committed, _batches = await _gateway(monkeypatch, operations, profile, baseline,
                                       scope={'type': 'branch', 'rootUid': 'edit'})
    assert committed['_committedDocument']['root']['children'][0] == outside
    assert committed['_committedDocument']['root']['children'][1]['data']['text'] == 'Updated authorized content'
    # Moving that bad historical relationship to a different parent is a new
    # operation and must not be grandfathered merely because its role is old.
    changed = deepcopy(baseline)
    changed['root']['children'][1]['children'].append(changed['root']['children'][0]['children'].pop())
    forged, _ = build_document_diff(baseline, changed)
    with pytest.raises(MindmapArtifactError, match='父节点关系'):
        strict_replay_document_operations(baseline, forged, template_profile=profile)
    with pytest.raises(ServiceException):
        await _gateway(monkeypatch, forged, profile, baseline)
