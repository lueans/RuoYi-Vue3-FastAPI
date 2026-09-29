"""Interoperate with the app's optional/required RSA-OAEP + AES-GCM envelope.

This is additional to TLS, never a substitute. No downgrade retry on errors.
"""

import base64
import json
import os
import time
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_KEY_ID_LENGTH = 128
MIN_RSA_KEY_BITS = 2048


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip('=')


def decode(value: str) -> bytes:
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def uses_envelope(config: dict, path: str) -> bool:
    if type(config.get('transportCryptoActive')) is not bool:
        raise ValueError('Invalid crypto configuration')
    def matches(patterns: object) -> bool:
        if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
            raise ValueError('Invalid crypto paths')
        return any(path == item or path.startswith(item.rstrip('/') + '/') for item in patterns)
    enabled = config.get('enabledPaths', [])
    return config['transportCryptoActive'] and not matches(config.get('excludePaths', [])) and (
        not enabled or matches(enabled)
    )


def encrypt(payload: dict, key_meta: dict, path: str) -> tuple[dict, bytes]:
    if key_meta.get('alg') != 'RSA_OAEP_AES_256_GCM' or str(key_meta.get('envelopeVersion')) != '1':
        raise ValueError('Unsupported encryption')
    if not isinstance(key_meta.get('kid'), str) or not key_meta['kid'] or len(key_meta['kid']) > MAX_KEY_ID_LENGTH:
        raise ValueError('Invalid key identifier')
    if key_meta.get('expireAt', 0) <= time.time():
        raise ValueError('Expired key')
    public_key = serialization.load_pem_public_key(key_meta['publicKey'].encode())
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < MIN_RSA_KEY_BITS:
        raise ValueError('Invalid public key')
    key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    aad = {'method': 'POST', 'path': path}
    wrapped = public_key.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    return {
        'v': '1', 'kid': key_meta['kid'], 'alg': key_meta['alg'], 'ts': int(time.time()),
        'nonce': str(uuid4()), 'ek': encode(wrapped), 'iv': encode(iv), 'aad': aad,
        'ct': encode(AESGCM(key).encrypt(iv, json_bytes(payload), json_bytes(aad))),
    }, key


def decrypt(envelope: dict, key: bytes, kid: str, path: str) -> dict:
    aad = {'method': 'POST', 'path': path, 'direction': 'response'}
    if (envelope.get('aad') != aad or envelope.get('kid') != kid or envelope.get('v') != '1'
            or envelope.get('alg') != 'AES_256_GCM'):
        raise ValueError('Response envelope binding failed')
    return json.loads(AESGCM(key).decrypt(decode(envelope['iv']), decode(envelope['ct']), json_bytes(aad)))
