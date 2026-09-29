"""No provider calls, CLI logins, user credentials, or application database."""

import asyncio
import json
import os
import stat
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mindmap_agent_bridge import cli, client, discovery, transport

DEVICE_ID = '11111111-1111-4111-8111-111111111111'
CONFIG = {'version': 1, 'deviceId': DEVICE_ID, 'deviceSecret': 'd' * 43,
          'pairingSecret': 'p' * 43, 'server': 'https://example.test/api'}
PATH = '/mindmap/ai/device-bridge/enroll'
WELCOME = {'type': 'welcome', 'protocolVersion': 1, 'capabilities': ['discover'], 'executionAvailable': False}


def state(revision):
    return {**WELCOME, 'type': 'state', 'scanRevision': revision}


@pytest.mark.parametrize('url', [
    'http://example.test', 'https://name:secret@example.test', 'https://example.test?secret=x',
    'https://example.test#fragment', 'file:///tmp/a', 'https://example.test:wrong', 'https://exam\nple.test',
])
def test_server_validation_rejects_unsafe_urls(url):
    with pytest.raises(client.BridgeError):
        client.normalize_server(url)


@pytest.mark.parametrize('url', ['http://localhost:8000', 'http://127.0.0.1:8000', 'http://[::1]:8000',
                               'https://example.test/api'])
def test_server_validation_retains_explicit_api_prefix(url):
    assert client.normalize_server(url + '/') == url


def test_private_configuration_is_atomic_and_cannot_be_overwritten_by_pair(tmp_path):
    path = tmp_path / 'private' / 'device.json'
    client.save_config(path, CONFIG, initial=True)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert client.read_config(path) == CONFIG
    with pytest.raises(client.BridgeError):
        client.save_config(path, {**CONFIG, 'deviceSecret': 'x' * 43}, initial=True)
    assert client.read_config(path)['deviceSecret'] == CONFIG['deviceSecret']
    paired = {key: value for key, value in CONFIG.items() if key != 'pairingSecret'}
    client.save_config(path, paired)
    assert client.read_config(path) == paired
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_configuration_rejects_symlinks_world_readable_and_malformed_files(tmp_path):
    path = tmp_path / 'device.json'
    client.save_config(path, CONFIG, initial=True)
    link = tmp_path / 'linked.json'
    link.symlink_to(path)
    for action in [lambda: client.read_config(link), lambda: client.save_config(link, CONFIG)]:
        with pytest.raises(client.BridgeError):
            action()
    path.chmod(0o644)
    with pytest.raises(client.BridgeError):
        client.read_config(path)
    for change in [{'version': True}, {'pairingSecret': ''}, {'deviceSecret': None}, {'server': 12}]:
        client.save_config(path, {**CONFIG, **change})
        with pytest.raises(client.BridgeError) as error:
            client.read_config(path)
        assert CONFIG['deviceSecret'] not in str(error.value)


@pytest.mark.parametrize('payload', [
    {**WELCOME, 'command': 'run something'}, {**WELCOME, 'executionAvailable': True},
    {**WELCOME, 'protocolVersion': True}, {**WELCOME, 'type': 'execute'}, [],
    {**state(1), 'scanRevision': 0}, {**state(1), 'scanRevision': True},
])
def test_protocol_rejects_unknown_fields_commands_and_execution(payload):
    expected = 'state' if isinstance(payload, dict) and 'scanRevision' in payload else 'welcome'
    with pytest.raises(client.BridgeError):
        client.decode_state(json.dumps(payload), expected)


@pytest.mark.asyncio
async def test_session_coalesces_scans_and_sends_only_allowlisted_metadata(monkeypatch):
    frames = [WELCOME, state(1), state(1), state(2), state(2), state(2)]
    socket = SimpleNamespace(recv=AsyncMock(side_effect=[json.dumps(item) for item in frames]), send=AsyncMock())
    scan = AsyncMock(return_value=[{'agentKey': 'claude', 'status': 'detected'}])
    class Stop(Exception):
        pass
    monkeypatch.setattr(client.asyncio, 'sleep', AsyncMock(side_effect=[None, None, Stop()]))
    with pytest.raises(Stop):
        await client.connected_session(socket, scan=scan)
    assert scan.await_count == 2
    sent = [json.loads(call.args[0]) for call in socket.send.await_args_list]
    assert [item['type'] for item in sent] == ['heartbeat', 'scan_result', 'heartbeat', 'scan_result', 'heartbeat']
    assert [item['scanRevision'] for item in sent if item['type'] == 'scan_result'] == [1, 2]
    assert CONFIG['deviceSecret'] not in json.dumps(sent)


@pytest.mark.asyncio
async def test_session_refuses_remote_execution_before_scanning():
    socket = SimpleNamespace(recv=AsyncMock(return_value=json.dumps({**WELCOME, 'executionAvailable': True})),
                             send=AsyncMock())
    scan = AsyncMock()
    with pytest.raises(client.BridgeError):
        await client.connected_session(socket, scan=scan)
    scan.assert_not_awaited()
    socket.send.assert_not_awaited()


def test_websocket_redirects_are_not_followed():
    error = RuntimeError('redirect')
    # Test the override without opening a socket.
    assert client.NoRedirectConnect.process_redirect(None, error) is error


@pytest.mark.asyncio
async def test_discovery_handles_python310_timeout_and_exposes_no_path(monkeypatch):
    monkeypatch.setattr(discovery, 'resolve_binary', lambda _key: '/private/test/claude')
    monkeypatch.setattr(discovery, 'probe', AsyncMock(side_effect=asyncio.TimeoutError))
    result = await discovery.detect('claude')
    assert result == {'agentKey': 'claude', 'installed': True, 'status': 'probe_failed',
                      'version': None, 'capabilities': []}
    assert '/private' not in json.dumps(result)


@pytest.mark.asyncio
async def test_discovery_extracts_only_version_and_known_capabilities(monkeypatch):
    monkeypatch.setattr(discovery, 'resolve_binary', lambda _key: '/test/kimi')
    monkeypatch.setattr(discovery, 'probe', AsyncMock(side_effect=[
        'Kimi 1.2.3\n/private/path\nSENSITIVE-TEXT', 'acp --resume unknown-secret',
    ]))
    result = await discovery.detect('kimi')
    assert result == {'agentKey': 'kimi', 'installed': True, 'version': '1.2.3',
                      'status': 'detected', 'capabilities': ['resume', 'acp']}


@pytest.mark.asyncio
async def test_claude_discovery_probes_print_mode_help_not_global_help(monkeypatch):
    monkeypatch.setattr(discovery, 'resolve_binary', lambda _key: '/test/claude')
    probe = AsyncMock(side_effect=['2.0.1', '--include-partial-messages'])
    monkeypatch.setattr(discovery, 'probe', probe)
    result = await discovery.detect('claude')
    assert result['capabilities'] == ['partial_messages']
    assert probe.await_args_list[1].kwargs == {'print_mode': True}


@pytest.mark.asyncio
async def test_probe_enforces_argument_environment_output_and_group_cleanup(monkeypatch):
    reader = SimpleNamespace(read=AsyncMock(side_effect=[b'x' * (discovery.MAX_PROBE_BYTES + 1)]))
    process = SimpleNamespace(stdout=reader, wait=AsyncMock(), pid=3456, returncode=0)
    spawn = AsyncMock(return_value=process)
    killed = []
    monkeypatch.setenv('APPLICATION_SECRET', 'must-not-reach-the-cli')
    monkeypatch.setattr(discovery.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(discovery.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(ValueError):
        await discovery.probe('/test/claude', '--version')
    assert spawn.call_args.args == ('/test/claude', '--version')
    assert 'APPLICATION_SECRET' not in spawn.call_args.kwargs['env']
    assert spawn.call_args.kwargs['start_new_session'] is True
    assert not os.path.exists(spawn.call_args.kwargs['cwd'])
    assert killed == [(3456, discovery.signal.SIGKILL)]
    process.wait.assert_awaited_once()
    with pytest.raises(ValueError):
        await discovery.probe('/test/claude', '--arbitrary-command')
    assert spawn.await_count == 1


@pytest.mark.asyncio
async def test_real_bounded_subprocess_probe_uses_only_python_version():
    assert 'Python ' in await discovery.probe(sys.executable, '--version')


@pytest.mark.asyncio
async def test_probe_cancel_during_spawn_reaps_the_started_process_group(monkeypatch):
    spawned, release = asyncio.Event(), asyncio.Event()
    original_spawn = asyncio.create_subprocess_exec
    process = None

    async def delayed_spawn(*_args, **kwargs):
        nonlocal process
        process = await original_spawn(sys.executable, '-c', 'import time; time.sleep(20)', **kwargs)
        spawned.set()
        await release.wait()
        return process

    monkeypatch.setattr(discovery.asyncio, 'create_subprocess_exec', delayed_spawn)
    task = asyncio.create_task(discovery.probe(sys.executable, '--version'))
    try:
        await asyncio.wait_for(spawned.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert process.returncode is not None
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if process is not None and process.returncode is None:
            os.killpg(process.pid, discovery.signal.SIGKILL)
            await process.wait()


@pytest.fixture
def rsa_material():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    metadata = {'kid': 'test-key', 'alg': 'RSA_OAEP_AES_256_GCM', 'envelopeVersion': '1',
                'expireAt': time.time() + 300,
                'publicKey': key.public_key().public_bytes(
                    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()}
    return key, metadata


def decrypt_request(key, payload):
    aes = key.decrypt(transport.decode(payload['ek']), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    body = json.loads(AESGCM(aes).decrypt(transport.decode(payload['iv']), transport.decode(payload['ct']),
                                       transport.json_bytes(payload['aad'])))
    return body, aes


@pytest.mark.asyncio
@pytest.mark.parametrize('encrypted,downgrade', [(False, False), (True, False), (True, True)])
async def test_enrollment_respects_crypto_configuration_and_never_downgrades(monkeypatch, rsa_material, encrypted, downgrade):
    private, metadata = rsa_material
    posts = []
    def handle(request):
        assert request.url.path.startswith('/api/')
        if request.url.path.endswith('/frontend-config'):
            return httpx.Response(200, json={'data': {'transportCryptoActive': encrypted, 'enabledPaths': ['/mindmap']}})
        if request.url.path.endswith('/public-key'):
            return httpx.Response(200, json={'data': metadata})
        posts.append(request)
        payload = json.loads(request.content)
        result = {'code': 200, 'data': {'deviceId': DEVICE_ID}}
        if encrypted:
            assert request.headers['x-transport-encrypt'] == '1'
            assert CONFIG['deviceSecret'] not in request.content.decode()
            assert payload['aad'] == {'method': 'POST', 'path': PATH}
            body, aes = decrypt_request(private, payload)
            assert body == {key: CONFIG[key] for key in ('deviceId', 'deviceSecret', 'pairingSecret')}
            if not downgrade:
                aad = {'method': 'POST', 'path': PATH, 'direction': 'response'}
                iv = b'i' * 12
                envelope = {'v': '1', 'kid': metadata['kid'], 'alg': 'AES_256_GCM', 'aad': aad,
                            'iv': transport.encode(iv),
                            'ct': transport.encode(AESGCM(aes).encrypt(iv, transport.json_bytes(result), transport.json_bytes(aad)))}
                return httpx.Response(200, json=envelope, headers={'x-body-encrypted': '1'})
        return httpx.Response(200, json=result)
    actual_client = httpx.AsyncClient
    def configured_client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return actual_client(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(client.httpx, 'AsyncClient', configured_client)
    if downgrade:
        with pytest.raises(client.BridgeError, match='拒绝降级'):
            await client.enroll(CONFIG)
    else:
        await client.enroll(CONFIG)
    assert len(posts) == 1


def test_ciphertext_is_bound_to_method_path_and_key(rsa_material):
    private, metadata = rsa_material
    request, key = transport.encrypt({'data': '测试'}, metadata, PATH)
    body, unwrapped = decrypt_request(private, request)
    assert body == {'data': '测试'} and key == unwrapped
    with pytest.raises(ValueError):
        transport.decrypt(request, key, metadata['kid'], PATH)
    with pytest.raises(ValueError):
        transport.encrypt({}, {**metadata, 'expireAt': 0}, PATH)
    with pytest.raises(ValueError):
        transport.encrypt({}, {**metadata, 'alg': 'none'}, PATH)


def test_crypto_path_matching_does_not_encrypt_excluded_or_unrelated_paths():
    assert transport.uses_envelope({'transportCryptoActive': True, 'enabledPaths': ['/mindmap']}, PATH)
    assert not transport.uses_envelope({'transportCryptoActive': True, 'enabledPaths': ['/mindmapx']}, PATH)
    assert not transport.uses_envelope({'transportCryptoActive': True, 'excludePaths': [PATH]}, PATH)
    with pytest.raises(ValueError):
        transport.uses_envelope({'transportCryptoActive': 'yes'}, PATH)


def test_lost_enrollment_response_reuses_persisted_key_without_reprompt(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'device.json'
    monkeypatch.setattr(sys, 'argv', ['bridge', '--config', str(path), 'pair', '--server', CONFIG['server']])
    monkeypatch.setattr(cli.getpass, 'getpass', lambda _prompt: DEVICE_ID + '.' + CONFIG['pairingSecret'])
    seen = []
    async def lost_response(config):
        assert client.read_config(path) == config  # durable before enrollment
        seen.append(dict(config))
        raise client.BridgeError('配对响应未确认')
    monkeypatch.setattr(cli, 'enroll', lost_response)
    with pytest.raises(SystemExit):
        cli.main()
    async def retry(config):
        assert config == seen[0]
    monkeypatch.setattr(cli, 'enroll', retry)
    monkeypatch.setattr(cli.getpass, 'getpass', lambda _prompt: pytest.fail('must reuse pending enrollment'))
    cli.main()
    assert 'pairingSecret' not in client.read_config(path)
    assert client.read_config(path)['deviceSecret'] == seen[0]['deviceSecret']
    output = capsys.readouterr()
    assert seen[0]['deviceSecret'] not in output.out + output.err
