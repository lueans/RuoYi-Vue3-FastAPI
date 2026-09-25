import importlib
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[4]

sys.path.insert(0, str(BACKEND_DIR))


def _load_adapter_module(module_name: str) -> ModuleType:
    sys.modules.pop(module_name, None)
    sys.modules.pop('cli', None)
    return importlib.import_module(module_name)


@pytest.fixture
def app_adapter() -> ModuleType:
    return _load_adapter_module('cli.tui.adapters.app')


@pytest.fixture
def cache_adapter() -> ModuleType:
    return _load_adapter_module('cli.tui.adapters.cache')


@pytest.fixture
def crypto_adapter() -> ModuleType:
    return _load_adapter_module('cli.tui.adapters.crypto')


@pytest.fixture
def database_adapter() -> ModuleType:
    return _load_adapter_module('cli.tui.adapters.database')


@pytest.fixture
def jobs_adapter() -> ModuleType:
    return _load_adapter_module('cli.tui.adapters.jobs')


@pytest.fixture
def gen_adapter() -> ModuleType:
    return _load_adapter_module('cli.tui.adapters.gen')


@pytest.fixture
def configs_adapter() -> ModuleType:
    return _load_adapter_module('cli.tui.adapters.configs')


@pytest.fixture
def ops_adapter() -> ModuleType:
    return _load_adapter_module('cli.tui.adapters.ops')


@pytest.fixture
def health_adapter() -> ModuleType:
    return _load_adapter_module('cli.tui.adapters.health')


@pytest.fixture
def load_adapter_module() -> Callable[[str], ModuleType]:
    return _load_adapter_module


@pytest.fixture(autouse=True)
def isolate_search_suggestion_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot tests exercise search context without querying live completions.

    Nested CLI command doubles do not cover the separate completion providers.
    Replace that I/O boundary instead of disposing a real connection afterwards.
    """
    search = importlib.import_module('cli.tui.search')
    providers = search.TUI_SEARCH_SERVICE.provider_registry.providers
    for key, provider in tuple(providers.items()):
        if provider.suggestion_provider is not None:
            monkeypatch.setitem(providers, key, replace(provider, suggestion_provider=Mock(return_value=[])))
