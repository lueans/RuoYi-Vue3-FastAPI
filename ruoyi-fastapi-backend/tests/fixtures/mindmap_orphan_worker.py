"""Test-only stand-in for a worker leaving a child after successful output."""

import json
import subprocess
import sys

request = json.load(sys.stdin)
child = subprocess.Popen(
    [sys.executable, '-c',
     'import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
     'print(os.getpid(),flush=True); time.sleep(20)'],
    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
)
assert int(child.stdout.readline()) == child.pid
child.stdout.close()
print(json.dumps({'protocolVersion': request['protocolVersion'], 'ok': True, 'childPid': child.pid}), flush=True)
