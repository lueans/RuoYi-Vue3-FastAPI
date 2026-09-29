"""Private run ownership journal, adapted from Open Design agent-process.ts.

No prompt, credential, remote path or arbitrary command is stored. A bootstrap
records its own PID BEFORE exec, closing the parent's spawn/record crash gap.
Unverifiable groups are retained, never guessed or claimed as stopped.
"""

import asyncio
import contextlib
import fcntl
import json
import math
import os
import re
import shutil
import signal
import stat
import sys
import weakref
from pathlib import Path
from itertools import islice
from uuid import uuid4

import psutil

BOOTSTRAP = Path(__file__).resolve()
RUN_NAME = re.compile(r'[a-f0-9]{32}')
PROCESS_NAME = re.compile(r'process-[a-f0-9]{32}\.json')


class RecoveryError(RuntimeError):
    pass


def run_root():
    return Path.home() / '.local/state/mindmap-agent-bridge/runs'


def _private(info, *, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
            or (not directory and info.st_nlink != 1)):
        raise RecoveryError('Untrusted run journal')


def _root(value):
    path = Path(value) if value is not None else run_root()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private(path.lstat(), directory=True)
    return path.resolve()


def _open_lock(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        _private(os.fstat(fd))
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextlib.contextmanager
def _registration_lock(path):
    fd = _open_lock(path / '.registration-lock')
    try:
        yield
    finally:
        os.close(fd)


def _read(path):
    def unique_fields(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise RecoveryError('Duplicate run journal field')
            value[key] = item
        return value
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        _private(info)
        if info.st_size > 4096:
            raise RecoveryError('Oversized run journal')
        try:
            value = json.loads(handle.read(4097), object_pairs_hook=unique_fields)
        except (ValueError, RecursionError):
            raise RecoveryError('Invalid run journal') from None
    if not isinstance(value, dict):
        raise RecoveryError('Invalid run journal')
    return value


def _write(directory, name, value):
    temporary = directory / ('.journal-' + uuid4().hex)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / name)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _identity(pid, started):
    return type(pid) is int and pid > 1 and type(started) in {int, float} and math.isfinite(started) and started > 0


def _owner(path):
    value = _read(path / 'owner.json')
    if (set(value) != {'version', 'agent', 'ownerPid', 'ownerStartedAt'} or type(value['version']) is not int
            or value['version'] != 1 or value['agent'] not in {'claude', 'codex', 'kimi'}
            or not _identity(value['ownerPid'], value['ownerStartedAt'])):
        raise RecoveryError('Invalid run owner')
    return value


def _owner_alive(owner):
    try:
        process = psutil.Process(owner['ownerPid'])
        return (process.create_time() == owner['ownerStartedAt']
                and process.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD})
    except psutil.NoSuchProcess:
        return False


def _records(path):
    records = []
    for entry in path.iterdir():
        if not entry.name.startswith('process-'):
            continue
        if not PROCESS_NAME.fullmatch(entry.name) or len(records) >= 8:
            raise RecoveryError('Invalid run process list')
        record = _read(entry)
        if record == {'version': 1, 'phase': 'pending'} and type(record['version']) is int:
            records.append(record)
        elif (set(record) == {'version', 'phase', 'pid', 'startedAt'} and type(record['version']) is int
              and record['version'] == 1 and record['phase'] == 'started'
              and _identity(record['pid'], record['startedAt'])):
            records.append(record)
        else:
            raise RecoveryError('Invalid run process')
    return records


def _group_alive(pid):
    if pid <= 1 or pid == os.getpgrp():
        raise RecoveryError('Unsafe process group')
    for member in psutil.process_iter(['pid', 'status']):
        try:
            if os.getpgid(member.pid) == pid and member.status() not in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
                return True
        except (ProcessLookupError, psutil.NoSuchProcess):
            continue
    return False


def _owned_alive(record, *, verified_here=False):
    if record['phase'] == 'pending':
        return False  # bootstrap cannot exec until it replaces this under lock
    pid = record['pid']
    try:
        process = psutil.Process(pid)
        if process.create_time() != record['startedAt'] or os.getpgid(pid) != pid:
            raise RecoveryError('Process identity changed')
    except (psutil.NoSuchProcess, ProcessLookupError):
        if not verified_here and _group_alive(pid):
            # An old PID with leader gone might now identify an unrelated
            # recycled session. No durable witness: retain, do not signal.
            raise RecoveryError('Process leader cannot be verified')
    return _group_alive(pid)


def signal_group(pid, sig):
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, sig)


async def _stop(record):
    if not _owned_alive(record):
        return
    # Ownership proved in THIS reconciliation; descendants can now be waited
    # for even if the verified leader exits in response to our TERM.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _owned_alive(record, verified_here=True):
            return
        signal_group(record['pid'], sig)
        deadline = asyncio.get_running_loop().time() + 1.5
        while _owned_alive(record, verified_here=True) and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(.03)
    if _owned_alive(record, verified_here=True):
        raise RecoveryError('Process group survived')


def _remove(path, identity):
    current = path.lstat()
    _private(current, directory=True)
    if (current.st_dev, current.st_ino) != identity or not shutil.rmtree.avoids_symlink_attacks:
        raise RecoveryError('Run directory changed')
    shutil.rmtree(path)  # exact validated UUID child, never the registry root


class OwnedRun:
    def __init__(self, path, owner_fd):
        self.path = path
        self._release_owner = weakref.finalize(self, os.close, owner_fd)
        info = path.lstat()
        self._identity = info.st_dev, info.st_ino
        self._removed = False

    @classmethod
    def create(cls, agent, *, root=None):
        if agent not in {'claude', 'codex', 'kimi'}:
            raise RecoveryError('Unknown run agent')
        path = _root(root) / uuid4().hex
        path.mkdir(mode=0o700)
        fd = _open_lock(path / '.owner-lock')
        run = cls(path, fd)
        try:
            _write(path, 'owner.json', {'version': 1, 'agent': agent, 'ownerPid': os.getpid(),
                                      'ownerStartedAt': psutil.Process().create_time()})
            return run
        except BaseException:
            run._release_owner()
            _remove(path, run._identity)  # no process or credential has existed
            raise

    def prepare_launch(self):
        if self._removed or _owner(self.path)['ownerPid'] != os.getpid():
            raise RecoveryError('Run is not owned by this bridge')
        with _registration_lock(self.path):
            if len(_records(self.path)) >= 8:
                raise RecoveryError('Too many run processes')
            name = 'process-' + uuid4().hex + '.json'
            _write(self.path, name, {'version': 1, 'phase': 'pending'})
            return name

    def cleanup(self):
        if self._removed:
            return
        with _registration_lock(self.path):
            if any(_owned_alive(record) for record in _records(self.path)):
                raise RecoveryError('Run still has live processes')
            _remove(self.path, self._identity)
            self._removed = True
            self._release_owner()


async def recover_runs(*, root=None):
    result = {'recovered': 0, 'active': 0, 'unresolved': 0}
    try:
        registry = _root(root)
        with os.scandir(registry) as listing:
            entries = [registry / entry.name for entry in islice(listing, 129)]
        if len(entries) > 128:
            raise RecoveryError('Too many run journals')
        for path in entries:
            owner_fd = None
            try:
                if not RUN_NAME.fullmatch(path.name):
                    raise RecoveryError('Unknown registry entry')
                info = path.lstat()
                _private(info, directory=True)
                owner = _owner(path)
                try:
                    owner_fd = _open_lock(path / '.owner-lock')
                except BlockingIOError:
                    result['active'] += 1
                    continue
                with _registration_lock(path):
                    if _owner_alive(owner):
                        result['active'] += 1
                        continue
                    records = _records(path)
                    # Validate ALL ownership before mutating any process.
                    for record in records:
                        _owned_alive(record)
                    for record in records:
                        await _stop(record)
                    _remove(path, (info.st_dev, info.st_ino))
                    result['recovered'] += 1
            except (RecoveryError, OSError, ValueError, TypeError, psutil.Error):
                result['unresolved'] += 1
            finally:
                if owner_fd is not None:
                    os.close(owner_fd)
        return result
    except (OSError, ValueError, psutil.Error) as exc:
        raise RecoveryError('Run registry is unavailable') from exc


def bootstrap(arguments):
    path, name, *command = arguments
    path = Path(path)
    if not RUN_NAME.fullmatch(path.name) or not PROCESS_NAME.fullmatch(name) or not command:
        raise RecoveryError('Invalid launch')
    _private(path.lstat(), directory=True)
    with _registration_lock(path):
        owner = _owner(path)
        if not _owner_alive(owner) or os.getppid() != owner['ownerPid'] or os.getpgrp() != os.getpid():
            raise RecoveryError('Bridge no longer owns this launch')
        pending = _read(path / name)
        if pending != {'version': 1, 'phase': 'pending'} or type(pending['version']) is not int:
            raise RecoveryError('Launch already used')
        _write(path, name, {'version': 1, 'phase': 'started', 'pid': os.getpid(),
                            'startedAt': psutil.Process().create_time()})
    os.execvpe(command[0], command, os.environ)


if __name__ == '__main__':
    try:
        bootstrap(sys.argv[1:])
    except Exception:
        # Bootstrap failure must NEVER exec the target or leak local details.
        sys.exit(78)
