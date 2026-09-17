"""Public API for the standalone MindMap Agent Kit."""

from mindmap_agent_kit.artifact import (
    ArtifactValidationError,
    build_artifact,
    compute_document_hash,
    render_summary,
    validate_artifact,
)
from mindmap_agent_kit.builder import MindmapBuilder
from mindmap_agent_kit.contract import (
    DEFAULT_RESULT_TYPES,
    DISCUSSION_INTENT,
    MAX_AGENT_MESSAGE_BYTES,
    MAX_AGENT_MESSAGE_LENGTH,
    MAX_AGENT_MESSAGE_TITLE_LENGTH,
    MESSAGE_TARGET,
    AgentContractError,
    agent_message_json_schema,
    build_agent_message_result,
    normalize_agent_manifest,
    normalize_agent_message_result,
    resolve_result_types,
    validate_agent_request,
)

__all__ = [
    'DEFAULT_RESULT_TYPES',
    'DISCUSSION_INTENT',
    'MAX_AGENT_MESSAGE_BYTES',
    'MAX_AGENT_MESSAGE_LENGTH',
    'MAX_AGENT_MESSAGE_TITLE_LENGTH',
    'MESSAGE_TARGET',
    'AgentContractError',
    'ArtifactValidationError',
    'MindmapBuilder',
    'agent_message_json_schema',
    'build_agent_message_result',
    'build_artifact',
    'compute_document_hash',
    'normalize_agent_manifest',
    'normalize_agent_message_result',
    'render_summary',
    'resolve_result_types',
    'validate_agent_request',
    'validate_artifact',
]

__version__ = '1.1.0'
