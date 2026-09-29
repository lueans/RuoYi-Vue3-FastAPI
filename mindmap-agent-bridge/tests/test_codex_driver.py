"""Driver, credentials and policy tests. No provider model requests."""

import asyncio
import copy
import json
import os
import shutil
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from mindmap_agent_bridge import codex_driver
from mindmap_agent_bridge.codex_policy import (
    CLI_VERSION, CONFIG_POLICY, CodexPolicy, startup_arguments, validate_config,
)
from mindmap_agent_bridge.codex_session import INSTRUCTIONS, CodexSession
from mindmap_agent_bridge.execution import BridgeError, RunCleanupError, RunFailure, RunProtocolError, RunStopped
from mindmap_agent_bridge.process_owner import OwnedProcess
from test_codex_session import OFFER, Harness, completed, event, tool

OFFER = replace(OFFER, model_ref='gpt-5.6-terra')


def configuration():
    config = {}
    for dotted, value in CONFIG_POLICY.items():
        current = config
        *parts, last = dotted.split('.')
        for part in parts:
            current = current.setdefault(part, {})
        current[last] = copy.deepcopy(value)
    return {'config': copy.deepcopy(config), 'layers': [{'name': {'type': 'sessionFlags'}, 'config': config}],
            'origins': {key: {'name': {'type': 'sessionFlags'}} for key in CONFIG_POLICY}}


def usage(**changes):
    return {**{'inputTokens': 100, 'cachedInputTokens': 20, 'cacheWriteInputTokens': 0,
               'outputTokens': 20, 'reasoningOutputTokens': 10, 'totalTokens': 120}, **changes}


def token_event(total=None, **changes):
    return event('thread/tokenUsage/updated', tokenUsage={'total': total or usage(**changes), 'last': usage()})


class PolicyHarness(Harness):
    def __init__(self, frames, *, model='gpt-5.6-terra', account=True, skills=None):
        super().__init__(frames)
        self.model, self.account, self.skills = model, account, skills or []
        self.session.policy = CodexPolicy(OFFER)

    async def send(self, raw):
        request = json.loads(raw)
        method = request.get('method')
        replies = {
            'initialize': {'userAgent': f'mindmap-agent-bridge/{CLI_VERSION}'},
            'config/read': configuration(),
            'account/read': {'account': {'type': 'apiKey'} if self.account else None, 'requiresOpenaiAuth': True},
            'skills/list': {'data': [{'cwd': self.session.cwd, 'errors': [], 'skills': self.skills}]},
            'thread/start': {'thread': {'id': 'thread-private'}, 'model': self.model, 'modelProvider': 'openai',
                             'approvalPolicy': 'never', 'sandbox': {'type': 'readOnly'}, 'cwd': self.session.cwd},
        }
        if method not in replies:
            return await super().send(raw)
        self.sent.append(request)
        self.put({'id': request['id'], 'result': replies[method]})


def test_config_checks_raw_flags_effective_values_and_layers():
    validate_config(configuration())
    for layer in ({'name': {'type': 'user'}, 'config': {'mcp_servers': {'unsafe': {}}}},
                  {'name': {'type': 'system'}, 'config': {'instructions': 'hidden'}}):
        value = configuration()
        value['layers'].append(layer)
        with pytest.raises(RunFailure):
            validate_config(value)
    for place in ('config', 'raw'):
        value = configuration()
        target = value['config'] if place == 'config' else value['layers'][0]['config']
        target['features']['shell_tool'] = True
        with pytest.raises(RunFailure):
            validate_config(value)
    value = configuration()
    value['origins'].pop('tools.web_search')
    with pytest.raises(RunFailure):
        validate_config(value)
    value = configuration()
    value['config']['hooks'] = {'SessionStart': []}
    value['config']['apps'] = {'_default': None}
    value['config']['tools'] = {'web_search': None}
    validate_config(value)  # actual pinned response has normalized nullable fields
    value['config']['hooks']['SessionStart'] = [{'command': 'unexpected'}]
    with pytest.raises(RunFailure):
        validate_config(value)


@pytest.mark.asyncio
@pytest.mark.parametrize('change,code', [({'account': False}, 'AI_PROVIDER_AUTH_FAILED'),
                                       ({'model': 'different'}, 'AI_CAPABILITY_UNSUPPORTED'),
                                       ({'skills': [{'name': 'new-bundled-skill', 'enabled': False}]}, 'AI_CAPABILITY_UNSUPPORTED'),
                                       ({'skills': [{'name': 'imagegen', 'enabled': True}]}, 'AI_CAPABILITY_UNSUPPORTED')])
async def test_failed_preflight_never_sends_prompt_or_uses_tools(change, code):
    h = PolicyHarness([tool(), *completed()], **change)
    with pytest.raises(RunFailure) as failure:
        await h.run(OFFER)
    assert failure.value.code == code
    assert 'turn/start' not in [frame.get('method') for frame in h.sent]
    h.channel.tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_policy_uses_cumulative_usage_and_rejects_missing_final_usage():
    h = PolicyHarness([token_event(), tool(), *completed()])
    await h.run(OFFER)
    assert h.session.policy.estimated_cost == Decimal('0.000404')
    assert [v.get('method') for v in h.sent].count('skills/list') == 2
    h = PolicyHarness(completed())
    with pytest.raises(RunFailure) as failure:
        await h.run(OFFER)
    assert failure.value.code == 'AI_BUDGET_EXCEEDED'
    h = PolicyHarness([token_event(outputTokens=100_000, totalTokens=100_100), tool(), *completed()])
    with pytest.raises(RunFailure):
        await h.run(OFFER)
    h.channel.tool.assert_not_awaited()  # total, not deceptively small `last`


@pytest.mark.parametrize('changes', [
    {'inputTokens': True}, {'cachedInputTokens': -1}, {'cacheWriteInputTokens': 100},
    {'totalTokens': 121}, {'reasoningOutputTokens': 21}, {'outputTokens': '20'},
    {'inputTokens': 10**30}, {'cacheWriteInputTokens': False},
])
def test_invalid_usage_fails_closed(changes):
    policy = CodexPolicy(OFFER)
    with pytest.raises(RunFailure):
        policy.observe('thread/tokenUsage/updated', token_event(**changes)['params'])


def test_conservative_cache_write_long_context_and_nonmonotonic_usage():
    policy = CodexPolicy(replace(OFFER, max_budget_usd=100))
    first = usage(cacheWriteInputTokens=None)
    policy.observe('thread/tokenUsage/updated', {'tokenUsage': {'total': first}})
    assert policy.estimated_cost == Decimal('0.000444')
    long = usage(inputTokens=300_000, cachedInputTokens=0, cacheWriteInputTokens=None,
                 outputTokens=100, totalTokens=300_100)
    # cached counters must be monotonic; use a fresh policy for this example.
    policy = CodexPolicy(replace(OFFER, max_budget_usd=100))
    policy.observe('thread/tokenUsage/updated', {'tokenUsage': {'total': long}})
    assert policy.estimated_cost == Decimal('1.5018')
    with pytest.raises(RunFailure):
        policy.observe('thread/tokenUsage/updated', {'tokenUsage': {'total': first}})
    with pytest.raises(RunFailure) as failure:
        policy.observe('model/rerouted', {'toModel': 'different'})
    assert failure.value.code == 'AI_CAPABILITY_UNSUPPORTED'


@pytest.mark.asyncio
async def test_foreign_usage_and_rerouting_do_not_affect_current_run():
    foreign = token_event(outputTokens=100_000, totalTokens=100_100)
    foreign['params']['turnId'] = 'foreign'
    h = PolicyHarness([foreign, token_event(), *completed()])
    await h.run(OFFER)
    assert h.session.policy.estimated_cost == Decimal('0.000404')
    h = PolicyHarness([token_event(), event('model/rerouted', toModel='different'), tool()])
    with pytest.raises(RunFailure):
        await h.run(OFFER)
    h.channel.tool.assert_not_awaited()


def test_local_environment_is_private_and_auth_copy_never_changes_source(monkeypatch, tmp_path):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    local = tmp_path / 'local'
    local.mkdir()
    auth = local / 'auth.json'
    auth.write_text('{"tokens":{"access_token":"private-local-token"}}')
    (local / 'config.toml').write_text('private-config')
    monkeypatch.setenv('CODEX_HOME', str(local))
    monkeypatch.setenv('DATABASE_PASSWORD', 'private-db')
    monkeypatch.setenv('NODE_OPTIONS', '--require=/untrusted')
    isolated = tmp_path / 'isolated'
    isolated.mkdir()
    env = codex_driver.isolated_environment(isolated)
    assert not {'DATABASE_PASSWORD', 'NODE_OPTIONS', 'OPENAI_API_KEY'} & env.keys()
    codex_driver.stage_local_auth(env)
    target = Path(env['CODEX_HOME']) / 'auth.json'
    assert target.read_bytes() == auth.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    assert Path(env['CODEX_HOME']).stat().st_mode & 0o777 == 0o700
    assert not (target.parent / 'config.toml').exists()
    target.write_text('refreshed-private-copy')
    assert 'private-local-token' in auth.read_text()


def test_explicit_local_api_key_is_not_passed_in_child_environment_or_copied(monkeypatch, tmp_path):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-offline-test-credential')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'missing-original-login'))
    env = codex_driver.isolated_environment(tmp_path)
    assert codex_driver.stage_local_auth(env) == 'sk-offline-test-credential'
    assert 'OPENAI_API_KEY' not in env and 'sk-offline' not in json.dumps(env)
    assert not (Path(env['CODEX_HOME']) / 'auth.json').exists()


@pytest.mark.parametrize('kind', ['missing', 'symlink', 'fifo', 'directory', 'oversize', 'invalid'])
def test_auth_rejects_nonregular_unbounded_or_malformed_files(monkeypatch, tmp_path, kind):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    local = tmp_path / 'local'
    local.mkdir()
    monkeypatch.setenv('CODEX_HOME', str(local))
    auth = local / 'auth.json'
    if kind == 'symlink':
        other = local / 'elsewhere'
        other.write_text('{}')
        auth.symlink_to(other)
    elif kind == 'fifo':
        os.mkfifo(auth)
    elif kind == 'directory':
        auth.mkdir()
    elif kind == 'oversize':
        auth.write_bytes(b'x' * (codex_driver.MAX_AUTH_BYTES + 1))
    elif kind == 'invalid':
        auth.write_text('private invalid json')
    with pytest.raises(RunFailure) as failure:
        codex_driver.stage_local_auth({'CODEX_HOME': str(tmp_path)})
    assert failure.value.code == 'AI_PROVIDER_AUTH_FAILED'
    assert 'private' not in str(failure.value)


@pytest.mark.parametrize('key', ['', ' ', 'bad\nkey', 'bad\rkey', 'x' * 16_385])
def test_invalid_explicit_key_never_falls_back_to_other_login(monkeypatch, tmp_path, key):
    monkeypatch.setenv('OPENAI_API_KEY', key)
    with pytest.raises(RunFailure):
        codex_driver.stage_local_auth({'CODEX_HOME': str(tmp_path)})


def test_constructor_pins_package_and_does_not_read_local_login(monkeypatch):
    monkeypatch.setattr(codex_driver, 'version', lambda _: '0.141.0')
    with pytest.raises(BridgeError, match='版本'):
        codex_driver.CodexRunDriver()
    monkeypatch.setattr(codex_driver, 'version', lambda _: CLI_VERSION)
    monkeypatch.setattr(codex_driver, 'stage_local_auth', lambda _: pytest.fail('constructor read credentials'))
    driver = codex_driver.CodexRunDriver()
    assert Path(driver.binary).is_absolute()
    assert driver._directory is None and driver.owner.process is None


def mock_driver(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-offline-test-credential')
    for key in ('DATABASE_PASSWORD', 'NODE_OPTIONS', 'HTTP_PROXY', 'ANTHROPIC_API_KEY'):
        monkeypatch.setenv(key, 'private-never-forward')
    monkeypatch.setattr(codex_driver, 'bundled_binary', lambda: sys.executable)
    driver = codex_driver.CodexRunDriver()
    start = driver.owner.start
    async def launch(argv, **kwargs):
        mock = str(Path(__file__).with_name('fixtures') / 'codex_driver_mock.py')
        return await start([argv[0], '-I', mock, *argv[1:]], **kwargs)
    monkeypatch.setattr(driver.owner, 'start', launch)
    return driver


@pytest.mark.asyncio
async def test_real_driver_stdio_tools_public_stream_and_verified_cleanup(monkeypatch):
    driver, channel = mock_driver(monkeypatch), Harness([]).channel
    result = await asyncio.wait_for(driver.run(OFFER, channel), 5)
    assert result['title'] == '离线驱动测试'
    assert [call.args[0] for call in channel.tool.await_args_list] == ['update_plan', 'add_nodes', 'complete_artifact']
    assert ''.join(call.args[0] for call in channel.public_text.await_args_list) == '正在整理脑图。'
    assert not driver.owner._alive() and not Path(driver._directory).exists()
    await driver.stop()  # idempotent cleanup
    with pytest.raises(RunProtocolError):
        await driver.run(OFFER, channel)


@pytest.mark.asyncio
@pytest.mark.parametrize('prompt', ['missing-usage', 'over-budget'])
async def test_driver_failed_budget_is_not_a_success_and_cleans_process(monkeypatch, prompt):
    driver, channel = mock_driver(monkeypatch), Harness([]).channel
    with pytest.raises(RunFailure) as failure:
        await asyncio.wait_for(driver.run(replace(OFFER, prompt=prompt), channel), 5)
    assert failure.value.code == 'AI_BUDGET_EXCEEDED'
    assert not driver.owner._alive() and not Path(driver._directory).exists()
    if prompt == 'over-budget':
        channel.tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_driver_cancel_during_model_work_stops_before_removing_private_home(monkeypatch):
    driver, channel = mock_driver(monkeypatch), Harness([]).channel
    ready = asyncio.Event()
    channel.public_text.side_effect = lambda *args, **kwargs: ready.set()
    task = asyncio.create_task(driver.run(replace(OFFER, prompt='interrupt-test'), channel))
    try:
        await asyncio.wait_for(ready.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert not driver.owner._alive() and not Path(driver._directory).exists()
        channel.tool.assert_not_awaited()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await driver.stop()


@pytest.mark.asyncio
async def test_cleanup_uncertainty_cannot_remove_private_home_or_return_success(monkeypatch):
    driver = mock_driver(monkeypatch)
    owner_stop = driver.owner.stop
    async def uncertain():
        await owner_stop()  # do not actually leave a child behind in this test
        raise RunCleanupError
    monkeypatch.setattr(driver.owner, 'stop', uncertain)
    try:
        with pytest.raises(RunCleanupError):
            await asyncio.wait_for(driver.run(OFFER, Harness([]).channel), 5)
        assert Path(driver._directory).is_dir()
        assert not driver.owner._alive()
    finally:
        await owner_stop()
        if driver._directory is not None:
            shutil.rmtree(driver._directory)


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_cancel_or_stop_during_spawn_cannot_leave_a_late_child(monkeypatch, cancel):
    driver, channel = mock_driver(monkeypatch), Harness([]).channel
    launch = driver.owner.start
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await launch(*args, **kwargs)
    monkeypatch.setattr(driver.owner, 'start', delayed)
    task = asyncio.create_task(driver.run(OFFER, channel))
    await asyncio.wait_for(entered.wait(), 1)
    stop = asyncio.create_task(driver.stop())
    if cancel:
        task.cancel()
    await asyncio.sleep(0)
    assert not stop.done()
    release.set()
    await asyncio.wait_for(stop, 5)
    with pytest.raises(asyncio.CancelledError if cancel else RunStopped):
        await task
    assert not driver.owner._alive() and not Path(driver._directory).exists()
    channel.tool.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('model', [None, 'unknown-model'])
async def test_unpriced_model_fails_before_reading_credentials(monkeypatch, model):
    driver = mock_driver(monkeypatch)
    monkeypatch.setattr(codex_driver, 'stage_local_auth', lambda _: pytest.fail('read credential'))
    with pytest.raises(RunFailure) as failure:
        await driver.run(replace(OFFER, model_ref=model), Harness([]).channel)
    assert failure.value.code == 'AI_CAPABILITY_UNSUPPORTED'
    assert driver.owner.process is None and driver._directory is None


@pytest.mark.asyncio
@pytest.mark.parametrize('fake_key', [False, True])
@pytest.mark.skipif(os.environ.get('MINDMAP_CODEX_PREFLIGHT') != '1', reason='explicit offline pinned CLI preflight')
async def test_real_pinned_cli_offline_config_skills_and_no_login(tmp_path, fake_key):
    # Never read user auth/env or call turn/start. A fake key exercises LOCAL
    # auth persistence, not provider authentication or a valid paid account.
    env = codex_driver.isolated_environment(tmp_path)
    cwd = tmp_path / 'workspace'
    cwd.mkdir(mode=0o700)
    owner = OwnedProcess()
    try:
        process = await owner.start([codex_driver.bundled_binary(), *startup_arguments(), 'app-server'],
                                    cwd=str(cwd), env=env)
        async def send(raw):
            process.stdin.write(raw.encode())
            await process.stdin.drain()
        session = CodexSession(process.stdout.readline, send, cwd=str(cwd))
        initialized = await session._request('initialize', {
            'clientInfo': {'name': 'mindmap-agent-bridge', 'version': '0.1.0'},
            'capabilities': {'experimentalApi': True},
        })
        assert initialized['userAgent'].split(' ')[0].endswith('/' + CLI_VERSION)
        await session._send({'method': 'initialized', 'params': {}})
        validate_config(await session._request('config/read', {'cwd': str(cwd), 'includeLayers': True}))
        if fake_key:
            policy = CodexPolicy(OFFER)
            policy.local_api_key = 'sk-offline-test-credential'
            await policy._login_local_key(session)
            assert policy.local_api_key is None
        account = await session._request('account/read', {'refreshToken': False})
        assert account == {'account': {'type': 'apiKey'} if fake_key else None, 'requiresOpenaiAuth': True}
        await CodexPolicy(OFFER)._skills(session)
        # A new ephemeral thread itself does not submit a model turn. Check
        # the runtime's resolved permissions/model, still with no login/key.
        thread = await session._request('thread/start', {
            'cwd': str(cwd), 'model': OFFER.model_ref, 'approvalPolicy': 'never', 'sandbox': 'read-only',
            'ephemeral': True, 'baseInstructions': INSTRUCTIONS, 'developerInstructions': INSTRUCTIONS,
            'dynamicTools': [{'type': 'function', 'name': f'mindmap_{tool["name"]}',
                              'description': tool['description'], 'inputSchema': tool['inputSchema'],
                              'deferLoading': False} for tool in OFFER.tools],
        })
        await CodexPolicy(OFFER).before_turn(session, OFFER, thread)
        assert (Path(env['CODEX_HOME']) / 'auth.json').exists() is fake_key
    finally:
        await owner.stop()
    assert not owner._alive()
