from typing import Any

from pytest import MonkeyPatch

from utils.ai_util import AiUtil


class _FakeModel:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def test_ollama_factory_maps_generic_fields_to_agno_contract(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        AiUtil,
        '_resolve_provider_class',
        classmethod(lambda _cls, _provider: _FakeModel),
    )

    model = AiUtil.get_model_from_factory(
        provider='Ollama',
        model_code='qwen3.5:latest',
        model_name='Qwen 3.5',
        base_url='http://127.0.0.1:11434',
        temperature=0.25,
        max_tokens=4096,
    )

    assert model.kwargs == {
        'id': 'qwen3.5:latest',
        'name': 'Qwen 3.5',
        'host': 'http://127.0.0.1:11434',
        'client_params': {'trust_env': False},
        'options': {'temperature': 0.25, 'num_predict': 4096},
    }


def test_ollama_factory_keeps_environment_proxy_for_remote_host(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        AiUtil,
        '_resolve_provider_class',
        classmethod(lambda _cls, _provider: _FakeModel),
    )

    model = AiUtil.get_model_from_factory(
        provider='Ollama',
        model_code='qwen3.5:latest',
        base_url='https://ollama.example.test',
    )

    assert model.kwargs == {
        'id': 'qwen3.5:latest',
        'host': 'https://ollama.example.test',
    }
