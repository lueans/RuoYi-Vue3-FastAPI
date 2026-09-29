"""Local installation checks must not borrow login state or execute a run."""

import asyncio
import importlib
import json
import os
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mindmap_agent_bridge import cli, discovery
from mindmap_agent_bridge.client import BridgeError


def diagnostics():
    return importlib.import_module('mindmap_agent_bridge.diagnostics')


@pytest.mark.parametrize('passed', [True, False])
def test_doctor_is_available_before_pairing_and_does_not_read_device_config(monkeypatch, capsys, passed):
    monkeypatch.setattr('sys.argv', ['bridge', 'doctor', '--agent', 'claude'])
    monkeypatch.setattr(cli, 'read_config', lambda _: pytest.fail('doctor must not read pairing secrets'))
    check = AsyncMock(return_value=[{'agentKey': 'claude', 'installationStatus': 'passed' if passed else 'blocked',
                                   'authenticationStatus': 'not_checked', 'executionAvailable': False}])
    monkeypatch.setattr(diagnostics(), 'diagnose', check)
    code = 0
    try:
        cli.main()
    except SystemExit as result:
        code = result.code
    assert code == (0 if passed else 1)
    check.assert_awaited_once_with(('claude',))
    records = json.loads(capsys.readouterr().out)
    assert [record['agentKey'] for record in records] == ['claude']
    assert records[0]['authenticationStatus'] == 'not_checked'
    assert records[0]['executionAvailable'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('agent,raw,expected', [
    ('claude', '2.1.276 (Claude Code)', None),
    ('codex', 'codex-cli 0.147.0', '0.147.0'),
    ('kimi', '2.1.1', '2.1.1'),
])
async def test_installed_is_never_authenticated_or_execution_ready(monkeypatch, agent, raw, expected):
    module = diagnostics()
    monkeypatch.setattr(module, 'installation_binary', lambda key: ('/private/test-agent', expected))
    probe = AsyncMock(return_value=raw)
    monkeypatch.setattr(module, 'probe', probe)
    result = await module.diagnose_agent(agent)
    assert result['installationStatus'] == 'passed'
    assert result['authenticationStatus'] == 'not_checked'
    assert result['executionAvailable'] is False
    assert '/private' not in json.dumps(result)
    probe.assert_awaited_once_with('/private/test-agent', '--version', isolated_home=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('agent,raw,expected', [
    ('codex', 'codex-cli 0.141.0', '0.147.0'),
    ('kimi', '1.34.0', '2.1.1'),
    ('kimi', '2.1.1-unverified', '2.1.1'),
    ('claude', 'private diagnostic without a version', None),
])
async def test_wrong_or_unrecognized_versions_are_not_passed(monkeypatch, agent, raw, expected):
    module = diagnostics()
    monkeypatch.setattr(module, 'installation_binary', lambda key: ('/private/test-agent', expected))
    monkeypatch.setattr(module, 'probe', AsyncMock(return_value=raw))
    result = await module.diagnose_agent(agent)
    assert result['installationStatus'] == 'blocked'
    assert result['executionAvailable'] is False
    assert 'private diagnostic' not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [ImportError('private module path'), PackageNotFoundError('private metadata'),
                                   OSError('private binary path'), asyncio.TimeoutError()])
async def test_incomplete_install_or_probe_failure_has_a_safe_repair_hint(monkeypatch, failure):
    module = diagnostics()
    def fail(_):
        raise failure
    monkeypatch.setattr(module, 'installation_binary', fail)
    result = await module.diagnose_agent('kimi')
    assert result['installationStatus'] == 'blocked'
    assert '[kimi]' in result['installCommand']
    assert 'private' not in json.dumps(result)


@pytest.mark.asyncio
async def test_missing_runtime_preserves_trusted_user_action_but_does_not_probe(monkeypatch):
    module = diagnostics()
    def missing(_):
        raise BridgeError('未找到本机 Kimi Code CLI；需要已验证的 2.1.1 版本')
    monkeypatch.setattr(module, 'installation_binary', missing)
    probe = AsyncMock()
    monkeypatch.setattr(module, 'probe', probe)
    result = await module.diagnose_agent('kimi')
    assert result['installationStatus'] == 'blocked'
    assert '未找到' in result['message']
    probe.assert_not_awaited()


def test_codex_checks_the_bundled_binary_not_a_path_installation(monkeypatch):
    from mindmap_agent_bridge import codex_driver
    monkeypatch.setattr(codex_driver, 'bundled_binary', lambda: '/test/bundled-codex')
    monkeypatch.setattr(discovery, 'resolve_binary', lambda _: pytest.fail('must not borrow PATH Codex'))
    assert diagnostics().installation_binary('codex') == ('/test/bundled-codex', '0.147.0')


@pytest.mark.asyncio
async def test_diagnostic_probe_has_private_home_and_no_auth_environment(monkeypatch):
    reader = SimpleNamespace(read=AsyncMock(side_effect=[b'1.2.3', b'']))
    process = SimpleNamespace(stdout=reader, wait=AsyncMock(), pid=3456, returncode=0)
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(discovery.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(discovery.os, 'killpg', lambda *_: None)
    for key in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'KIMI_API_KEY', 'CODEX_HOME', 'NODE_OPTIONS'):
        monkeypatch.setenv(key, 'private-never-read')
    assert await discovery.probe('/test/agent', '--version', isolated_home=True) == '1.2.3'
    environment = spawn.call_args.kwargs['env']
    assert environment['HOME'] != str(Path.home())
    for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME'):
        assert environment[key].startswith(spawn.call_args.kwargs['cwd'] + os.sep)
    assert 'private-never-read' not in json.dumps(environment)
    assert not Path(environment['HOME']).exists(), 'owned diagnostic directory is removed'


@pytest.mark.asyncio
async def test_unknown_agent_is_rejected_before_import_or_probe(monkeypatch):
    module = diagnostics()
    monkeypatch.setattr(module, 'installation_binary', lambda _: pytest.fail('unrecognized agent'))
    with pytest.raises(ValueError):
        await module.diagnose_agent('custom-shell')


@pytest.mark.asyncio
@pytest.mark.parametrize('agent', ['claude', 'codex', 'kimi'])
async def test_scan_only_install_reports_missing_execution_extra_without_running_a_probe(monkeypatch, agent):
    module = diagnostics()
    original = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, 'find_spec', lambda name: None if name == 'psutil' else original(name))
    probe = AsyncMock()
    monkeypatch.setattr(module, 'probe', probe)
    result = await module.diagnose_agent(agent)
    assert result['installationStatus'] == 'blocked'
    assert '可选依赖' in result['message']
    probe.assert_not_awaited()


def test_cli_deduplicates_only_explicit_agent_choices(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['bridge', 'doctor', '--agent', 'codex', '--agent', 'codex'])
    check = AsyncMock(return_value=[{'agentKey': 'codex', 'installationStatus': 'passed'}])
    monkeypatch.setattr(diagnostics(), 'diagnose', check)
    cli.main()
    check.assert_awaited_once_with(('codex',))
    assert len(json.loads(capsys.readouterr().out)) == 1
