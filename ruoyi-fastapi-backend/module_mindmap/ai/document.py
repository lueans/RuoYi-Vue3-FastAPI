"""SMM v2 artifact 的规范化、哈希与安全校验。"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from urllib.parse import urlparse

import rfc8785

from module_mindmap.service.simple_mind_document_codec import (
    TRANSIENT_KEYS,
    SimpleMindDocumentCodec,
    clone_json_value,
    validate_mindmap_tree,
)

SMM_FORMAT = 'ruoyi-mindmap'
SMM_FORMAT_SCHEMA_VERSION = 2
SMM_HASH_PREFIX = 'mmf2:sha256:'
SMM_ENGINE_NAME = 'simple-mind-map'

AI_MAX_NODE_COUNT = 2_000
AI_MAX_TREE_DEPTH = 32
AI_MAX_DOCUMENT_BYTES = 1_800_000
AI_MAX_FILE_BYTES = 2_000_000
AI_MAX_NODE_TEXT_LENGTH = 10_000
AI_MAX_NOTE_LENGTH = 20_000
AI_BLANK_SOURCE_NODE_TEXT = '未命名节点'


class AiMindmapLayout(str, Enum):
    MIND_MAP = 'mindMap'
    LOGICAL_STRUCTURE = 'logicalStructure'
    ORGANIZATION_STRUCTURE = 'organizationStructure'
    CATALOG_ORGANIZATION = 'catalogOrganization'
    TIMELINE = 'timeline'
    TIMELINE_2 = 'timeline2'
    VERTICAL_TIMELINE = 'verticalTimeline'
    VERTICAL_TIMELINE_2 = 'verticalTimeline2'
    VERTICAL_TIMELINE_3 = 'verticalTimeline3'
    FISHBONE = 'fishbone'
    FISHBONE_2 = 'fishbone2'
    RIGHT_FISHBONE = 'rightFishbone'
    RIGHT_FISHBONE_2 = 'rightFishbone2'
    LOGICAL_STRUCTURE_LEFT = 'logicalStructureLeft'


AI_ALLOWED_LAYOUTS = frozenset(layout.value for layout in AiMindmapLayout)
AI_ALLOWED_LINK_SCHEMES = frozenset({'http', 'https', 'mailto'})
AI_FORBIDDEN_CONTENT_KEYS = frozenset({
    'image',
    'imageTitle',
    'imageSize',
    'attachmentUrl',
    'attachmentName',
    'imgMap',
})
AI_PROJECTION_DATA_KEYS = frozenset({
    'uid',
    'text',
    'note',
    'hyperlink',
    'tag',
})
_CONTROL_CHARACTER_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_HTML_PATTERN = re.compile(r'<[^>]*>')


class MindmapArtifactError(ValueError):
    """可安全暴露给接口层的 artifact 校验错误。"""

    def __init__(self, message: str, *, code: str = 'AI_OUTPUT_INVALID') -> None:
        super().__init__(message)
        self.code = code


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def canonical_json_bytes(value: Any) -> bytes:
    """按 RFC 8785 生成跨 Python/浏览器稳定的 JSON 字节。"""
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as exc:
        raise MindmapArtifactError('脑图包含无法序列化的字段') from exc


def compute_document_hash(document: dict[str, Any]) -> str:
    return f'{SMM_HASH_PREFIX}{hashlib.sha256(canonical_json_bytes(document)).hexdigest()}'


def document_from_mindmap_detail(detail: Any) -> dict[str, Any]:
    """Map a detail VO to an editor document without normalizing its content.

    Preserve nullable metadata, blank nodes and view state: callers choose
    their existing source/projection policy and retain permission checks.
    This mapping, like an inline envelope, does not copy the referenced data.
    """
    return {
        'root': getattr(detail, 'node_tree', None),
        'layout': getattr(detail, 'layout', None),
        'theme': getattr(detail, 'theme', None),
        'view': getattr(detail, 'view_data', None),
        'documentData': getattr(detail, 'document_data', None),
    }


def _clean_text(value: Any, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise MindmapArtifactError(f'{label}必须是字符串')
    text = _CONTROL_CHARACTER_PATTERN.sub('', value).strip()
    if not text:
        raise MindmapArtifactError(f'{label}不能为空')
    if len(text) > max_length:
        raise MindmapArtifactError(f'{label}不能超过{max_length}个字符')
    text = _HTML_PATTERN.sub('', text).strip()
    if not text:
        raise MindmapArtifactError(f'{label}不能为空')
    return text


def _normalize_link(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MindmapArtifactError('脑图链接必须是非空字符串')
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in AI_ALLOWED_LINK_SCHEMES:
        raise MindmapArtifactError('脑图链接仅支持 http、https 或 mailto 协议')
    return normalized


def _sanitize_ai_tree(  # noqa: PLR0912
    root: dict[str, Any],
    *,
    content_policy: str = 'generated',
) -> dict[str, Any]:
    if content_policy not in {'generated', 'source', 'projection'}:
        raise ValueError('content_policy must be generated, source, or projection')
    sanitized = clone_json_value(root)
    pending = [sanitized]
    while pending:
        node = pending.pop()
        data = node.get('data')
        if not _is_record(data):
            raise MindmapArtifactError('脑图节点 data 必须是对象')
        for key in tuple(data):
            key_text = str(key)
            if key in TRANSIENT_KEYS:
                data.pop(key, None)
                continue
            if key in AI_FORBIDDEN_CONTENT_KEYS:
                if content_policy == 'generated':
                    raise MindmapArtifactError('AI 脑图不能生成图片或附件')
                if content_policy == 'projection':
                    data.pop(key, None)
                continue
            if key_text.lower().startswith('on'):
                if content_policy == 'source':
                    data.pop(key, None)
                    continue
                raise MindmapArtifactError('AI 脑图包含不允许的事件字段')
            if content_policy == 'projection' and key not in AI_PROJECTION_DATA_KEYS:
                data.pop(key, None)
        data['text'] = _clean_text(data.get('text'), '脑图节点文本', AI_MAX_NODE_TEXT_LENGTH)
        if content_policy != 'source':
            data.pop('richText', None)
        if data.get('note') is not None:
            data['note'] = _clean_text(data['note'], '脑图节点备注', AI_MAX_NOTE_LENGTH)
        if data.get('hyperlink') is not None:
            data['hyperlink'] = _normalize_link(data['hyperlink'])
        children = node.get('children')
        if children is None:
            node['children'] = []
            children = []
        if not isinstance(children, list):
            raise MindmapArtifactError('脑图节点 children 必须是数组')
        pending.extend(reversed(children))
    return sanitized


def _measure_tree(
    root: dict[str, Any],
    *,
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> tuple[int, int]:
    node_count = 0
    max_depth = 0
    pending = [(root, 1)]
    while pending:
        node, depth = pending.pop()
        node_count += 1
        max_depth = max(max_depth, depth)
        if node_count > max_node_count:
            raise MindmapArtifactError(
                f'AI 脑图节点数量不能超过{max_node_count}',
                code='AI_INPUT_TOO_LARGE',
            )
        if depth > AI_MAX_TREE_DEPTH:
            raise MindmapArtifactError(
                f'AI 脑图层级不能超过{AI_MAX_TREE_DEPTH}',
                code='AI_INPUT_TOO_LARGE',
            )
        pending.extend((child, depth + 1) for child in node.get('children') or [])
    return node_count, max_depth


def normalize_ai_document(
    document: dict[str, Any],
    *,
    content_policy: str = 'generated',
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> tuple[dict[str, Any], dict[str, int]]:
    """把 Agent 候选结果收敛为编辑器可消费的确定性文档。"""
    if not _is_record(document):
        raise MindmapArtifactError('AI 脑图文档必须是对象')
    root = document.get('root')
    if not _is_record(root):
        raise MindmapArtifactError('AI 脑图缺少有效根节点')
    try:
        validate_mindmap_tree(root)
        normalized_root = SimpleMindDocumentCodec.decode(SimpleMindDocumentCodec.encode(root))
    except ValueError as exc:
        raise MindmapArtifactError(str(exc)) from exc
    if not _is_record(normalized_root):
        raise MindmapArtifactError('AI 脑图缺少有效根节点')
    normalized_root = _sanitize_ai_tree(normalized_root, content_policy=content_policy)
    node_count, tree_depth = _measure_tree(
        normalized_root,
        max_node_count=max_node_count,
    )

    layout = document.get('layout') or 'logicalStructure'
    if layout not in AI_ALLOWED_LAYOUTS:
        raise MindmapArtifactError('AI 脑图布局类型无效')
    theme = document.get('theme')
    if not _is_record(theme):
        theme = {'template': 'default', 'config': {}}
    else:
        theme = {
            'template': str(theme.get('template') or 'default')[:100],
            'config': clone_json_value(theme.get('config') or {}),
        }
    if content_policy == 'projection':
        theme['config'] = {}
    normalized = {
        'root': normalized_root,
        'layout': layout,
        'theme': theme,
        'view': clone_json_value(document.get('view')) if content_policy == 'source' else None,
        'documentData': (
            clone_json_value(document.get('documentData') or {})
            if content_policy == 'source'
            else {}
        ),
    }
    encoded = canonical_json_bytes(normalized)
    if len(encoded) > AI_MAX_DOCUMENT_BYTES:
        raise MindmapArtifactError(
            f'AI 脑图规范文档不能超过{AI_MAX_DOCUMENT_BYTES}字节',
            code='AI_INPUT_TOO_LARGE',
        )
    return normalized, {'nodeCount': node_count, 'treeDepth': tree_depth, 'bytes': len(encoded)}


def normalize_ai_editable_source_document(
    document: dict[str, Any],
    *,
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Normalize an editor snapshot while accepting legitimate blank nodes.

    A new simple-mind-map document starts with an empty root label, and nodes may
    temporarily be blank while a user edits. Generated artifacts remain strict;
    only editor-source snapshots receive a deterministic placeholder so browser
    and server hashes, proposal stale checks, and undo checks stay aligned.
    """
    if not _is_record(document):
        raise MindmapArtifactError('AI 脑图文档必须是对象')
    prepared = clone_json_value(document)
    # Pan/zoom is presentation state, not proposal content. The browser source
    # fingerprint intentionally omits it, so the server must do the same.
    prepared['view'] = None
    root = prepared.get('root')
    if not _is_record(root):
        raise MindmapArtifactError('AI 脑图缺少有效根节点')
    pending = [root]
    while pending:
        node = pending.pop()
        data = node.get('data')
        if not _is_record(data):
            raise MindmapArtifactError('脑图节点 data 必须是对象')
        raw_text = data.get('text')
        if isinstance(raw_text, str):
            visible_text = _HTML_PATTERN.sub(
                '',
                _CONTROL_CHARACTER_PATTERN.sub('', raw_text).strip(),
            ).strip()
            if not visible_text:
                data['text'] = AI_BLANK_SOURCE_NODE_TEXT
        elif raw_text is None:
            data['text'] = AI_BLANK_SOURCE_NODE_TEXT
        raw_note = data.get('note')
        if isinstance(raw_note, str):
            visible_note = _HTML_PATTERN.sub(
                '',
                _CONTROL_CHARACTER_PATTERN.sub('', raw_note).strip(),
            ).strip()
            if not visible_note:
                data.pop('note', None)
        raw_link = data.get('hyperlink')
        if isinstance(raw_link, str) and not raw_link.strip():
            data.pop('hyperlink', None)
        children = node.get('children')
        if isinstance(children, list):
            pending.extend(reversed(children))
    return normalize_ai_document(
        prepared,
        content_policy='source',
        max_node_count=max_node_count,
    )


def project_ai_source_document(
    document: dict[str, Any],
    *,
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> tuple[dict[str, Any], dict[str, int]]:
    """生成只含 Agent 必需文本语义的投影，不把附件、图片或 HTML 送入模型。"""
    normalized, _summary = normalize_ai_document(
        document,
        content_policy='source',
        max_node_count=max_node_count,
    )
    return normalize_ai_document(
        normalized,
        content_policy='projection',
        max_node_count=max_node_count,
    )


def build_smm_artifact(
    document: dict[str, Any],
    *,
    title: str,
    agent_key: str,
    adapter_version: str,
    prompt_version: str,
    artifact_id: str | None = None,
    validator_version: str = 'mindmap-validator-2',
    validation_status: str = 'passed',
    preserve_source_content: bool = False,
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> tuple[dict[str, Any], dict[str, int]]:
    normalized, summary = normalize_ai_document(
        document,
        content_policy='source' if preserve_source_content else 'generated',
        max_node_count=max_node_count,
    )
    safe_title = _clean_text(title, '脑图标题', 200)
    artifact = {
        'format': SMM_FORMAT,
        'formatSchemaVersion': SMM_FORMAT_SCHEMA_VERSION,
        'manifest': {
            'artifactId': artifact_id or str(uuid.uuid4()),
            'title': safe_title,
            'sourceType': 'ai_generated',
            'createdAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'generator': {
                'agentKey': agent_key,
                'adapterVersion': adapter_version,
                'promptVersion': prompt_version,
            },
            'validation': {
                'status': validation_status,
                'validatorVersion': validator_version,
            },
            'documentHash': compute_document_hash(normalized),
        },
        'document': normalized,
    }
    if len(canonical_json_bytes(artifact)) > AI_MAX_FILE_BYTES:
        raise MindmapArtifactError(
            f'AI 脑图文件不能超过{AI_MAX_FILE_BYTES}字节',
            code='AI_INPUT_TOO_LARGE',
        )
    return artifact, summary


def validate_smm_artifact(
    artifact: dict[str, Any],
    *,
    require_passed: bool = True,
    max_node_count: int = AI_MAX_NODE_COUNT,
) -> tuple[dict[str, Any], dict[str, int]]:
    if not _is_record(artifact):
        raise MindmapArtifactError('SMM 文件必须是对象')
    if len(canonical_json_bytes(artifact)) > AI_MAX_FILE_BYTES:
        raise MindmapArtifactError(
            f'AI 脑图文件不能超过{AI_MAX_FILE_BYTES}字节',
            code='AI_INPUT_TOO_LARGE',
        )
    if artifact.get('format') != SMM_FORMAT:
        raise MindmapArtifactError('SMM 文件格式标识无效')
    if artifact.get('formatSchemaVersion') != SMM_FORMAT_SCHEMA_VERSION:
        raise MindmapArtifactError('不支持的 SMM 文件版本')
    manifest = artifact.get('manifest')
    if not _is_record(manifest):
        raise MindmapArtifactError('SMM 文件缺少 manifest')
    validation = manifest.get('validation')
    if not _is_record(validation) or validation.get('status') not in {'passed', 'draft'}:
        raise MindmapArtifactError('SMM 文件校验状态无效')
    # SMM 本身允许保存既有图片、附件和富文本；Agent 是否有权新增这些字段
    # 由隔离工具合同控制。这里仍会移除事件字段并执行结构、大小和哈希校验。
    source_document = artifact.get('document')
    document, summary = normalize_ai_document(
        source_document,
        content_policy='source',
        max_node_count=max_node_count,
    )
    expected_hash = compute_document_hash(document)
    # 外部 SDK 对发送前的原始 SMM 负责，平台对清洗后的规范文档负责。
    # 同时接受这两个可验证的边界，避免每个独立 Agent Kit 复制平台编解码器；
    # 返回值始终改写为平台规范哈希，后续存储和应用只有一种表示。
    source_hash = compute_document_hash(source_document)
    if manifest.get('documentHash') not in {source_hash, expected_hash}:
        raise MindmapArtifactError('SMM 文件内容哈希不匹配')
    normalized_artifact = clone_json_value(artifact)
    normalized_artifact['document'] = document
    normalized_artifact['manifest']['documentHash'] = expected_hash
    if require_passed and normalized_artifact['manifest']['validation']['status'] != 'passed':
        raise MindmapArtifactError('未通过校验的草稿不能直接应用')
    return normalized_artifact, summary
