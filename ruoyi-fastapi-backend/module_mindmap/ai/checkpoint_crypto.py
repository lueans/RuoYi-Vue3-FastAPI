"""Domain-separated, rotatable encryption for AI draft checkpoints."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from config.env import AppConfig, JwtConfig, MindmapAiConfig
from exceptions.exception import ServiceException

CHECKPOINT_CRYPTO_VERSION = 2
CHECKPOINT_FALLBACK_KEY_ID = 'dev-jwt-fallback-v1'
CHECKPOINT_MIN_SECRET_BYTES = 32
_CHECKPOINT_KEY_DOMAIN = b'mindmap-ai-draft-checkpoint:key:v1\0'
_CHECKPOINT_FALLBACK_DOMAIN = b'mindmap-ai-draft-checkpoint:jwt-fallback:v1\0'
_KEY_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
_FALLBACK_ENVIRONMENTS = frozenset({'dev', 'test', 'local'})


def _fernet_from_secret(secret: str, *, domain: bytes) -> Fernet:
    if len(secret.encode('utf-8')) < CHECKPOINT_MIN_SECRET_BYTES:
        raise ServiceException('AI 草稿检查点密钥长度不能少于 32 字节')
    digest = hashlib.sha256(domain + secret.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _legacy_jwt_fernet() -> Fernet:
    """Match the historical CryptoUtil derivation for explicit read-only migration."""
    digest = hashlib.sha256(JwtConfig.jwt_secret_key.encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _parse_legacy_keys() -> dict[str, str]:
    raw = str(MindmapAiConfig.mindmap_ai_checkpoint_legacy_keys_json or '').strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ServiceException('AI 草稿检查点历史密钥配置不是有效 JSON') from exc
    if not isinstance(parsed, dict):
        raise ServiceException('AI 草稿检查点历史密钥配置必须是 JSON 对象')
    output: dict[str, str] = {}
    for raw_key_id, raw_secret in parsed.items():
        key_id = str(raw_key_id)
        secret = str(raw_secret)
        if (
            not _KEY_ID_PATTERN.fullmatch(key_id)
            or len(secret.encode('utf-8')) < CHECKPOINT_MIN_SECRET_BYTES
            or secret == JwtConfig.jwt_secret_key
        ):
            raise ServiceException('AI 草稿检查点历史密钥配置无效')
        output[key_id] = secret
    return output


def _current_key() -> tuple[str, Fernet]:
    key_id = str(MindmapAiConfig.mindmap_ai_checkpoint_key_id or '').strip()
    secret = str(MindmapAiConfig.mindmap_ai_checkpoint_key or '')
    if secret.strip():
        if not _KEY_ID_PATTERN.fullmatch(key_id):
            raise ServiceException('AI 草稿检查点当前 keyId 无效')
        if secret == JwtConfig.jwt_secret_key:
            raise ServiceException('AI 草稿检查点密钥必须与 JWT 密钥不同')
        return key_id, _fernet_from_secret(secret, domain=_CHECKPOINT_KEY_DOMAIN)
    environment = str(AppConfig.app_env or '').strip().lower()
    if environment not in _FALLBACK_ENVIRONMENTS:
        raise ServiceException('生产环境必须配置独立的 AI 草稿检查点密钥')
    return (
        CHECKPOINT_FALLBACK_KEY_ID,
        _fernet_from_secret(JwtConfig.jwt_secret_key, domain=_CHECKPOINT_FALLBACK_DOMAIN),
    )


class MindmapAiCheckpointCrypto:
    """Encrypt with one current key and decrypt by an explicitly declared keyId."""

    @classmethod
    def validate_runtime_configuration(cls) -> None:
        """Fail fast on unsafe checkpoint key configuration without writing data."""
        current_key_id, _cipher = _current_key()
        legacy_keys = _parse_legacy_keys()
        if current_key_id in legacy_keys:
            raise ServiceException('AI 草稿检查点当前 keyId 不得出现在历史密钥中')

    @classmethod
    def encrypt_envelope(cls, payload: dict[str, Any]) -> str:
        key_id, cipher = _current_key()
        inner = {
            **payload,
            'cryptoVersion': CHECKPOINT_CRYPTO_VERSION,
            'keyId': key_id,
        }
        plaintext = json.dumps(
            inner,
            ensure_ascii=False,
            allow_nan=False,
            separators=(',', ':'),
        ).encode('utf-8')
        token = cipher.encrypt(plaintext).decode('ascii')
        return json.dumps(
            {
                'cryptoVersion': CHECKPOINT_CRYPTO_VERSION,
                'keyId': key_id,
                'token': token,
            },
            ensure_ascii=True,
            separators=(',', ':'),
        )

    @classmethod
    def decrypt_envelope(cls, ciphertext: str) -> dict[str, Any]:
        try:
            outer = json.loads(ciphertext)
        except (TypeError, json.JSONDecodeError):
            outer = None
        if not isinstance(outer, dict):
            if not MindmapAiConfig.mindmap_ai_checkpoint_allow_legacy_jwt_read:
                raise ServiceException('AI 草稿检查点使用了不允许的历史密文格式')
            return cls._decrypt_legacy_jwt(ciphertext)
        crypto_version = outer.get('cryptoVersion')
        key_id = outer.get('keyId')
        token = outer.get('token')
        if (
            crypto_version != CHECKPOINT_CRYPTO_VERSION
            or not isinstance(key_id, str)
            or not _KEY_ID_PATTERN.fullmatch(key_id)
            or not isinstance(token, str)
        ):
            raise ServiceException('AI 草稿检查点密文包络无效')
        current_key_id, current_cipher = _current_key()
        if key_id == current_key_id:
            cipher = current_cipher
        else:
            legacy_secret = _parse_legacy_keys().get(key_id)
            if legacy_secret is None:
                raise ServiceException('AI 草稿检查点 keyId 未配置')
            cipher = _fernet_from_secret(legacy_secret, domain=_CHECKPOINT_KEY_DOMAIN)
        try:
            inner = json.loads(cipher.decrypt(token.encode('ascii')))
        except (InvalidToken, UnicodeError, json.JSONDecodeError) as exc:
            raise ServiceException('AI 草稿检查点密文认证失败') from exc
        if (
            not isinstance(inner, dict)
            or inner.get('cryptoVersion') != CHECKPOINT_CRYPTO_VERSION
            or inner.get('keyId') != key_id
        ):
            raise ServiceException('AI 草稿检查点密文上下文无效')
        return inner

    @staticmethod
    def _decrypt_legacy_jwt(ciphertext: str) -> dict[str, Any]:
        try:
            decoded = _legacy_jwt_fernet().decrypt(ciphertext.encode('ascii'))
            inner = json.loads(decoded)
        except (InvalidToken, UnicodeError, json.JSONDecodeError) as exc:
            raise ServiceException('AI 草稿检查点历史密文认证失败') from exc
        if not isinstance(inner, dict) or inner.get('schemaVersion') != 1:
            raise ServiceException('AI 草稿检查点历史密文上下文无效')
        return inner
