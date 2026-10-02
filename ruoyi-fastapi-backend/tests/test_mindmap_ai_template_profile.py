"""Trusted template formats survive actual tools, previews and persisted jobs."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from exceptions.exception import ServiceException
from module_mindmap.ai.adapters.base import AgentRunContext, agent_target_layout, build_agent_user_prompt
from module_mindmap.ai.document import MindmapArtifactError
from module_mindmap.ai.message_context import user_message_attachments
from module_mindmap.ai.template_profile import (
    build_template_profile,
    read_template_profile,
    template_role_id,
)
from module_mindmap.ai.tool_contract import MindmapToolService
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel
from module_mindmap.service.mindmap_ai_service import MindmapAiService, MindmapAiTaskManager
from module_mindmap.service.mindmap_ai_template_service import MindmapAiTemplateService

TAG = {'tagId': 7, 'text': 'Important', 'style': {
    'fill': '#ffeedd', 'color': '#112233', 'fontSize': 16, 'placement': 'top', 'align': 'right',
}, 'status': 0}
CHILD_FONT_SIZE = 18


def detail() -> dict:
    return {
        'id': 9, 'contentRevision': 4, 'layout': 'mindMap',
        'theme': {'template': 'default', 'config': {'backgroundColor': '#abcdef', 'root': {'fontSize': 24}}},
        'nodeTree': {'data': {'uid': 'template-root', 'text': 'Old topic', 'fillColor': '#123456'}, 'children': [
            {'data': {'uid': 'template-child', 'text': 'Only one example', 'fontSize': CHILD_FONT_SIZE,
                      'shape': 'roundedRectangle', 'tag': [{**TAG, 'placement': 'bottom', 'align': 'left'}]},
             'children': []},
        ]},
    }


def request(**changes: object) -> MindmapAiJobCreateModel:
    return MindmapAiJobCreateModel(prompt='Generate a completely new topic and many details', attachments=[{
        'id': 'selected-template', 'name': 'Chosen template', 'mediaType': 'application/x-mindmap-template',
        'size': 20, 'text': 'Client text cannot grant any style authority', 'purpose': 'template',
        'templateSource': {'mindmapId': 9, 'contentRevision': 4},
    }], **changes)


def test_profile_is_bounded_format_data_and_identity_changes_with_visual_style() -> None:
    original = detail()
    original['nodeTree']['children'][0]['data']['tag'].append(TAG)
    original['nodeTree']['data'].update(image='https://private/image', onClick='unsafe', pluginSecret='hidden')
    original['theme']['config']['backgroundImage'] = 'url(https://private/image)'
    profile = build_template_profile(original)
    assert profile['roles']['r']['style'] == {'fillColor': '#123456'}
    assert len(profile['roles']['r.0']['tags']) == 1
    assert 'private' not in json.dumps(profile)
    assert 'pluginSecret' not in json.dumps(profile)
    original['nodeTree']['data']['fillColor'] = '#ffffff'
    assert build_template_profile(original)['profileId'] != profile['profileId']
    assert profile['roles']['r']['style']['fillColor'] == '#123456'


@pytest.mark.asyncio
async def test_server_freeze_ignores_client_profile_and_revalidates_revision_and_access(monkeypatch: pytest.MonkeyPatch) -> None:
    model = request(_templateProfile={'profileId': 'forged', 'roles': {'r': {'style': {'fillColor': 'red'}}}})
    assert model._template_profile is None
    getter = AsyncMock(return_value=detail())
    monkeypatch.setattr(MindmapAiTemplateService, 'get_template', getter)
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_template_service.load_ai_tag_catalog', AsyncMock(return_value=[TAG]))
    await MindmapAiTemplateService.freeze_request_template(object(), model, 3)
    frozen = MindmapAiTemplateService.frozen_request_payload(model)
    getter.assert_awaited_once_with(getter.await_args.args[0], 9, 3)
    assert read_template_profile(frozen)['roles']['r']['style'] == {'fillColor': '#123456'}
    restored = MindmapAiJobCreateModel.model_validate(frozen)
    assert restored._template_profile is None  # API deserialization never grants authority.
    assert read_template_profile(json.loads(json.dumps(frozen))) == model._template_profile
    getter.return_value = {**detail(), 'contentRevision': 5}
    with pytest.raises(ServiceException) as changed:
        await MindmapAiTemplateService.freeze_request_template(object(), request(), 3)
    assert '模版已更新' in changed.value.message
    getter.side_effect = ServiceException(message='无查看权限')
    with pytest.raises(ServiceException) as forbidden:
        await MindmapAiTemplateService.freeze_request_template(object(), request(), 3)
    assert forbidden.value.message == '无查看权限'


@pytest.mark.asyncio
async def test_unavailable_template_tags_are_filtered_and_have_deterministic_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MindmapAiTemplateService, 'get_template', AsyncMock(return_value=detail()))
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_template_service.load_ai_tag_catalog', AsyncMock(return_value=[]))
    model = request()
    await MindmapAiTemplateService.freeze_request_template(object(), model, 3)
    frozen = MindmapAiTemplateService.frozen_request_payload(model)
    assert frozen['_templateProfile']['roles']['r.0']['tags'] == []
    receipt = user_message_attachments(frozen)[0]
    assert receipt['warnings'] == ['模版中的部分标签当前不可引用，已跳过这些标签：Important']
    assert 'text' not in receipt


def test_recovery_requires_matching_frozen_profile_and_never_inherits_without_current_template() -> None:
    model = request()
    model._template_profile = build_template_profile(detail())
    frozen = MindmapAiTemplateService.frozen_request_payload(model)
    corrupted = deepcopy(frozen)
    corrupted['_templateProfile']['roles']['r']['style']['fillColor'] = '#ffffff'
    with pytest.raises(MindmapArtifactError, match='快照损坏'):
        read_template_profile(corrupted)
    with pytest.raises(MindmapArtifactError, match='快照缺失'):
        read_template_profile(model.model_dump(by_alias=True))
    assert read_template_profile({**frozen, 'attachments': []}) is None
    no_template = MindmapAiJobCreateModel(prompt='next turn')
    assert '_templateProfile' not in MindmapAiTemplateService.frozen_request_payload(no_template, frozen)


def test_template_styles_tags_and_new_content_survive_stream_fork_and_artifact() -> None:
    profile = build_template_profile(detail())
    tools = MindmapToolService(template_profile=profile, tag_catalog=[TAG])
    root_uid = tools.start_document('Entirely new topic')['rootUid']
    first = tools.add_nodes([{'parentUid': root_uid, 'text': 'New material', 'templateRole': 'r.0'}])['created'][0]['nodeUid']
    tools.add_nodes([{'parentUid': first, 'text': 'Extra details absent from template'}])
    projection = tools.read_projection()
    assert projection['layout'] == 'mindMap'
    assert projection['theme'] == profile['theme']
    assert projection['root']['data']['text'] == 'Entirely new topic'
    assert projection['root']['data']['fillColor'] == '#123456'
    child = projection['root']['children'][0]
    assert child['data']['fontSize'] == CHILD_FONT_SIZE
    assert child['data']['tag'] == [{**TAG, 'placement': 'bottom', 'align': 'left'}]
    assert child['children'][0]['data']['text'] == 'Extra details absent from template'
    assert child['children'][0]['data']['fontSize'] == CHILD_FONT_SIZE
    assert tools.fork().read_projection() == projection
    delta = tools.build_stream_delta(after_cursor=0, tool_name='add_nodes')
    assert delta['previewState'] == projection
    assert delta['operations'][0]['payload']['data']['fontSize'] == CHILD_FONT_SIZE
    artifact, _, _ = tools.complete_artifact(title='new topic', agent_key='native_mindmap', adapter_version='1', prompt_version='1')
    assert artifact['document']['root']['children'][0]['data']['tag'][0]['style'] == TAG['style']
    assert artifact['document']['theme'] == profile['theme']


def test_template_checkpoint_restoration_keeps_style_and_role_identity() -> None:
    profile = build_template_profile(detail())
    initial = {'root': {'data': {'uid': 'root', 'text': 'Existing'}, 'children': []},
               'layout': 'logicalStructure', 'theme': {'template': 'default', 'config': {}}}
    tools = MindmapToolService(base_document=initial, template_profile=profile, tag_catalog=[TAG], trusted_source=True)
    tools.update_nodes([{'nodeUid': 'root', 'patch': {'templateRole': 'r', 'text': 'New topic'}}])
    tools.add_nodes([{'parentUid': 'root', 'text': 'New child'}])
    recovered = MindmapToolService(base_document=initial, template_profile=profile, tag_catalog=[TAG], trusted_source=True)
    recovered.restore_checkpoint_projection(tools.read_projection())
    assert recovered.read_projection() == tools.read_projection()
    different = detail()
    different['nodeTree']['data']['fillColor'] = '#000000'
    different_profile = build_template_profile(different)
    assert template_role_id(tools.read_projection()['root']['data'], different_profile) is None


def test_local_scope_applies_role_without_changing_global_theme_and_layout() -> None:
    profile = build_template_profile(detail())
    source = {'root': {'data': {'uid': 'root', 'text': 'Existing'}, 'children': [
        {'data': {'uid': 'branch', 'text': 'Branch'}, 'children': []},
    ]}, 'layout': 'logicalStructure', 'theme': {'template': 'default', 'config': {}}}
    tools = MindmapToolService(base_document=source, scope={'type': 'branch', 'rootUid': 'branch'},
                              trusted_source=True, template_profile=profile, tag_catalog=[TAG])
    tools.update_nodes([{'nodeUid': 'branch', 'patch': {'templateRole': 'r', 'text': 'New content'}}])
    assert tools.read_projection()['layout'] == source['layout']
    assert tools.read_projection()['theme'] == source['theme']
    assert all(item['type'] != 'set_document_meta' for item in tools.build_stream_delta(after_cursor=0, tool_name='update_nodes')['operations'])
    with pytest.raises(MindmapArtifactError, match='授权范围'):
        tools.update_nodes([{'nodeUid': 'root', 'patch': {'templateRole': 'r'}}])


def test_model_cannot_create_styles_or_invent_role_and_template_layout_wins_ui_default() -> None:
    profile = build_template_profile(detail())
    tools = MindmapToolService(template_profile=profile, tag_catalog=[TAG])
    root = tools.start_document('New')['rootUid']
    for patch in ({'fillColor': 'red'}, {'templateRole': 'invented'}, {'templateRole': 'r.0'}):
        with pytest.raises(MindmapArtifactError):
            tools.update_nodes([{'nodeUid': root, 'patch': patch}])
    ctx = AgentRunContext(job_id='test', user_id=3, intent='create', prompt='New content',
                          parameters={'layout': 'logicalStructure'}, source_document=None,
                          tool_service=tools, template_profile=profile, attachments=tuple(request().model_dump(by_alias=True)['attachments']))
    assert agent_target_layout(ctx) == 'mindMap'
    prompt = build_agent_user_prompt(ctx)
    assert 'templateRole' in prompt
    assert '不是节点 UID' in prompt
    assert '唯一 clientRef' in prompt


def test_existing_node_updates_use_default_role_and_reject_other_authorized_tags() -> None:
    profile = build_template_profile(detail())
    source = {'root': {'data': {'uid': 'root', 'text': 'Existing'}, 'children': [
        {'data': {'uid': 'child', 'text': 'Old content', 'fontSize': 44, 'borderWidth': 9,
                  'pluginMetadata': 'preserved'}, 'children': []},
    ]}}
    tools = MindmapToolService(base_document=source, template_profile=profile, trusted_source=True,
                              tag_catalog=[TAG, {**TAG, 'tagId': 99}])
    with pytest.raises(MindmapArtifactError, match='标签不属于'):
        tools.update_nodes([{'nodeUid': 'child', 'patch': {'text': 'New', 'tag': [{'tagId': 99}]}}])
    tools.update_nodes([{'nodeUid': 'child', 'patch': {'text': 'Entirely new content'}}])
    node = tools._draft.document['root']['children'][0]['data']
    assert template_role_id(node, profile) == 'r.0'
    assert node['fontSize'] == CHILD_FONT_SIZE
    assert node['tag'] == [{**TAG, 'placement': 'bottom', 'align': 'left'}]
    assert 'borderWidth' not in node
    assert node['pluginMetadata'] == 'preserved'
    assert tools._draft.document['root']['data']['text'] == 'Existing'


def test_explicit_role_clears_old_inline_overrides_that_mask_the_new_theme() -> None:
    template = detail()
    template['nodeTree']['data'].pop('fillColor')
    profile = build_template_profile(template)
    source = {'root': {'data': {'uid': 'root', 'text': 'Existing', 'fontSize': 44, 'borderWidth': 9,
                               'image': 'https://example.test/preserved.png'}, 'children': []}}
    tools = MindmapToolService(base_document=source, template_profile=profile, trusted_source=True, tag_catalog=[TAG])
    tools.update_nodes([{'nodeUid': 'root', 'patch': {'templateRole': 'r'}}])
    result = tools._draft.document
    assert result['theme']['config']['root']['fontSize'] == template['theme']['config']['root']['fontSize']
    assert 'fontSize' not in result['root']['data']
    assert 'borderWidth' not in result['root']['data']
    assert result['root']['data']['image'] == 'https://example.test/preserved.png'
    # Reapplying an identical role must not emit an invalid empty update.
    cursor = len(tools._draft.operations)
    tools.update_nodes([{'nodeUid': 'root', 'patch': {'templateRole': 'r'}}])
    assert len(tools._draft.operations) == cursor


def test_unchanged_manual_relations_and_tags_outside_scope_do_not_block_another_branch() -> None:
    template = detail()
    template['nodeTree']['children'].append({'data': {'uid': 'other-role', 'text': 'Other'}, 'children': []})
    profile = build_template_profile(template)
    generator = MindmapToolService(template_profile=profile, tag_catalog=[TAG])
    root = generator.start_document('New topic')['rootUid']
    nodes = generator.add_nodes([
        {'parentUid': root, 'text': 'A', 'templateRole': 'r.0'},
        {'parentUid': root, 'text': 'B', 'templateRole': 'r.1'},
        {'parentUid': root, 'text': 'C', 'templateRole': 'r.0'},
    ])['created']
    baseline = deepcopy(generator._draft.document)
    moved = baseline['root']['children'].pop(1)
    baseline['root']['children'][0]['children'].append(moved)
    baseline['root']['children'][0]['data']['tag'] = [{**TAG, 'tagId': 99, 'placement': 'top'}]
    untouched = deepcopy(baseline['root']['children'][0])
    tools = MindmapToolService(base_document=baseline, template_profile=profile, trusted_source=True,
                              scope={'type': 'branch', 'rootUid': nodes[2]['nodeUid']}, tag_catalog=[TAG])
    tools.update_nodes([{'nodeUid': nodes[2]['nodeUid'], 'patch': {'text': 'New C content'}}])
    assert tools._draft.document['root']['children'][0] == untouched
    assert tools._draft.document['root']['children'][1]['data']['text'] == 'New C content'


def _manually_reparented_template_source() -> tuple[dict, dict, str, str]:
    template = detail()
    template['nodeTree']['children'].extend([
        {'data': {'uid': 'second-role', 'text': 'Second'}, 'children': []},
        {'data': {'uid': 'third-role', 'text': 'Third'}, 'children': []},
    ])
    profile = build_template_profile(template)
    generator = MindmapToolService(template_profile=profile, tag_catalog=[TAG])
    root = generator.start_document('Topic')['rootUid']
    created = generator.add_nodes([
        {'parentUid': root, 'text': 'Parent', 'templateRole': 'r.0'},
        {'parentUid': root, 'text': 'User moved this child', 'templateRole': 'r.1'},
    ])['created']
    baseline = deepcopy(generator._draft.document)
    moved = baseline['root']['children'].pop(1)
    baseline['root']['children'][0]['children'].append(moved)
    return profile, baseline, created[0]['nodeUid'], created[1]['nodeUid']


@pytest.mark.parametrize('patch', [{'text': 'Updated content'}, {'note': 'Updated note'}])
def test_implicit_content_update_preserves_unchanged_historical_template_relation(patch: dict) -> None:
    profile, baseline, _parent_uid, child_uid = _manually_reparented_template_source()
    original = deepcopy(baseline)
    tools = MindmapToolService(base_document=baseline, template_profile=profile, trusted_source=True, tag_catalog=[TAG])
    tools.update_nodes([{'nodeUid': child_uid, 'patch': patch}])
    child = tools._draft.document['root']['children'][0]['children'][0]['data']
    assert template_role_id(child, profile) == 'r.1'
    assert all(child[key] == value for key, value in patch.items())
    assert baseline == original
    artifact, _, _ = tools.complete_artifact(title='Updated', agent_key='native_mindmap', adapter_version='1', prompt_version='1')
    assert artifact['document']['root']['children'][0]['children'][0]['data'] == child


@pytest.mark.parametrize('requested_role', ['r.1', 'r.2'])
def test_explicit_role_still_checks_a_historical_relation(requested_role: str) -> None:
    profile, baseline, _parent_uid, child_uid = _manually_reparented_template_source()
    tools = MindmapToolService(base_document=baseline, template_profile=profile, trusted_source=True, tag_catalog=[TAG])
    original = deepcopy(tools._draft.document)
    with pytest.raises(MindmapArtifactError, match='父节点关系'):
        tools.update_nodes([{'nodeUid': child_uid, 'patch': {'text': 'New', 'templateRole': requested_role}}])
    assert tools._draft.document == original


def test_same_batch_parent_role_change_cannot_gain_a_historical_relation_exemption() -> None:
    profile, baseline, parent_uid, child_uid = _manually_reparented_template_source()
    tools = MindmapToolService(base_document=baseline, template_profile=profile, trusted_source=True, tag_catalog=[TAG])
    original = deepcopy(tools._draft.document)
    with pytest.raises(MindmapArtifactError, match='父节点关系'):
        tools.update_nodes([
            {'nodeUid': parent_uid, 'patch': {'templateRole': 'r.2'}},
            {'nodeUid': child_uid, 'patch': {'text': 'New child content'}},
        ])
    assert tools._draft.document == original
    assert tools._draft.operations == []


@pytest.mark.parametrize('change', ['move', 'parent_role'])
def test_current_turn_cannot_introduce_a_new_incompatible_template_relationship(change: str) -> None:
    template = detail()
    template['nodeTree']['children'].append({'data': {'uid': 'other-role', 'text': 'Other'}, 'children': []})
    profile = build_template_profile(template)
    tools = MindmapToolService(template_profile=profile, tag_catalog=[TAG])
    root = tools.start_document('New topic')['rootUid']
    nodes = tools.add_nodes([
        {'parentUid': root, 'text': 'A', 'clientRef': 'a', 'templateRole': 'r.0'},
        {'parentUid': root, 'text': 'B', 'templateRole': 'r.1'},
        {'parentUid': '@a', 'text': 'C', 'templateRole': 'r.0'},
    ])['created']
    baseline = deepcopy(tools._draft.document)
    with pytest.raises(MindmapArtifactError, match='父节点关系'):
        if change == 'move':
            tools.move_nodes([{'nodeUid': nodes[2]['nodeUid'], 'parentUid': nodes[1]['nodeUid']}])
        else:
            tools.update_nodes([{'nodeUid': nodes[0]['nodeUid'], 'patch': {'templateRole': 'r.1'}}])
    assert tools._draft.document == baseline


@pytest.mark.asyncio
async def test_create_persists_profile_and_idempotent_replay_does_not_refetch_template(monkeypatch: pytest.MonkeyPatch) -> None:
    model = request(agentKey='codex')
    database = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    manifest = SimpleNamespace(agent_key='codex', adapter_version='1', sdk_version='1', runtime_version='1',
                               intents={'create'}, input_types={'none'}, result_types=('artifact',))
    policy = SimpleNamespace(max_budget_usd=1, timeout_seconds=30, retention_days=30)
    getter = AsyncMock(return_value=detail())
    lookup = AsyncMock(return_value=None)
    stored = None

    async def add_job(_db: object, values: dict) -> SimpleNamespace:
        nonlocal stored
        stored = SimpleNamespace(**values, parent_job_id=None, retry_of_job_id=None, title=None,
                                 artifact_id=None, proposal_id=None, usage_json=None,
                                 error_code=None, error_message=None, completed_time=None)
        return stored

    monkeypatch.setattr(MindmapAiTemplateService, 'get_template', getter)
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_template_service.load_ai_tag_catalog', AsyncMock(return_value=[TAG]))
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.get_mindmap_agent_registry',
                        lambda: SimpleNamespace(get=lambda _key: SimpleNamespace(get_manifest=lambda: manifest)))
    monkeypatch.setattr(MindmapAiService, '_ensure_connector_available', AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(MindmapAiService, '_prepare_source_for_job', AsyncMock(return_value=(None, None, None, None, None)))
    monkeypatch.setattr(MindmapAiService, '_runtime_policy', lambda *_args: policy)
    monkeypatch.setattr(MindmapAiService, '_validate_job_policy', lambda *_args: 'test')
    monkeypatch.setattr(MindmapAiService, '_ensure_concurrency_available', AsyncMock())
    monkeypatch.setattr(MindmapAiTaskManager, 'schedule', Mock())
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiDao.get_job_by_idempotency', lookup)
    for method in ('add_session', 'add_event'):
        monkeypatch.setattr(f'module_mindmap.service.mindmap_ai_service.MindmapAiDao.{method}', AsyncMock())
    monkeypatch.setattr('module_mindmap.service.mindmap_ai_service.MindmapAiDao.add_job', add_job)
    first = await MindmapAiService.create_job(database, model, 3, 'template-create')
    frozen = json.loads(stored.request_json)
    assert read_template_profile(frozen)['roles']['r.0']['tags'] == [
        {'tagId': 7, 'text': 'Important', 'placement': 'bottom', 'align': 'left'},
    ]
    assert frozen['attachments'][0]['templateSource'] == {'mindmapId': 9, 'contentRevision': 4}
    lookup.return_value = stored
    getter.side_effect = AssertionError('A committed turn must reuse its immutable snapshot')
    replay = await MindmapAiService.create_job(database, request(agentKey='codex'), 3, 'template-create')
    assert replay.id == first.id
    getter.assert_awaited_once()
    assert json.loads(stored.request_json) == frozen
