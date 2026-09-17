"""把 Connector 的服务端凭据引用解析为单次 Agent 运行环境。"""
from __future__ import annotations

import os
import re
from typing import Any

from module_mindmap.ai.document import MindmapArtifactError

_ENV_NAME_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{1,127}$')

CLAUDE_DIRECT_CREDENTIAL_ENV = frozenset({
    'ANTHROPIC_API_KEY',
    'ANTHROPIC_AUTH_TOKEN',
    'CLAUDE_CODE_OAUTH_TOKEN',
    'GOOGLE_APPLICATION_CREDENTIALS',
})
CLAUDE_BEDROCK_STATIC_CREDENTIAL_ENV = frozenset({
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'AWS_SESSION_TOKEN',
})
CLAUDE_BEDROCK_WEB_IDENTITY_ENV = frozenset({
    'AWS_ROLE_ARN',
    'AWS_ROLE_SESSION_NAME',
    'AWS_WEB_IDENTITY_TOKEN_FILE',
})
CLAUDE_BEDROCK_PROFILE_ENV = frozenset({
    'AWS_PROFILE',
    'AWS_SHARED_CREDENTIALS_FILE',
    'AWS_CONFIG_FILE',
})
CLAUDE_BEDROCK_COMMON_ENV = frozenset({
    'CLAUDE_CODE_USE_BEDROCK',
    'AWS_REGION',
    'AWS_DEFAULT_REGION',
    'AWS_CA_BUNDLE',
    'AWS_EC2_METADATA_DISABLED',
    'ANTHROPIC_BEDROCK_BASE_URL',
    'ANTHROPIC_SMALL_FAST_MODEL_AWS_REGION',
})
CLAUDE_BEDROCK_DEFAULT_CHAIN_ENV = frozenset({
    'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI',
})
CLAUDE_BEDROCK_RUNTIME_ENV = (
    CLAUDE_BEDROCK_COMMON_ENV
    | CLAUDE_BEDROCK_DEFAULT_CHAIN_ENV
    | frozenset({
        'AWS_BEARER_TOKEN_BEDROCK',
    })
)
CLAUDE_BEDROCK_ENV_ALLOWLIST = frozenset().union(
    CLAUDE_BEDROCK_STATIC_CREDENTIAL_ENV,
    CLAUDE_BEDROCK_WEB_IDENTITY_ENV,
    CLAUDE_BEDROCK_PROFILE_ENV,
    CLAUDE_BEDROCK_RUNTIME_ENV,
)
CLAUDE_BEDROCK_CREDENTIAL_ANCHORS = frozenset({
    *CLAUDE_BEDROCK_STATIC_CREDENTIAL_ENV,
    'AWS_PROFILE',
    'AWS_BEARER_TOKEN_BEDROCK',
    'AWS_ROLE_ARN',
    'AWS_WEB_IDENTITY_TOKEN_FILE',
    # 允许部署在 EC2/ECS 等工作负载角色上的服务显式选择默认凭据链。
    'CLAUDE_CODE_USE_BEDROCK',
})
CLAUDE_CREDENTIAL_ENV_ALLOWLIST = frozenset().union(
    CLAUDE_DIRECT_CREDENTIAL_ENV,
    CLAUDE_BEDROCK_ENV_ALLOWLIST,
)
_AGENT_ENV_ALLOWLIST = {
    # Connector 仍然只保存一个变量名；Bedrock anchor 会在运行时原子地
    # 展开为同一凭据族。任何值都不会进入 Connector 或任务记录。
    'claude': CLAUDE_DIRECT_CREDENTIAL_ENV | CLAUDE_BEDROCK_CREDENTIAL_ANCHORS,
    'codex': frozenset({'OPENAI_API_KEY'}),
}


def _configured_environment(names: frozenset[str]) -> dict[str, str]:
    return {
        name: value
        for name in names
        if (value := os.environ.get(name))
    }


def _require_environment(names: frozenset[str]) -> dict[str, str]:
    selected = _configured_environment(names)
    missing = sorted(names - set(selected))
    if missing:
        raise MindmapArtifactError(
            f'Claude Bedrock 凭据缺少配套环境变量：{"、".join(missing)}',
            code='AI_PROVIDER_AUTH_FAILED',
        )
    return selected


def _resolve_claude_bedrock_credential(anchor: str) -> dict[str, str]:
    """由一个只写引用选择 Bedrock 凭据族，并仅复制固定白名单成员。"""
    selected = _configured_environment(CLAUDE_BEDROCK_COMMON_ENV)
    selected['CLAUDE_CODE_USE_BEDROCK'] = '1'

    if anchor in CLAUDE_BEDROCK_STATIC_CREDENTIAL_ENV:
        selected.update(_require_environment(frozenset({
            'AWS_ACCESS_KEY_ID',
            'AWS_SECRET_ACCESS_KEY',
        })))
        selected.update(_configured_environment(frozenset({'AWS_SESSION_TOKEN'})))
    elif anchor == 'AWS_PROFILE':
        selected.update(_require_environment(frozenset({'AWS_PROFILE'})))
        selected.update(_configured_environment(CLAUDE_BEDROCK_PROFILE_ENV))
    elif anchor == 'AWS_BEARER_TOKEN_BEDROCK':
        selected.update(_require_environment(frozenset({'AWS_BEARER_TOKEN_BEDROCK'})))
    elif anchor in {'AWS_ROLE_ARN', 'AWS_WEB_IDENTITY_TOKEN_FILE'}:
        selected.update(_require_environment(frozenset({
            'AWS_ROLE_ARN',
            'AWS_WEB_IDENTITY_TOKEN_FILE',
        })))
        selected.update(_configured_environment(CLAUDE_BEDROCK_WEB_IDENTITY_ENV))
    else:
        # CLAUDE_CODE_USE_BEDROCK 作为引用时使用 AWS 默认凭据链。只选择
        # 受信任部署环境中的标准候选，不允许任意 endpoint/命令变量透传。
        raw_switch = os.environ.get('CLAUDE_CODE_USE_BEDROCK', '').lower()
        if raw_switch not in {'1', 'true'}:
            raise MindmapArtifactError(
                'Claude Bedrock 默认凭据链未启用',
                code='AI_PROVIDER_AUTH_FAILED',
            )
        selected.update(_configured_environment(
            CLAUDE_BEDROCK_STATIC_CREDENTIAL_ENV
            | CLAUDE_BEDROCK_PROFILE_ENV
            | CLAUDE_BEDROCK_WEB_IDENTITY_ENV
            | CLAUDE_BEDROCK_DEFAULT_CHAIN_ENV
            | frozenset({'AWS_BEARER_TOKEN_BEDROCK'}),
        ))

    return selected


def resolve_connector_credential(agent_key: str, connector: Any | None) -> dict[str, str]:
    """只解析白名单环境变量；返回值只放进内存运行上下文，不持久化。"""
    credential_ref = str(getattr(connector, 'credential_ref', '') or '').strip()
    if not credential_ref:
        return {}
    if credential_ref.startswith('secret://'):
        raise MindmapArtifactError(
            '当前部署未配置 secret:// 密钥提供器，请改用 env:// 服务端环境变量',
            code='AI_PROVIDER_AUTH_FAILED',
        )
    if not credential_ref.startswith('env://'):
        raise MindmapArtifactError('Connector 凭据引用无效', code='AI_PROVIDER_AUTH_FAILED')
    variable_name = credential_ref.removeprefix('env://')
    if not _ENV_NAME_PATTERN.fullmatch(variable_name):
        raise MindmapArtifactError('Connector 环境变量名称无效', code='AI_PROVIDER_AUTH_FAILED')
    allowed_names = _AGENT_ENV_ALLOWLIST.get(agent_key, frozenset())
    if variable_name not in allowed_names:
        raise MindmapArtifactError(
            f'{agent_key} Connector 不允许使用环境变量 {variable_name}',
            code='AI_PROVIDER_AUTH_FAILED',
        )
    value = os.environ.get(variable_name)
    if not value:
        raise MindmapArtifactError(
            f'Connector 引用的环境变量 {variable_name} 未配置',
            code='AI_PROVIDER_AUTH_FAILED',
        )
    if agent_key == 'claude' and variable_name in CLAUDE_BEDROCK_CREDENTIAL_ANCHORS:
        return _resolve_claude_bedrock_credential(variable_name)
    return {variable_name: value}
