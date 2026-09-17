"""AI 草稿检查点专用密钥、轮换与兼容读取边界。"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI

import server
from config.env import AppConfig, JwtConfig, MindmapAiConfig
from exceptions.exception import ServiceException
from module_mindmap.ai.checkpoint_crypto import (
    CHECKPOINT_CRYPTO_VERSION,
    CHECKPOINT_FALLBACK_KEY_ID,
    MindmapAiCheckpointCrypto,
)
from module_mindmap.service.mindmap_ai_service import MindmapAiTaskManager
from utils.crypto_util import CryptoUtil

CURRENT_SECRET = 'current-checkpoint-secret-32-bytes-minimum-value'
LEGACY_SECRET = 'legacy-checkpoint-secret-32-bytes-minimum-value'


def _document() -> dict:
    return {
        'root': {'data': {'uid': 'root', 'text': 'private'}, 'children': []},
        'layout': 'logicalStructure',
        'theme': {'template': 'default', 'config': {}},
        'view': None,
        'documentData': {},
    }


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    environment: str = 'prod',
    key_id: str = 'current-v2',
    secret: str = CURRENT_SECRET,
    legacy_keys: dict[str, str] | None = None,
    allow_legacy_jwt: bool = False,
) -> None:
    monkeypatch.setattr(AppConfig, 'app_env', environment)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_checkpoint_key_id', key_id)
    monkeypatch.setattr(MindmapAiConfig, 'mindmap_ai_checkpoint_key', secret)
    monkeypatch.setattr(
        MindmapAiConfig,
        'mindmap_ai_checkpoint_legacy_keys_json',
        json.dumps(legacy_keys or {}),
    )
    monkeypatch.setattr(
        MindmapAiConfig,
        'mindmap_ai_checkpoint_allow_legacy_jwt_read',
        allow_legacy_jwt,
    )


def test_current_key_envelope_declares_crypto_version_and_key_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    encrypted = MindmapAiCheckpointCrypto.encrypt_envelope({
        'schemaVersion': 1,
        'jobId': 'job-1',
        'payload': {'private': '节点正文'},
    })

    outer = json.loads(encrypted)
    assert outer['cryptoVersion'] == CHECKPOINT_CRYPTO_VERSION
    assert outer['keyId'] == 'current-v2'
    assert '节点正文' not in encrypted
    decrypted = MindmapAiCheckpointCrypto.decrypt_envelope(encrypted)
    assert decrypted['cryptoVersion'] == CHECKPOINT_CRYPTO_VERSION
    assert decrypted['keyId'] == 'current-v2'
    assert decrypted['payload'] == {'private': '节点正文'}


def test_rotated_legacy_key_is_read_only_and_selected_by_declared_key_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, key_id='old-v1', secret=LEGACY_SECRET)
    encrypted_old = MindmapAiCheckpointCrypto.encrypt_envelope({
        'schemaVersion': 1,
        'jobId': 'job-1',
    })

    _configure(
        monkeypatch,
        key_id='current-v2',
        secret=CURRENT_SECRET,
        legacy_keys={'old-v1': LEGACY_SECRET},
    )
    assert MindmapAiCheckpointCrypto.decrypt_envelope(encrypted_old)['jobId'] == 'job-1'
    encrypted_new = json.loads(MindmapAiCheckpointCrypto.encrypt_envelope({'jobId': 'job-2'}))
    assert encrypted_new['keyId'] == 'current-v2'

    tampered = json.loads(encrypted_old)
    tampered['keyId'] = 'current-v2'
    with pytest.raises(ServiceException, match='认证失败'):
        MindmapAiCheckpointCrypto.decrypt_envelope(json.dumps(tampered))


def test_production_without_dedicated_key_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, environment='prod', secret='')

    with pytest.raises(ServiceException, match='生产环境必须配置'):
        MindmapAiCheckpointCrypto.validate_runtime_configuration()


def test_configured_checkpoint_key_cannot_reuse_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, secret=JwtConfig.jwt_secret_key)

    with pytest.raises(ServiceException, match='必须与 JWT 密钥不同'):
        MindmapAiCheckpointCrypto.validate_runtime_configuration()


def test_runtime_validation_allows_development_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, environment='dev', secret='')

    assert MindmapAiCheckpointCrypto.validate_runtime_configuration() is None


def test_runtime_validation_rejects_invalid_legacy_key_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    monkeypatch.setattr(
        MindmapAiConfig,
        'mindmap_ai_checkpoint_legacy_keys_json',
        '{invalid-json',
    )

    with pytest.raises(ServiceException, match='不是有效 JSON'):
        MindmapAiCheckpointCrypto.validate_runtime_configuration()


def test_development_fallback_is_domain_separated_from_legacy_crypto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, environment='dev', secret='')
    encrypted = MindmapAiCheckpointCrypto.encrypt_envelope({'jobId': 'job-dev'})

    assert json.loads(encrypted)['keyId'] == CHECKPOINT_FALLBACK_KEY_ID
    assert MindmapAiCheckpointCrypto.decrypt_envelope(encrypted)['jobId'] == 'job-dev'
    with pytest.raises(ServiceException):
        CryptoUtil.decrypt(json.loads(encrypted)['token'])


def test_unversioned_legacy_jwt_ciphertext_requires_explicit_read_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_plaintext = json.dumps({'schemaVersion': 1, 'jobId': 'legacy-job'})
    encrypted = CryptoUtil.encrypt(legacy_plaintext)
    _configure(monkeypatch, allow_legacy_jwt=True)
    assert MindmapAiCheckpointCrypto.decrypt_envelope(encrypted)['jobId'] == 'legacy-job'

    monkeypatch.setattr(
        MindmapAiConfig,
        'mindmap_ai_checkpoint_allow_legacy_jwt_read',
        False,
    )
    with pytest.raises(ServiceException, match='不允许的历史密文格式'):
        MindmapAiCheckpointCrypto.decrypt_envelope(encrypted)


def test_authenticated_checkpoint_parts_cannot_be_spliced_into_another_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    values = MindmapAiTaskManager._draft_checkpoint_values(
        job_id='job-source',
        document=_document(),
        operations=[],
        initial_state=None,
        preview_version=4,
        preview_epoch=2,
        summary={},
        expires_time=datetime.now() + timedelta(hours=1),
    )
    spliced_checkpoint = SimpleNamespace(
        **{**values, 'job_id': 'job-target'},
        update_time=datetime.now(),
    )

    assert MindmapAiTaskManager._draft_checkpoint_preview(spliced_checkpoint) is None


@pytest.mark.asyncio
async def test_server_lifespan_validates_checkpoint_key_before_database_startup() -> None:
    checkpoint_error = ServiceException('checkpoint config invalid')
    with (
        patch.object(
            server.RedisUtil,
            'create_redis_pool',
            new=AsyncMock(return_value=object()),
        ),
        patch.object(
            server.StartupUtil,
            'acquire_startup_log_gate',
            new=AsyncMock(return_value=False),
        ),
        patch.object(
            server.TransportKeyProvider,
            'validate_runtime_configuration',
        ),
        patch.object(
            server.MindmapAiCheckpointCrypto,
            'validate_runtime_configuration',
            side_effect=checkpoint_error,
        ) as validate_checkpoint,
        patch.object(server, 'init_create_table', new=AsyncMock()) as init_database,
        pytest.raises(ServiceException, match='checkpoint config invalid'),
    ):
        async with server.lifespan(FastAPI()):
            pass

    validate_checkpoint.assert_called_once_with()
    init_database.assert_not_awaited()
