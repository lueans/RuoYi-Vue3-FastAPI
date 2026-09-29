"""Driver tests must never use the user's persistent run registry."""

import importlib.util

import pytest


@pytest.fixture(autouse=True)
def private_run_registry(monkeypatch, tmp_path):
    if importlib.util.find_spec('psutil') is None:
        return  # scan-only tests do not require an execution extra
    from mindmap_agent_bridge import run_recovery
    monkeypatch.setattr(run_recovery, 'run_root', lambda: tmp_path / 'private-runs')
