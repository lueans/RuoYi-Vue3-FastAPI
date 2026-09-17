"""AI 脑图领域服务。"""

from module_mindmap.ai.document import (
    AI_MAX_DOCUMENT_BYTES,
    AI_MAX_NODE_COUNT,
    AI_MAX_TREE_DEPTH,
    SMM_FORMAT,
    SMM_FORMAT_SCHEMA_VERSION,
    build_smm_artifact,
    validate_smm_artifact,
)

__all__ = [
    'AI_MAX_DOCUMENT_BYTES',
    'AI_MAX_NODE_COUNT',
    'AI_MAX_TREE_DEPTH',
    'SMM_FORMAT',
    'SMM_FORMAT_SCHEMA_VERSION',
    'build_smm_artifact',
    'validate_smm_artifact',
]
