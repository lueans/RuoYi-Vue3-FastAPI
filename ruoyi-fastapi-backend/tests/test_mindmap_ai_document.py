import json

import pytest

from module_mindmap.ai.document import (
    AI_MAX_FILE_BYTES,
    MindmapArtifactError,
    build_smm_artifact,
    compute_document_hash,
    normalize_ai_editable_source_document,
    validate_smm_artifact,
)
from module_mindmap.ai.tool_contract import MindmapToolService
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel

SMM_VERSION = 2
TWO_NODES = 2
THREE_ITEMS = 3
TASK_NODE_LIMIT = 100
AI_JOB_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


def _document() -> dict:
    return {
        'root': {
            'data': {'uid': 'root', 'text': '支付系统', 'isActive': True},
            'children': [
                {'data': {'uid': 'child', 'text': '支付成功'}, 'children': []},
            ],
        },
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': {'transform': {'scale': 2}},
        'documentData': {},
    }


def test_build_and_validate_smm_v2_artifact() -> None:
    artifact, summary = build_smm_artifact(
        _document(),
        title='支付系统',
        agent_key='native_mindmap',
        adapter_version='1.0.0',
        prompt_version='mindmap-create-1',
        artifact_id='artifact-1',
    )

    assert artifact['format'] == 'ruoyi-mindmap'
    assert artifact['formatSchemaVersion'] == SMM_VERSION
    assert artifact['manifest']['artifactId'] == 'artifact-1'
    assert artifact['manifest']['documentHash'] == compute_document_hash(artifact['document'])
    assert artifact['document']['view'] is None
    assert 'isActive' not in artifact['document']['root']['data']
    assert summary == {'nodeCount': 2, 'treeDepth': 2, 'bytes': summary['bytes']}

    restored, restored_summary = validate_smm_artifact(json.loads(json.dumps(artifact)))
    assert restored['document'] == artifact['document']
    assert restored_summary['nodeCount'] == TWO_NODES


def test_artifact_rejects_hash_tampering() -> None:
    artifact, _summary = build_smm_artifact(
        _document(),
        title='支付系统',
        agent_key='native_mindmap',
        adapter_version='1.0.0',
        prompt_version='mindmap-create-1',
    )
    artifact['document']['root']['data']['text'] = '被篡改'

    with pytest.raises(MindmapArtifactError, match='哈希不匹配'):
        validate_smm_artifact(artifact)


def test_external_artifact_hash_is_verified_before_platform_normalization() -> None:
    artifact, _summary = build_smm_artifact(
        _document(),
        title='支付系统',
        agent_key='native_mindmap',
        adapter_version='1.0.0',
        prompt_version='mindmap-create-1',
    )
    source_document = artifact['document']
    source_document['root']['data'].update({
        'text': '<b>支付系统</b>',
        'onClick': 'untrusted()',
    })
    artifact['manifest']['documentHash'] = compute_document_hash(source_document)

    restored, _summary = validate_smm_artifact(artifact)

    assert restored['document']['root']['data']['text'] == '支付系统'
    assert 'onClick' not in restored['document']['root']['data']
    assert restored['manifest']['documentHash'] == compute_document_hash(restored['document'])


def test_artifact_validation_enforces_full_envelope_size() -> None:
    artifact, _summary = build_smm_artifact(
        _document(),
        title='支付系统',
        agent_key='native_mindmap',
        adapter_version='1.0.0',
        prompt_version='mindmap-create-1',
    )
    artifact['untrustedPadding'] = 'x' * AI_MAX_FILE_BYTES

    with pytest.raises(MindmapArtifactError) as too_large:
        validate_smm_artifact(artifact)

    assert too_large.value.code == 'AI_INPUT_TOO_LARGE'


def test_editable_source_normalization_accepts_blank_nodes_deterministically() -> None:
    document = _document()
    document['root']['data']['text'] = '  <b></b>\x00  '
    document['root']['data']['note'] = ' <i></i> '
    document['root']['data']['hyperlink'] = '   '

    normalized, summary = normalize_ai_editable_source_document(document)

    assert normalized['root']['data']['text'] == '未命名节点'
    assert 'note' not in normalized['root']['data']
    assert 'hyperlink' not in normalized['root']['data']
    assert normalized['view'] is None
    assert summary['nodeCount'] == TWO_NODES
    with pytest.raises(MindmapArtifactError, match='不能为空'):
        build_smm_artifact(
            document,
            title='严格产物仍拒绝空节点',
            agent_key='native_mindmap',
            adapter_version='1.0.0',
            prompt_version='test-1',
        )


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        ('hyperlink', 'javascript:alert(1)', '链接仅支持'),
        ('image', 'data:image/png;base64,AAAA', '不能生成图片'),
        ('onClick', 'alert(1)', '事件字段'),
    ],
)
def test_artifact_rejects_unsafe_agent_content(field: str, value: str, message: str) -> None:
    document = _document()
    document['root']['data'][field] = value
    with pytest.raises(MindmapArtifactError, match=message):
        build_smm_artifact(
            document,
            title='支付系统',
            agent_key='native_mindmap',
            adapter_version='1.0.0',
            prompt_version='mindmap-create-1',
        )


def test_draft_tool_contract_builds_and_freezes_artifact() -> None:
    tools = MindmapToolService()
    root = tools.start_document('订单系统')
    created = tools.add_nodes([
        {'clientRef': 'a', 'parentUid': root['rootUid'], 'text': '创建订单'},
        {'clientRef': 'b', 'parentUid': root['rootUid'], 'text': '取消订单'},
    ])
    tools.update_nodes([{
        'nodeUid': created['created'][0]['nodeUid'],
        'patch': {'note': '校验库存'},
    }])
    summary = tools.validate_draft()
    artifact, final_summary, operations = tools.complete_artifact(
        title='订单系统',
        agent_key='native_mindmap',
        adapter_version='1.0.0',
        prompt_version='mindmap-create-1',
    )

    assert summary['nodeCount'] == THREE_ITEMS
    assert final_summary['nodeCount'] == THREE_ITEMS
    assert len(operations) == THREE_ITEMS
    assert artifact['manifest']['validation']['status'] == 'passed'
    with pytest.raises(MindmapArtifactError, match='已经完成'):
        tools.add_nodes([{'parentUid': root['rootUid'], 'text': '迟到节点'}])


def test_draft_tool_contract_builds_replayable_stream_deltas() -> None:
    tools = MindmapToolService()
    cursor = tools.operation_cursor()
    root = tools.start_document('实时订单脑图')
    started = tools.build_stream_delta(after_cursor=cursor, tool_name='start_document')

    assert started['operationCursor'] == 0
    assert started['initialState']['root']['data']['uid'] == root['rootUid']
    assert started['summary'] == {'nodeCount': 1, 'treeDepth': 1}

    cursor = tools.operation_cursor()
    created = tools.add_nodes([{
        'parentUid': root['rootUid'],
        'text': '创建订单',
    }])
    delta = tools.build_stream_delta(after_cursor=cursor, tool_name='add_nodes')

    assert delta['operationCursor'] == 1
    assert delta['operations'] == [{
        'type': 'create_node',
        'nodeUid': created['created'][0]['nodeUid'],
        'payload': {
            'parentUid': root['rootUid'],
            'index': 0,
            'data': {
                'uid': created['created'][0]['nodeUid'],
                'text': '创建订单',
                'expand': True,
            },
        },
    }]
    assert delta['summary'] == {'nodeCount': 2, 'treeDepth': 2}


def test_add_nodes_resolves_prior_client_refs_within_one_atomic_batch() -> None:
    tools = MindmapToolService(intent='create')
    root = tools.start_document('订单系统')

    created = tools.add_nodes([
        {
            'clientRef': 'case',
            'parentUid': root['rootUid'],
            'text': '创建订单成功',
        },
        {
            'clientRef': 'precondition',
            'parentUid': '@case',
            'text': '用户已登录',
        },
        {
            'clientRef': 'action',
            'parentUid': '@precondition',
            'text': '提交有效订单',
        },
        {
            'clientRef': 'expected',
            'parentUid': '@action',
            'text': '订单创建成功',
        },
    ])

    uid_by_ref = {
        item['clientRef']: item['nodeUid']
        for item in created['created']
    }
    projection = tools.read_projection()
    case = projection['root']['children'][0]
    precondition = case['children'][0]
    action = precondition['children'][0]
    expected = action['children'][0]
    assert case['data']['uid'] == uid_by_ref['case']
    assert precondition['data']['uid'] == uid_by_ref['precondition']
    assert action['data']['uid'] == uid_by_ref['action']
    assert expected['data']['uid'] == uid_by_ref['expected']


@pytest.mark.parametrize(
    'nodes',
    [
        [{'clientRef': 'child', 'parentUid': '@missing', 'text': '未知引用'}],
        [
            {'clientRef': 'child', 'parentUid': '@parent', 'text': '后向引用'},
            {'clientRef': 'parent', 'parentUid': 'root', 'text': '后创建的父节点'},
        ],
        [{'clientRef': 'self', 'parentUid': '@self', 'text': '自引用'}],
        [
            {'clientRef': 'duplicate', 'parentUid': 'root', 'text': '第一个'},
            {'clientRef': 'duplicate', 'parentUid': 'root', 'text': '第二个'},
        ],
    ],
    ids=['unknown', 'forward', 'self', 'duplicate'],
)
def test_add_nodes_rejects_invalid_client_refs_atomically(nodes: list[dict]) -> None:
    tools = MindmapToolService(base_document=_document(), trusted_source=True)
    before = tools.read_projection()

    with pytest.raises(MindmapArtifactError, match='clientRef'):
        tools.add_nodes(nodes)

    assert tools.read_projection() == before
    assert tools.operation_cursor() == 0


def test_add_nodes_client_refs_preserve_scope_and_roll_back_on_escape() -> None:
    document = _document()
    document['root']['children'].append({
        'data': {'uid': 'other', 'text': '退款'},
        'children': [],
    })
    tools = MindmapToolService(
        base_document=document,
        scope={'type': 'branch', 'rootUid': 'child'},
        trusted_source=True,
    )
    created = tools.add_nodes([
        {'clientRef': 'safe', 'parentUid': 'child', 'text': '授权内父节点'},
        {'clientRef': 'nested', 'parentUid': '@safe', 'text': '授权内子节点'},
    ])
    assert len(created['created']) == 2  # noqa: PLR2004
    before_escape = tools.read_projection()
    before_cursor = tools.operation_cursor()

    with pytest.raises(MindmapArtifactError, match='超出本次 AI 授权范围'):
        tools.add_nodes([
            {'clientRef': 'would-rollback', 'parentUid': 'child', 'text': '应回滚'},
            {'parentUid': 'other', 'text': '越权'},
        ])

    assert tools.read_projection() == before_escape
    assert tools.operation_cursor() == before_cursor


def test_source_task_node_budget_rejects_overflow_batch_atomically() -> None:
    tools = MindmapToolService(
        base_document=_document(),
        trusted_source=True,
        max_nodes=TASK_NODE_LIMIT,
        max_depth=6,
    )
    first_batch = [
        {'parentUid': 'root', 'text': f'新增用例 {index}'}
        for index in range(99)
    ]
    tools.add_nodes(first_batch)
    before_overflow = tools.read_projection()
    before_cursor = tools.operation_cursor()

    with pytest.raises(
        MindmapArtifactError,
        match='剩余节点预算 1，本批新增 3',
    ) as exceeded:
        tools.add_nodes([
            {'parentUid': 'root', 'text': f'溢出用例 {index}'}
            for index in range(3)
        ])

    assert exceeded.value.code == 'AI_BUDGET_EXCEEDED'
    assert tools.read_projection() == before_overflow
    assert tools.operation_cursor() == before_cursor == TASK_NODE_LIMIT - 1

    tools.add_nodes([{'parentUid': 'root', 'text': '第 100 个新增节点'}])
    _artifact, _summary, operations = tools.complete_artifact(
        title='支付系统',
        agent_key='claude',
        adapter_version='test',
        prompt_version='test',
    )
    assert sum(item['type'] == 'create_node' for item in operations) == TASK_NODE_LIMIT


def test_add_nodes_rejects_task_depth_overflow_atomically() -> None:
    tools = MindmapToolService(
        base_document=_document(),
        trusted_source=True,
        max_nodes=TASK_NODE_LIMIT,
        max_depth=2,
    )
    before = tools.read_projection()

    with pytest.raises(MindmapArtifactError, match='当前 3 层，上限 2 层') as exceeded:
        tools.add_nodes([{'parentUid': 'child', 'text': '过深节点'}])

    assert exceeded.value.code == 'AI_BUDGET_EXCEEDED'
    assert tools.read_projection() == before
    assert tools.operation_cursor() == 0


@pytest.mark.parametrize(('kwargs', 'message'), [
    ({'max_nodes': 0}, '节点上限无效'),
    ({'max_depth': 0}, '层级上限无效'),
])
def test_invalid_task_structure_budget_is_not_output_invalid(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(MindmapArtifactError, match=message) as invalid:
        MindmapToolService(**kwargs)

    assert invalid.value.code == 'AI_BUDGET_EXCEEDED'


def test_generated_artifact_size_failure_is_budget_not_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = MindmapToolService()
    tools.start_document('支付系统')

    def reject_size(*_args: object, **_kwargs: object) -> None:
        raise MindmapArtifactError(
            'AI 脑图文件超过限制',
            code='AI_INPUT_TOO_LARGE',
        )

    monkeypatch.setattr(
        'module_mindmap.ai.tool_contract.build_smm_artifact',
        reject_size,
    )

    with pytest.raises(MindmapArtifactError) as exceeded:
        tools.complete_artifact(
            title='支付系统',
            agent_key='codex',
            adapter_version='test',
            prompt_version='test',
        )

    assert exceeded.value.code == 'AI_BUDGET_EXCEEDED'
    assert str(exceeded.value) == 'AI 脑图文件超过限制'


def test_generated_draft_byte_overflow_is_budget_and_atomic() -> None:
    tools = MindmapToolService(max_nodes=200, max_depth=6)
    root_uid = tools.start_document('支付系统')['rootUid']
    before = tools.read_projection()

    with pytest.raises(MindmapArtifactError) as exceeded:
        tools.add_nodes([
            {
                'parentUid': root_uid,
                'text': f'大字段节点 {index}',
                'note': 'x' * 20_000,
            }
            for index in range(100)
        ])

    assert exceeded.value.code == 'AI_BUDGET_EXCEEDED'
    assert '规范文档不能超过' in str(exceeded.value)
    assert tools.read_projection() == before
    assert tools.operation_cursor() == 0


def test_move_nodes_rejects_task_depth_overflow_atomically() -> None:
    document = _document()
    document['root']['children'].append({
        'data': {'uid': 'other', 'text': '退款'},
        'children': [],
    })
    tools = MindmapToolService(
        base_document=document,
        trusted_source=True,
        max_nodes=TASK_NODE_LIMIT,
        max_depth=2,
    )
    before = tools.read_projection()

    with pytest.raises(MindmapArtifactError, match='当前 3 层，上限 2 层') as exceeded:
        tools.move_nodes([{'nodeUid': 'other', 'parentUid': 'child'}])

    assert exceeded.value.code == 'AI_BUDGET_EXCEEDED'
    assert tools.read_projection() == before
    assert tools.operation_cursor() == 0


def test_draft_move_rejects_cycle_without_mutating_document() -> None:
    tools = MindmapToolService()
    root = tools.start_document('根')
    first = tools.add_nodes([{'parentUid': root['rootUid'], 'text': '一级'}])['created'][0]['nodeUid']
    second = tools.add_nodes([{'parentUid': first, 'text': '二级'}])['created'][0]['nodeUid']
    before = tools.read_projection()

    with pytest.raises(MindmapArtifactError, match='形成循环'):
        tools.move_nodes([{'nodeUid': first, 'parentUid': second}])
    assert tools.read_projection() == before


def test_trusted_source_keeps_assets_out_of_projection_and_preserves_artifact() -> None:
    document = _document()
    document['root']['data'].update({
        'image': 'data:image/png;base64,AAAA',
        'imageTitle': '架构图',
        'richText': True,
        'pluginSecret': '不能发送给 Agent',
    })
    document['documentData'] = {'privatePluginState': '不能发送给 Agent'}
    tools = MindmapToolService(base_document=document, trusted_source=True)

    projection = tools.read_projection()
    assert 'image' not in projection['root']['data']
    assert 'richText' not in projection['root']['data']
    assert 'pluginSecret' not in projection['root']['data']
    assert projection['documentData'] == {}

    tools.update_nodes([{'nodeUid': 'child', 'patch': {'text': '支付完成'}}])
    artifact, _summary, _operations = tools.complete_artifact(
        title='支付系统',
        agent_key='native_mindmap',
        adapter_version='1.0.0',
        prompt_version='mindmap-edit-1',
    )
    assert artifact['document']['root']['data']['image'].startswith('data:image/png')
    assert artifact['document']['root']['data']['richText'] is True
    assert artifact['document']['root']['data']['pluginSecret'] == '不能发送给 Agent'
    assert artifact['document']['view'] == {'transform': {'scale': 2}}
    assert artifact['document']['documentData'] == {'privatePluginState': '不能发送给 Agent'}
    validate_smm_artifact(artifact)


def test_branch_scope_blocks_outside_mutation_and_meta_changes() -> None:
    document = _document()
    document['root']['children'].append({
        'data': {'uid': 'other', 'text': '退款'},
        'children': [],
    })
    tools = MindmapToolService(
        base_document=document,
        scope={'type': 'branch', 'rootUid': 'child'},
        trusted_source=True,
    )

    assert tools.read_projection()['root']['data']['uid'] == 'child'
    with pytest.raises(MindmapArtifactError, match='超出本次 AI 授权范围'):
        tools.update_nodes([{'nodeUid': 'other', 'patch': {'text': '越权'}}])
    with pytest.raises(MindmapArtifactError, match='局部授权范围'):
        tools.set_document_meta(title='越权标题')

    created = tools.add_nodes([{'parentUid': 'child', 'text': '新检查'}])
    new_uid = created['created'][0]['nodeUid']
    tools.update_nodes([{'nodeUid': new_uid, 'patch': {'note': '授权内'}}])


def test_selected_node_scope_collapses_ancestor_descendant_overlap() -> None:
    document = _document()
    document['root']['children'][0]['children'] = [{
        'data': {'uid': 'grandchild', 'text': '支付结果'},
        'children': [],
    }]
    tools = MindmapToolService(
        base_document=document,
        scope={
            'type': 'selectedNodes',
            'nodeUids': ['grandchild', 'child'],
        },
        trusted_source=True,
    )

    projection = tools.read_projection()

    assert projection['root']['data']['uid'] == 'child'
    assert projection['root']['children'][0]['data']['uid'] == 'grandchild'
    assert projection['authorizedScope']['nodeUids'] == ['child']
    assert tools.authorized_scope_summary()['nodeCount'] == 2  # noqa: PLR2004


def test_selected_node_projection_recollapses_roots_after_move() -> None:
    document = _document()
    document['root']['children'].append({
        'data': {'uid': 'other', 'text': '退款'},
        'children': [],
    })
    tools = MindmapToolService(
        base_document=document,
        scope={
            'type': 'selectedNodes',
            'nodeUids': ['child', 'other'],
        },
        trusted_source=True,
    )

    tools.move_nodes([{'nodeUid': 'other', 'parentUid': 'child'}])
    projection = tools.read_projection()
    projected_uids: list[str] = []
    pending = [projection['root']]
    while pending:
        node = pending.pop()
        projected_uids.append(node['data']['uid'])
        pending.extend(node.get('children') or [])

    assert projection['root']['data']['uid'] == 'child'
    assert projected_uids.count('other') == 1
    assert tools.authorized_scope_summary()['nodeCount'] == 2  # noqa: PLR2004


def test_readonly_compatible_source_can_generate_independent_file() -> None:
    request = MindmapAiJobCreateModel.model_validate({
        'agentKey': 'codex',
        'intent': 'expand',
        'prompt': '生成一份独立扩展版本',
        'source': {'type': 'cloud_document', 'mindmapId': 7},
        'target': 'file',
    })

    assert request.target == 'file'


def test_proposal_requires_an_existing_document_source() -> None:
    with pytest.raises(ValueError, match='现有本地或云端脑图'):
        MindmapAiJobCreateModel.model_validate({
            'agentKey': 'codex',
            'intent': 'create',
            'prompt': '创建脑图',
            'source': {'type': 'none'},
            'target': 'proposal',
        })
