"""SMM v2 artifact construction and deterministic validation."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import rfc8785

FORMAT = 'ruoyi-mindmap'
SCHEMA_VERSION = 2
HASH_PREFIX = 'mmf2:sha256:'
MAX_NODES = 2_000
MAX_DEPTH = 32
MAX_FILE_BYTES = 2_000_000
ALLOWED_LAYOUTS = frozenset({
    'mindMap', 'logicalStructure', 'organizationStructure', 'catalogOrganization',
    'timeline', 'timeline2', 'verticalTimeline', 'verticalTimeline2',
    'verticalTimeline3', 'fishbone', 'fishbone2', 'rightFishbone',
    'rightFishbone2', 'logicalStructureLeft',
})
ALLOWED_LINK_SCHEMES = frozenset({'http', 'https', 'mailto'})
AGENT_KEY_PATTERN = re.compile(r'^[a-z][a-z0-9_]{1,63}$')


class ArtifactValidationError(ValueError):
    """Stable validation error raised for an invalid SMM artifact."""


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as exc:
        raise ArtifactValidationError('artifact contains a non-canonical JSON value') from exc


def compute_document_hash(document: dict[str, Any]) -> str:
    return f'{HASH_PREFIX}{hashlib.sha256(canonical_json_bytes(document)).hexdigest()}'


def _walk_document(document: dict[str, Any]) -> tuple[int, int]:
    root = document.get('root')
    if not _is_record(root):
        raise ArtifactValidationError('document.root must be an object')
    node_count = 0
    max_depth = 0
    seen_uids: set[str] = set()
    pending: list[tuple[dict[str, Any], int]] = [(root, 1)]
    while pending:
        node, depth = pending.pop()
        node_count += 1
        max_depth = max(max_depth, depth)
        if node_count > MAX_NODES:
            raise ArtifactValidationError(f'document cannot contain more than {MAX_NODES} nodes')
        if depth > MAX_DEPTH:
            raise ArtifactValidationError(f'document cannot exceed depth {MAX_DEPTH}')
        data = node.get('data')
        if not _is_record(data):
            raise ArtifactValidationError('every node must contain a data object')
        uid = data.get('uid')
        text = data.get('text')
        if not isinstance(uid, str) or not uid.strip():
            raise ArtifactValidationError('every node must contain a non-empty string uid')
        if uid in seen_uids:
            raise ArtifactValidationError(f'duplicate node uid: {uid}')
        seen_uids.add(uid)
        if not isinstance(text, str) or not text.strip():
            raise ArtifactValidationError(f'node {uid} must contain non-empty text')
        for key in data:
            if str(key).lower().startswith('on'):
                raise ArtifactValidationError(f'node {uid} contains a forbidden event field')
        hyperlink = data.get('hyperlink')
        if hyperlink is not None:
            if not isinstance(hyperlink, str) or urlparse(hyperlink).scheme.lower() not in ALLOWED_LINK_SCHEMES:
                raise ArtifactValidationError(f'node {uid} contains an unsafe hyperlink')
        children = node.get('children', [])
        if not isinstance(children, list) or any(not _is_record(child) for child in children):
            raise ArtifactValidationError(f'node {uid}.children must be an array of nodes')
        pending.extend((child, depth + 1) for child in reversed(children))
    return node_count, max_depth


def validate_artifact(artifact: dict[str, Any], *, require_passed: bool = True) -> dict[str, Any]:
    if not _is_record(artifact):
        raise ArtifactValidationError('artifact must be an object')
    if artifact.get('format') != FORMAT or artifact.get('formatSchemaVersion') != SCHEMA_VERSION:
        raise ArtifactValidationError('artifact must use ruoyi-mindmap SMM v2')
    manifest = artifact.get('manifest')
    document = artifact.get('document')
    if not _is_record(manifest) or not _is_record(document):
        raise ArtifactValidationError('artifact must contain manifest and document objects')
    required_manifest = ('artifactId', 'title', 'sourceType', 'createdAt', 'generator', 'validation', 'documentHash')
    missing = [key for key in required_manifest if key not in manifest]
    if missing:
        raise ArtifactValidationError(f'manifest is missing: {", ".join(missing)}')
    if not isinstance(manifest['artifactId'], str) or not manifest['artifactId'].strip():
        raise ArtifactValidationError('manifest.artifactId must be a non-empty string')
    if not isinstance(manifest['title'], str) or not manifest['title'].strip() or len(manifest['title']) > 200:
        raise ArtifactValidationError('manifest.title must contain 1 to 200 characters')
    generator = manifest.get('generator')
    if not _is_record(generator) or not AGENT_KEY_PATTERN.fullmatch(str(generator.get('agentKey') or '')):
        raise ArtifactValidationError('manifest.generator.agentKey is invalid')
    if any(not isinstance(generator.get(key), str) or not generator[key].strip() for key in ('adapterVersion', 'promptVersion')):
        raise ArtifactValidationError('manifest.generator versions must be non-empty strings')
    validation = manifest.get('validation')
    if not _is_record(validation) or validation.get('status') not in {'passed', 'draft'}:
        raise ArtifactValidationError('manifest.validation.status must be passed or draft')
    if not isinstance(validation.get('validatorVersion'), str) or not validation['validatorVersion'].strip():
        raise ArtifactValidationError('manifest.validation.validatorVersion must be a non-empty string')
    if require_passed and validation['status'] != 'passed':
        raise ArtifactValidationError('draft artifacts cannot be applied')
    if document.get('layout') not in ALLOWED_LAYOUTS:
        raise ArtifactValidationError('document.layout is not supported')
    if not _is_record(document.get('theme')) or not _is_record(document.get('documentData')):
        raise ArtifactValidationError('document.theme and document.documentData must be objects')
    if document.get('view') is not None and not _is_record(document.get('view')):
        raise ArtifactValidationError('document.view must be an object or null')
    node_count, tree_depth = _walk_document(document)
    expected_hash = compute_document_hash(document)
    if manifest.get('documentHash') != expected_hash:
        raise ArtifactValidationError('manifest.documentHash does not match document content')
    byte_size = len(canonical_json_bytes(artifact))
    if byte_size > MAX_FILE_BYTES:
        raise ArtifactValidationError(f'artifact cannot exceed {MAX_FILE_BYTES} bytes')
    return {
        'status': 'passed',
        'formatSchemaVersion': SCHEMA_VERSION,
        'documentHash': expected_hash,
        'nodeCount': node_count,
        'treeDepth': tree_depth,
        'bytes': byte_size,
        'platformTrust': 'external_unverified',
    }


def build_artifact(
    document: dict[str, Any],
    *,
    title: str,
    agent_key: str,
    adapter_version: str,
    prompt_version: str,
    artifact_id: str | None = None,
    validation_status: str = 'passed',
) -> dict[str, Any]:
    if validation_status not in {'passed', 'draft'}:
        raise ArtifactValidationError('validation_status must be passed or draft')
    if not isinstance(title, str) or not title.strip():
        raise ArtifactValidationError('title must be a non-empty string')
    if not isinstance(agent_key, str) or not AGENT_KEY_PATTERN.fullmatch(agent_key):
        raise ArtifactValidationError('agent_key is invalid')
    if (
        not isinstance(adapter_version, str)
        or not adapter_version.strip()
        or not isinstance(prompt_version, str)
        or not prompt_version.strip()
    ):
        raise ArtifactValidationError('adapter_version and prompt_version are required')
    artifact = {
        'format': FORMAT,
        'formatSchemaVersion': SCHEMA_VERSION,
        'manifest': {
            'artifactId': artifact_id or str(uuid.uuid4()),
            'title': title.strip()[:200],
            'sourceType': 'external_agent',
            'createdAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'generator': {
                'agentKey': agent_key,
                'adapterVersion': adapter_version,
                'promptVersion': prompt_version,
            },
            'validation': {
                'status': validation_status,
                'validatorVersion': 'mindmap-agent-kit-1',
            },
            'provenance': 'external_unverified',
            'documentHash': compute_document_hash(document),
        },
        'document': document,
    }
    validate_artifact(artifact, require_passed=False)
    return artifact


def render_summary(artifact: dict[str, Any]) -> str:
    report = validate_artifact(artifact, require_passed=False)
    manifest = artifact['manifest']
    validation = manifest['validation']['status']
    lines = [
        f"# {manifest['title']}",
        '',
        f"- SMM: v{artifact['formatSchemaVersion']}",
        f"- Validation: {validation}",
        f"- Nodes: {report['nodeCount']}",
        f"- Depth: {report['treeDepth']}",
        f"- Generator: {manifest['generator']['agentKey']} {manifest['generator']['adapterVersion']}",
        f"- Document hash: `{manifest['documentHash']}`",
        '- Platform trust: external/unverified until imported and revalidated by the platform',
    ]
    return '\n'.join(lines)


def load_artifact(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(f'cannot read artifact: {exc}') from exc
    if not _is_record(value):
        raise ArtifactValidationError('artifact JSON root must be an object')
    return value
