"""Companion envelopes must match the actual platform crypto implementation."""

import importlib
import json
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from config.env import TransportCryptoConfig
from utils.transport_crypto_util import TransportCryptoUtil, TransportKeyProvider


def test_local_companion_enrollment_crypto_interoperates_with_platform(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'mindmap-agent-bridge'))
    transport = importlib.import_module('mindmap_agent_bridge.transport')
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    monkeypatch.setattr(TransportKeyProvider, 'get_private_key_pem', lambda _kid: pem)
    monkeypatch.setattr(TransportCryptoConfig, 'transport_crypto_algorithm', 'RSA_OAEP_AES_256_GCM')
    metadata = {
        'kid': 'temporary-test-key', 'alg': 'RSA_OAEP_AES_256_GCM', 'envelopeVersion': '1',
        'expireAt': time.time() + 300,
        'publicKey': private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
    }
    path = '/mindmap/ai/device-bridge/enroll'
    payload = {'deviceId': '11111111-1111-4111-8111-111111111111', 'deviceSecret': 'd' * 43, 'pairingSecret': 'p' * 43}
    envelope, key = transport.encrypt(payload, metadata, path)
    received = TransportCryptoUtil.decrypt_envelope(envelope, 'POST', path)
    assert json.loads(received.plaintext) == payload
    assert received.aes_key == key
    result = {'code': 200, 'data': {'deviceId': payload['deviceId']}}
    response = TransportCryptoUtil.encrypt_response_body(key, json.dumps(result).encode(), metadata['kid'], 'POST', path)
    assert transport.decrypt(json.loads(response), key, metadata['kid'], path) == result
