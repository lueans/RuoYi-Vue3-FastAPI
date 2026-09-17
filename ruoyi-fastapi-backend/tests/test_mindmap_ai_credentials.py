from types import SimpleNamespace

import pytest

from module_mindmap.ai.credentials import resolve_connector_credential
from module_mindmap.ai.document import MindmapArtifactError


def test_env_credential_is_resolved_only_for_agent_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'secret-value')
    connector = SimpleNamespace(credential_ref='env://ANTHROPIC_API_KEY')
    assert resolve_connector_credential('claude', connector) == {
        'ANTHROPIC_API_KEY': 'secret-value',
    }
    with pytest.raises(MindmapArtifactError, match='不允许'):
        resolve_connector_credential('codex', connector)

    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'gateway-secret')
    assert resolve_connector_credential(
        'claude', SimpleNamespace(credential_ref='env://ANTHROPIC_AUTH_TOKEN'),
    ) == {'ANTHROPIC_AUTH_TOKEN': 'gateway-secret'}


def test_missing_or_unsupported_secret_reference_fails_before_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with pytest.raises(MindmapArtifactError, match='未配置'):
        resolve_connector_credential(
            'codex', SimpleNamespace(credential_ref='env://OPENAI_API_KEY'),
        )
    with pytest.raises(MindmapArtifactError, match='密钥提供器'):
        resolve_connector_credential(
            'claude', SimpleNamespace(credential_ref='secret://mindmap/claude'),
        )


def test_claude_bedrock_static_reference_resolves_the_complete_credential_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'access-id')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'secret-key')
    monkeypatch.setenv('AWS_SESSION_TOKEN', 'session-token')
    monkeypatch.setenv('AWS_REGION', 'us-east-1')
    monkeypatch.setenv('DATABASE_PASSWORD', 'must-not-leak')

    selected = resolve_connector_credential(
        'claude', SimpleNamespace(credential_ref='env://AWS_ACCESS_KEY_ID'),
    )

    assert selected == {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_REGION': 'us-east-1',
        'AWS_ACCESS_KEY_ID': 'access-id',
        'AWS_SECRET_ACCESS_KEY': 'secret-key',
        'AWS_SESSION_TOKEN': 'session-token',
    }
    assert 'DATABASE_PASSWORD' not in selected


def test_claude_bedrock_static_reference_fails_atomically_when_secret_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'access-id')
    monkeypatch.delenv('AWS_SECRET_ACCESS_KEY', raising=False)

    with pytest.raises(MindmapArtifactError) as error:
        resolve_connector_credential(
            'claude', SimpleNamespace(credential_ref='env://AWS_ACCESS_KEY_ID'),
        )

    assert error.value.code == 'AI_PROVIDER_AUTH_FAILED'
    assert 'AWS_SECRET_ACCESS_KEY' in str(error.value)
    assert 'access-id' not in str(error.value)


def test_claude_bedrock_profile_reference_includes_only_safe_profile_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AWS_PROFILE', 'mindmap-runtime')
    monkeypatch.setenv('AWS_REGION', 'eu-west-1')
    monkeypatch.setenv('AWS_CONFIG_FILE', '/run/secrets/aws/config')
    monkeypatch.setenv('AWS_SHARED_CREDENTIALS_FILE', '/run/secrets/aws/credentials')
    monkeypatch.setenv('AWS_ENDPOINT_URL', 'https://attacker.example.test')

    selected = resolve_connector_credential(
        'claude', SimpleNamespace(credential_ref='env://AWS_PROFILE'),
    )

    assert selected == {
        'CLAUDE_CODE_USE_BEDROCK': '1',
        'AWS_PROFILE': 'mindmap-runtime',
        'AWS_REGION': 'eu-west-1',
        'AWS_CONFIG_FILE': '/run/secrets/aws/config',
        'AWS_SHARED_CREDENTIALS_FILE': '/run/secrets/aws/credentials',
    }
    assert 'AWS_ENDPOINT_URL' not in selected


def test_claude_bedrock_web_identity_reference_requires_role_and_token_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('AWS_ROLE_ARN', 'arn:aws:iam::123456789012:role/mindmap')
    monkeypatch.setenv('AWS_WEB_IDENTITY_TOKEN_FILE', '/var/run/secrets/aws/token')
    monkeypatch.setenv('AWS_ROLE_SESSION_NAME', 'mindmap-session')

    selected = resolve_connector_credential(
        'claude', SimpleNamespace(credential_ref='env://AWS_WEB_IDENTITY_TOKEN_FILE'),
    )

    assert selected['CLAUDE_CODE_USE_BEDROCK'] == '1'
    assert selected['AWS_ROLE_ARN'].endswith(':role/mindmap')
    assert selected['AWS_WEB_IDENTITY_TOKEN_FILE'] == '/var/run/secrets/aws/token'
    assert selected['AWS_ROLE_SESSION_NAME'] == 'mindmap-session'


def test_claude_bedrock_default_chain_allows_only_relative_container_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('CLAUDE_CODE_USE_BEDROCK', 'true')
    monkeypatch.setenv(
        'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI',
        '/v2/credentials/task-role',
    )
    monkeypatch.setenv(
        'AWS_CONTAINER_CREDENTIALS_FULL_URI',
        'https://attacker.example.test/credentials',
    )

    selected = resolve_connector_credential(
        'claude',
        SimpleNamespace(credential_ref='env://CLAUDE_CODE_USE_BEDROCK'),
    )

    assert selected['CLAUDE_CODE_USE_BEDROCK'] == '1'
    assert selected['AWS_CONTAINER_CREDENTIALS_RELATIVE_URI'] == (
        '/v2/credentials/task-role'
    )
    assert 'AWS_CONTAINER_CREDENTIALS_FULL_URI' not in selected
