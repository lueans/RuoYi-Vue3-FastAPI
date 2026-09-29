"""Crash recovery uses only test-owned directories and disposable processes."""

import asyncio
import contextlib
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

psutil = pytest.importorskip('psutil')

from mindmap_agent_bridge import run_recovery as recovery
from mindmap_agent_bridge.process_owner import OwnedProcess


def test_workspace_records_only_private_ownership_metadata(tmp_path):
    run = recovery.OwnedRun.create('kimi', root=tmp_path / 'runs')
    assert stat.S_IMODE(run.path.stat().st_mode) == 0o700
    record = json.loads((run.path / 'owner.json').read_text())
    assert set(record) == {'version', 'agent', 'ownerPid', 'ownerStartedAt'}
    assert record['ownerPid'] == os.getpid() and record['agent'] == 'kimi'
    assert stat.S_IMODE((run.path / 'owner.json').stat().st_mode) == 0o600
    run.cleanup()
    assert not run.path.exists()


@pytest.mark.asyncio
async def test_active_bridge_is_never_reaped(tmp_path):
    root = tmp_path / 'runs'
    run = recovery.OwnedRun.create('claude', root=root)
    result = await recovery.recover_runs(root=root)
    assert result == {'recovered': 0, 'active': 1, 'unresolved': 0}
    assert run.path.exists()
    run.cleanup()


@pytest.mark.asyncio
async def test_spawn_is_durably_registered_before_the_program_receives_input(tmp_path):
    run = recovery.OwnedRun.create('codex', root=tmp_path / 'runs')
    owner = OwnedProcess()
    try:
        process = await owner.start([sys.executable, '-c', 'print("ready",flush=True); input()'],
                                    env={}, cwd=run.path, workspace=run)
        assert await asyncio.wait_for(process.stdout.readline(), 3) == b'ready\n'
        records = [json.loads(path.read_text()) for path in run.path.glob('process-*.json')]
        assert len(records) == 1 and records[0]['phase'] == 'started'
        assert records[0]['pid'] == process.pid
        assert records[0]['startedAt'] == psutil.Process(process.pid).create_time()
        with pytest.raises(recovery.RecoveryError):
            run.cleanup()  # no deleting credentials while its program runs
    finally:
        await owner.stop()
        run.cleanup()


def crashed_run(root, child_code='import time; print("ready",flush=True); time.sleep(30)'):
    package = Path(__file__).resolve().parents[1]
    code = '''
import asyncio, json, os, signal, sys
sys.path.insert(0, sys.argv[1])
from mindmap_agent_bridge.run_recovery import OwnedRun
from mindmap_agent_bridge.process_owner import OwnedProcess
async def main():
    run = OwnedRun.create('kimi', root=sys.argv[2])
    (run.path / 'credential-copy').write_text('fake-private-test-only')
    owner = OwnedProcess()
    proc = await owner.start([sys.executable, '-c', sys.argv[3]],
                             env={}, cwd=run.path, workspace=run)
    assert await proc.stdout.readline() == b'ready\\n'
    print(json.dumps({'path':str(run.path),'pid':proc.pid,'startedAt':owner.created_at}),flush=True)
    os.kill(os.getpid(), signal.SIGKILL)
asyncio.run(main())
'''
    result = subprocess.run([sys.executable, '-I', '-c', code, str(package), str(root), child_code],
                            capture_output=True, text=True, timeout=6)
    assert result.returncode == -signal.SIGKILL, result.stderr
    return json.loads(result.stdout)


def finish_test_process(record):
    # Exact process created by this test only, guarded against PID recycling.
    try:
        process = psutil.Process(record['pid'])
        if process.create_time() == record['startedAt']:
            os.killpg(record['pid'], signal.SIGKILL)
    except (psutil.NoSuchProcess, ProcessLookupError):
        pass


@pytest.mark.asyncio
async def test_abrupt_bridge_exit_is_recovered_before_private_directory_is_removed(tmp_path):
    root = tmp_path / 'runs'
    record = crashed_run(root)
    try:
        assert psutil.pid_exists(record['pid'])
        assert await recovery.recover_runs(root=root) == {'recovered': 1, 'active': 0, 'unresolved': 0}
        assert not Path(record['path']).exists()
        assert await recovery.recover_runs(root=root) == {'recovered': 0, 'active': 0, 'unresolved': 0}
    finally:
        finish_test_process(record)


@pytest.mark.asyncio
async def test_recovery_escalates_for_a_child_that_outlives_its_verified_leader(tmp_path, monkeypatch):
    root = tmp_path / 'runs'
    child = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("child",flush=True); time.sleep(30)'
    code = ('import subprocess,sys,time; child=subprocess.Popen([sys.executable,"-c",' + repr(child) + '],'
            'stdout=subprocess.PIPE); assert child.stdout.readline()==b"child\\n"; '
            'print("ready",flush=True); time.sleep(30)')
    record = crashed_run(root, code)
    descendants = psutil.Process(record['pid']).children()
    assert len(descendants) == 1
    signals, send = [], recovery.signal_group
    def track(pid, sig):
        signals.append((pid, sig))
        send(pid, sig)
    monkeypatch.setattr(recovery, 'signal_group', track)
    try:
        assert (await recovery.recover_runs(root=root))['recovered'] == 1
        assert signals == [(record['pid'], signal.SIGTERM), (record['pid'], signal.SIGKILL)]
        assert not Path(record['path']).exists()
        for child in descendants:
            with contextlib.suppress(psutil.NoSuchProcess):
                assert child.status() in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}
    finally:
        finish_test_process(record)
        for child in descendants:
            with contextlib.suppress(psutil.NoSuchProcess):
                child.kill()  # psutil Process retains this test child's birth time


@pytest.mark.asyncio
async def test_recycled_pid_keeps_record_and_credentials_without_signalling(tmp_path, monkeypatch):
    root = tmp_path / 'runs'
    record = crashed_run(root)
    try:
        path = next(Path(record['path']).glob('process-*.json'))
        value = json.loads(path.read_text())
        value['startedAt'] -= 100  # no longer proves ownership of this PID
        path.write_text(json.dumps(value))
        signals = Mock(side_effect=AssertionError('must not signal mismatched process'))
        monkeypatch.setattr(recovery, 'signal_group', signals)
        assert await recovery.recover_runs(root=root) == {'recovered': 0, 'active': 0, 'unresolved': 1}
        signals.assert_not_called()
        assert (Path(record['path']) / 'credential-copy').exists()
    finally:
        finish_test_process(record)


@pytest.mark.asyncio
async def test_failed_termination_retains_credentials_and_blocks_recovery(tmp_path, monkeypatch):
    root = tmp_path / 'runs'
    record = crashed_run(root)
    try:
        monkeypatch.setattr(recovery, 'signal_group', Mock(side_effect=PermissionError))
        assert (await recovery.recover_runs(root=root))['unresolved'] == 1
        assert (Path(record['path']) / 'credential-copy').exists()
        assert psutil.Process(record['pid']).is_running()
    finally:
        finish_test_process(record)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['corrupt', 'symlink', 'public', 'foreign-path', 'deep-json', 'duplicate-key'])
async def test_unverifiable_record_never_deletes_other_data(tmp_path, case):
    root = tmp_path / 'runs'
    run = recovery.OwnedRun.create('claude', root=root)
    target = tmp_path / 'outside'
    target.mkdir()
    (target / 'keep').write_text('user data')
    owner = run.path / 'owner.json'
    if case == 'corrupt':
        owner.write_text('invalid')
    elif case == 'symlink':
        owner.unlink()
        owner.symlink_to(target / 'keep')
    elif case == 'public':
        owner.chmod(0o644)
    elif case == 'deep-json':
        owner.write_text('[' * 1500 + '0' + ']' * 1500)
    elif case == 'duplicate-key':
        owner.write_text(owner.read_text().replace('"version": 1', '"version": 2, "version": 1'))
    else:
        value = json.loads(owner.read_text())
        value['directory'] = str(target)
        owner.write_text(json.dumps(value))
    result = await recovery.recover_runs(root=root)
    assert result['unresolved'] == 1 and result['recovered'] == 0
    assert (target / 'keep').read_text() == 'user data'
    assert run.path.exists()


@pytest.mark.asyncio
async def test_symlink_run_and_symlink_registry_are_rejected(tmp_path):
    root = tmp_path / 'runs'
    root.mkdir(mode=0o700)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep').write_text('user data')
    (root / ('a' * 32)).symlink_to(outside, target_is_directory=True)
    assert (await recovery.recover_runs(root=root))['unresolved'] == 1
    alias = tmp_path / 'alias'
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(recovery.RecoveryError):
        await recovery.recover_runs(root=alias)
    assert (outside / 'keep').exists()


@pytest.mark.parametrize('case', ['record_failure', 'owner_changed', 'replayed_slot'])
def test_bootstrap_never_execs_without_a_durable_current_owner_record(tmp_path, case):
    run = recovery.OwnedRun.create('codex', root=tmp_path / 'runs')
    slot = run.prepare_launch()
    if case == 'owner_changed':
        owner = json.loads((run.path / 'owner.json').read_text())
        owner['ownerStartedAt'] -= 100
        (run.path / 'owner.json').write_text(json.dumps(owner))
    elif case == 'replayed_slot':
        (run.path / slot).write_text(json.dumps({'version': 1, 'phase': 'started',
                                               'pid': os.getpid(), 'startedAt': psutil.Process().create_time()}))
    else:
        run.path.chmod(0o500)  # bootstrap can read but cannot persist identity
    try:
        result = subprocess.run([sys.executable, '-I', str(recovery.BOOTSTRAP), str(run.path), slot,
                                 sys.executable, '-c', 'print("must-not-execute")'],
                                start_new_session=True, capture_output=True, timeout=3)
        assert result.returncode == 78 and not result.stdout
    finally:
        run.path.chmod(0o700)
        (run.path / slot).unlink()  # exact fake record; target never executed
        run.cleanup()


@pytest.mark.asyncio
async def test_missing_leader_with_live_group_is_retained_without_guessing_ownership(tmp_path, monkeypatch):
    root = tmp_path / 'runs'
    record = crashed_run(root)
    actual = recovery.psutil.Process
    def without_leader(pid=None):
        if pid == record['pid']:
            raise psutil.NoSuchProcess(pid)
        return actual(pid)
    try:
        monkeypatch.setattr(recovery.psutil, 'Process', without_leader)
        monkeypatch.setattr(recovery, '_group_alive', lambda _pid: True)
        signals = Mock(side_effect=AssertionError('no witness for this group'))
        monkeypatch.setattr(recovery, 'signal_group', signals)
        assert (await recovery.recover_runs(root=root))['unresolved'] == 1
        signals.assert_not_called()
        assert Path(record['path']).exists()
    finally:
        monkeypatch.setattr(recovery.psutil, 'Process', actual)
        finish_test_process(record)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['unresolved', 'unreadable'])
async def test_execution_startup_cannot_connect_before_recovery_is_confirmed(tmp_path, monkeypatch, failure):
    from mindmap_agent_bridge import execution_client
    reconcile = AsyncMock(return_value={'recovered': 0, 'active': 0, 'unresolved': 1})
    if failure == 'unreadable':
        reconcile.side_effect = recovery.RecoveryError('private path must not be printed')
    monkeypatch.setattr(recovery, 'recover_runs', reconcile)
    discovery, execution = AsyncMock(), AsyncMock()
    monkeypatch.setattr(execution_client, 'run', discovery)
    monkeypatch.setattr(execution_client, 'run_execution', execution)
    with pytest.raises(execution_client.BridgeError) as caught:
        await execution_client.run_with_execution({})
    assert 'private path' not in str(caught.value)
    discovery.assert_not_awaited()
    execution.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_recovery_precedes_both_connections(monkeypatch):
    from mindmap_agent_bridge import execution_client
    order = []
    async def reconcile():
        order.append('recovered')
        return {'recovered': 1, 'active': 1, 'unresolved': 0}
    async def connection(_config, **_kwargs):
        assert order == ['recovered']
    monkeypatch.setattr(recovery, 'recover_runs', reconcile)
    monkeypatch.setattr(execution_client, 'run', connection)
    monkeypatch.setattr(execution_client, 'run_execution', connection)
    await execution_client.run_with_execution({})
