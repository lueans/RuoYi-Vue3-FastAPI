"""Submitted context chips follow each persisted turn, not today's canvas."""

import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from module_mindmap.ai.message_context import (
    freeze_user_message_context,
    user_message_attachments,
    user_message_context,
)
from module_mindmap.entity.vo.mindmap_ai_vo import MindmapAiJobCreateModel
from module_mindmap.service.mindmap_ai_service import MindmapAiDao, MindmapAiService, _stable_create_fingerprint


def document(label: str = '发送时的登录节点') -> dict:
    return {'root': {'data': {'uid': 'root', 'text': '不应返回的根正文', 'note': '私密备注'}, 'children': [
        {'data': {'uid': 'login', 'text': label, 'note': '不应回显的节点备注'}, 'children': []},
        {'data': {'uid': 'sms', 'text': '短信验证码', 'hyperlink': 'https://private.invalid'}, 'children': []},
        {'data': {'uid': 'private', 'text': '未授权旁支正文'}, 'children': []},
    ]}}


def payload(scope: dict | None = None, **source: object) -> dict:
    return {'prompt': '完善用例', 'source': {
        'type': 'cloud_document', 'mindmapId': 130, 'document': document(),
        'scope': scope or {'type': 'document'}, **source,
    }}


@pytest.mark.parametrize(('scope', 'expected'), [
    ({'type': 'document'}, []),
    ({'type': 'branch', 'rootUid': 'login'}, [{'uid': 'login', 'label': '发送时的登录节点'}]),
    ({'type': 'selectedNodes', 'nodeUids': ['sms', 'login', 'sms']}, [
        {'uid': 'sms', 'label': '短信验证码'}, {'uid': 'login', 'label': '发送时的登录节点'},
    ]),
])
def test_saved_scope_controls_exact_selected_labels_and_order(scope: dict, expected: list) -> None:
    result = user_message_context(payload(scope))
    assert result == {'sourceMode': 'current', 'scopeType': scope['type'], 'contextNodes': expected}
    encoded = json.dumps(result, ensure_ascii=False)
    assert '私密备注' not in encoded and '不应回显' not in encoded
    assert '未授权旁支' not in encoded and 'private.invalid' not in encoded
    assert '不应返回的根正文' not in encoded


@pytest.mark.parametrize('source_type', ['local_snapshot', 'cloud_document', 'uploaded_artifact'])
def test_context_frozen_at_submission_survives_later_rebase_and_renamed_nodes(source_type: str) -> None:
    original = payload({'type': 'branch', 'rootUid': 'login'}, type=source_type)
    saved = freeze_user_message_context(original)
    saved['source'] = {**saved['source'], 'document': document('执行时节点已改名')}
    frozen_again = freeze_user_message_context(saved)
    assert user_message_context(frozen_again)['contextNodes'] == [{'uid': 'login', 'label': '发送时的登录节点'}]
    assert '_userMessageContext' not in original
    assert original['source']['document']['root']['children'][0]['data']['text'] == '发送时的登录节点'


def test_frozen_new_source_does_not_become_file_after_queued_artifact_rebase() -> None:
    saved = freeze_user_message_context({'source': {'type': 'none', 'scope': {'type': 'document'}}})
    saved['source'] = {'type': 'uploaded_artifact', 'scope': {'type': 'document'}, 'document': document()}
    assert user_message_context(saved) == {'sourceMode': 'new', 'scopeType': 'document', 'contextNodes': []}


@pytest.mark.parametrize('bad_source', [
    None, {}, {'type': 'unknown'}, {'type': 'cloud_document'},
    {'type': 'cloud_document', 'scope': None}, {'type': 'cloud_document', 'scope': {'type': 'bogus'}},
    {'type': 'cloud_document', 'scope': {'type': 'branch'}},
    {'type': 'cloud_document', 'scope': {'type': 'selectedNodes', 'nodeUids': []}},
])
def test_legacy_unknown_or_missing_scope_never_fakes_entire_map(bad_source: object) -> None:
    assert user_message_context({'source': bad_source}) is None


def test_known_selection_without_snapshot_keeps_uids_and_count_not_document_fallback() -> None:
    request = payload({'type': 'selectedNodes', 'nodeUids': ['gone', 'login']}, document=None)
    assert user_message_context(request) == {'sourceMode': 'current', 'scopeType': 'selectedNodes', 'contextNodes': [
        {'uid': 'gone', 'label': ''}, {'uid': 'login', 'label': ''},
    ]}


@pytest.mark.parametrize('snapshot_key', ['baselineDocument', 'artifact'])
def test_legacy_snapshot_fallback_is_read_only_and_scope_filtered(snapshot_key: str) -> None:
    snapshot = document()
    request = payload({'type': 'branch', 'rootUid': 'sms'}, document=None,
        **{snapshot_key: {'document': snapshot} if snapshot_key == 'artifact' else snapshot})
    before = copy.deepcopy(request)
    assert user_message_context(request)['contextNodes'] == [{'uid': 'sms', 'label': '短信验证码'}]
    assert request == before


def test_rich_text_labels_are_plain_bounded_and_stable_on_repeated_reads() -> None:
    request = payload({'type': 'branch', 'rootUid': 'login'}, document=document(
        '<p><strong>登录</strong><script>不应展示</script> &amp; &lt;button&gt;</p>\x00',
    ))
    frozen = freeze_user_message_context(request)
    expected = [{'uid': 'login', 'label': '登录 & <button>'}]
    assert user_message_context(request)['contextNodes'] == expected
    assert user_message_context(frozen)['contextNodes'] == expected
    assert user_message_context(freeze_user_message_context(frozen))['contextNodes'] == expected
    assert len(user_message_context(payload({'type': 'branch', 'rootUid': 'login'}, document=document('x' * 10_000)))['contextNodes'][0]['label']) == 512


def test_server_receipt_cannot_be_injected_as_client_context_or_change_fingerprint() -> None:
    request = payload({'type': 'branch', 'rootUid': 'login'})
    clean = MindmapAiJobCreateModel.model_validate(request)
    injected = MindmapAiJobCreateModel.model_validate({**request, '_userMessageContext': {
        'sourceMode': 'current', 'scopeType': 'document', 'contextNodes': [],
    }, 'context': {'scopeType': 'document'}, 'aiContextNodes': [{'uid': 'private', 'label': '伪造'}]})
    assert _stable_create_fingerprint(clean) == _stable_create_fingerprint(injected)
    frozen = freeze_user_message_context(injected.model_dump(by_alias=True, exclude_none=True))
    assert user_message_context(frozen)['contextNodes'] == [{'uid': 'login', 'label': '发送时的登录节点'}]


@pytest.mark.asyncio
async def test_timeline_exposes_each_saved_context_and_attachment_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from module_mindmap.service import mindmap_ai_service as service

    now = datetime.now()
    session = SimpleNamespace(id='session', title='会话', status='active', current_agent_key='codex',
        created_time=now, update_time=now, expires_time=now + timedelta(days=1))
    first = freeze_user_message_context(payload({'type': 'branch', 'rootUid': 'login'}))
    first['source']['document'] = document('执行结束后的名称')
    first['attachments'] = [{'id': 'file', 'name': '需求.md', 'size': 3, 'mediaType': 'text/markdown', 'text': '私密附件正文'}]
    second = payload({'type': 'selectedNodes', 'nodeUids': ['sms', 'login']})
    second['attachments'] = [{
        'id': 'legacy', 'name': '旧附件.txt', 'size': 3, 'mediaType': 'text/plain',
        'parsing': {'status': 'parsed', 'characterCount': 1000, 'parsedAt': 'invented'},
        'privateContent': '不应泄露的遗留正文',
    }, {'name': '无效元数据'}]
    jobs = [SimpleNamespace(id=str(index), created_time=now, request_json=json.dumps(request))
        for index, request in enumerate([first, second, {'prompt': '旧任务', 'source': {}}])]
    monkeypatch.setattr(MindmapAiDao, 'get_session', AsyncMock(return_value=session))
    monkeypatch.setattr(MindmapAiDao, 'list_jobs_for_session', AsyncMock(return_value=jobs))
    monkeypatch.setattr(MindmapAiDao, 'list_events', AsyncMock(return_value=[]))
    monkeypatch.setattr(service, '_job_model', lambda job: SimpleNamespace(model_dump=lambda **_: {'id': job.id}))
    timeline = await MindmapAiService.get_session_timeline(object(), 'session', 7)
    turns = timeline['turns']
    assert turns[0]['userMessage']['context']['contextNodes'] == [{'uid': 'login', 'label': '发送时的登录节点'}]
    assert turns[1]['userMessage']['context']['scopeType'] == 'selectedNodes'
    assert len(turns[1]['userMessage']['context']['contextNodes']) == 2
    assert turns[2]['userMessage']['context'] is None
    assert turns[0]['userMessage']['attachments'] == [{
        'id': 'file', 'name': '需求.md', 'size': 3, 'mediaType': 'text/markdown',
        'parsing': {'status': 'parsed', 'characterCount': 6},
    }]
    assert turns[1]['userMessage']['attachments'] == [{
        'id': 'legacy', 'name': '旧附件.txt', 'size': 3, 'mediaType': 'text/plain',
        'parsing': {'status': 'unknown'},
    }]
    assert turns[2]['userMessage']['attachments'] == []
    serialized = json.dumps(timeline, ensure_ascii=False, default=str)
    assert '私密附件正文' not in serialized and '未授权旁支' not in serialized and '私密备注' not in serialized
    assert '执行结束后的名称' not in serialized
    assert '不应泄露的遗留正文' not in serialized and 'parsedAt' not in serialized


def attachment(**changes: object) -> dict:
    return {
        'id': 'file', 'name': '需求.md', 'size': 10,
        'mediaType': 'text/markdown', 'text': '附件正文', **changes,
    }


@pytest.mark.parametrize('text', ['参考正文', 'A😀𠮷é', 'e\u0301', '文\n本', 'x' * 50_000])
def test_attachment_receipt_counts_saved_unicode_code_points_without_text(text: str) -> None:
    request = {'attachments': [attachment(text=text)]}
    before = copy.deepcopy(request)
    assert user_message_attachments(request) == [{
        'id': 'file', 'name': '需求.md', 'size': 10, 'mediaType': 'text/markdown',
        'parsing': {'status': 'parsed', 'characterCount': len(text)},
    }]
    assert request == before


@pytest.mark.parametrize('changes', [
    {'text': None}, {'text': ''}, {'text': ' \n\t'}, {'text': 10},
    {'text': {'secret': '正文'}}, {'text': 'x' * 50_001},
])
def test_attachment_receipt_invalid_body_keeps_metadata_with_unknown_parsing(changes: dict) -> None:
    receipt = user_message_attachments({'attachments': [attachment(**changes)]})
    assert receipt == [{
        'id': 'file', 'name': '需求.md', 'size': 10, 'mediaType': 'text/markdown',
        'parsing': {'status': 'unknown'},
    }]


def test_attachment_receipt_missing_legacy_text_never_trusts_claimed_parser_result() -> None:
    legacy = attachment()
    legacy.pop('text')
    legacy['parsing'] = {'status': 'parsed', 'characterCount': 9999, 'parsedAt': 'invented', 'pages': 99}
    modern = attachment(parsing={'status': 'failed', 'characterCount': 9999}, content='extra private body')
    receipts = user_message_attachments({'attachments': [legacy, modern]})
    assert [item['parsing'] for item in receipts] == [
        {'status': 'unknown'}, {'status': 'parsed', 'characterCount': 4},
    ]
    assert all(set(item) == {'id', 'name', 'size', 'mediaType', 'parsing'} for item in receipts)
    encoded = json.dumps(receipts, ensure_ascii=False)
    assert '附件正文' not in encoded and 'extra private body' not in encoded
    assert 'parsedAt' not in encoded and 'pages' not in encoded


@pytest.mark.parametrize('payload', [None, [], {}, {'attachments': None}, {'attachments': {}}])
def test_attachment_receipt_absent_or_invalid_collection_is_empty(payload: object) -> None:
    assert user_message_attachments(payload) == []


def test_attachment_receipt_skips_invalid_metadata_and_bounds_legacy_collection() -> None:
    assert user_message_attachments({'attachments': [
        None, {}, attachment(size=True), attachment(name=' '), attachment(),
    ]}) == user_message_attachments({'attachments': [attachment()]})
    files = [attachment(id=str(index)) for index in range(8)]
    assert [item['id'] for item in user_message_attachments({'attachments': files})] == ['0', '1', '2', '3', '4']
