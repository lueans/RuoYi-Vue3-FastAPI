"""Provider-neutral capability and discussion-result contracts for Agent adapters."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Final, Literal

AgentResultType = Literal['artifact', 'message']
AgentTarget = Literal['file', 'proposal', 'message']

ARTIFACT_RESULT: Final[AgentResultType] = 'artifact'
MESSAGE_RESULT: Final[AgentResultType] = 'message'
DISCUSSION_INTENT: Final = 'discuss'
MESSAGE_TARGET: Final[AgentTarget] = 'message'
DEFAULT_RESULT_TYPES: Final[tuple[AgentResultType, ...]] = (ARTIFACT_RESULT,)
SUPPORTED_RESULT_TYPES: Final[frozenset[str]] = frozenset({ARTIFACT_RESULT, MESSAGE_RESULT})
SUPPORTED_TARGETS: Final[frozenset[str]] = frozenset({'file', 'proposal', MESSAGE_TARGET})

# These limits intentionally mirror module_mindmap.ai.adapters.base. Keeping the
# standalone Kit equally strict means an external result cannot pass locally and
# then fail only after it reaches platform persistence.
MAX_AGENT_MESSAGE_LENGTH: Final = 20_000
MAX_AGENT_MESSAGE_BYTES: Final = 64 * 1024
MAX_AGENT_MESSAGE_TITLE_LENGTH: Final = 200
_UNSAFE_MESSAGE_CONTROL_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


class AgentContractError(ValueError):
    """Stable validation error raised for an invalid Agent interoperability payload."""


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise AgentContractError(f'manifest.{field_name} must be a non-empty string array')
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise AgentContractError(f'manifest.{field_name} cannot contain duplicates')
    return normalized


def resolve_result_types(manifest: Mapping[str, Any]) -> tuple[AgentResultType, ...]:
    """Resolve result capabilities, defaulting pre-discussion manifests to artifact-only."""
    if not isinstance(manifest, Mapping):
        raise AgentContractError('manifest must be an object')
    raw_result_types = manifest.get('resultTypes', DEFAULT_RESULT_TYPES)
    result_types = _string_tuple(raw_result_types, 'resultTypes')
    if not set(result_types).issubset(SUPPORTED_RESULT_TYPES):
        raise AgentContractError('manifest.resultTypes supports only artifact and message')
    return tuple(result_types)  # type: ignore[return-value]


def normalize_agent_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate capabilities and materialize the backward-compatible resultTypes default."""
    if not isinstance(manifest, Mapping):
        raise AgentContractError('manifest must be an object')
    intents = _string_tuple(manifest.get('intents'), 'intents')
    result_types = resolve_result_types(manifest)
    if DISCUSSION_INTENT in intents and MESSAGE_RESULT not in result_types:
        raise AgentContractError('manifest declaring discuss must also declare resultTypes message')
    normalized = dict(manifest)
    normalized['intents'] = list(intents)
    normalized['resultTypes'] = list(result_types)
    return normalized


def validate_agent_request(
    intent: str,
    target: str,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Validate the intent/target pair and optional manifest capability negotiation."""
    if not isinstance(intent, str) or not intent.strip():
        raise AgentContractError('request.intent must be a non-empty string')
    if not isinstance(target, str) or target not in SUPPORTED_TARGETS:
        raise AgentContractError('request.target must be file, proposal, or message')
    intent = intent.strip()
    expected_result: AgentResultType
    if intent == DISCUSSION_INTENT:
        if target != MESSAGE_TARGET:
            raise AgentContractError('discuss requests must target message')
        expected_result = MESSAGE_RESULT
    else:
        if target == MESSAGE_TARGET:
            raise AgentContractError('only discuss requests may target message')
        expected_result = ARTIFACT_RESULT

    if manifest is not None:
        capabilities = normalize_agent_manifest(manifest)
        if intent not in capabilities['intents']:
            raise AgentContractError(f'manifest does not support intent: {intent}')
        if expected_result not in capabilities['resultTypes']:
            raise AgentContractError(f'manifest does not support result type: {expected_result}')
    return {'intent': intent, 'target': target, 'resultType': expected_result}


def agent_message_json_schema() -> dict[str, Any]:
    """Return the closed structured-output schema used for discussion completion."""
    return {
        'type': 'object',
        'properties': {
            'completionState': {
                'type': 'string',
                'enum': ['message_completed'],
            },
            'title': {
                'type': ['string', 'null'],
                'maxLength': MAX_AGENT_MESSAGE_TITLE_LENGTH,
            },
            'content': {
                'type': 'string',
                'minLength': 1,
                'maxLength': MAX_AGENT_MESSAGE_LENGTH,
            },
            'contentType': {
                'type': 'string',
                'enum': ['text/plain'],
            },
        },
        'required': ['completionState', 'title', 'content', 'contentType'],
        'additionalProperties': False,
    }


def _structured_payload(value: Any) -> Any:
    if hasattr(value, 'model_dump') and callable(value.model_dump):
        try:
            return value.model_dump(by_alias=True)
        except TypeError:
            return value.model_dump()
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def normalize_agent_message_result(value: Any) -> dict[str, str | None]:
    """Validate and normalize a discussion result before returning it to the platform."""
    payload = _structured_payload(value)
    if (
        not isinstance(payload, dict)
        or set(payload) != {'completionState', 'title', 'content', 'contentType'}
        or payload.get('completionState') != 'message_completed'
        or payload.get('contentType') != 'text/plain'
    ):
        raise AgentContractError('discussion result does not match the structured contract')
    raw_title = payload.get('title')
    raw_content = payload.get('content')
    if raw_title is not None and not isinstance(raw_title, str):
        raise AgentContractError('discussion title must be a string or null')
    if not isinstance(raw_content, str):
        raise AgentContractError('discussion content must be a string')

    title = ' '.join(raw_title.split()) if isinstance(raw_title, str) else None
    if title == '':
        title = None
    content = raw_content.strip()
    if (
        (
            title is not None
            and (len(title) > MAX_AGENT_MESSAGE_TITLE_LENGTH or _UNSAFE_MESSAGE_CONTROL_PATTERN.search(title))
        )
        or not content
        or len(content) > MAX_AGENT_MESSAGE_LENGTH
        or len(content.encode('utf-8')) > MAX_AGENT_MESSAGE_BYTES
        or _UNSAFE_MESSAGE_CONTROL_PATTERN.search(content)
    ):
        raise AgentContractError('discussion result contains unsafe or overlong content')
    return {
        'completionState': 'message_completed',
        'title': title,
        'content': content,
        'contentType': 'text/plain',
    }


def build_agent_message_result(
    content: str,
    *,
    title: str | None = None,
) -> dict[str, str | None]:
    """Build a normalized discussion completion without weakening validation."""
    return normalize_agent_message_result(
        {
            'completionState': 'message_completed',
            'title': title,
            'content': content,
            'contentType': 'text/plain',
        }
    )
