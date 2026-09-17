"""Cross-package conformance checks for the standalone Agent Kit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KIT_ROOT = REPOSITORY_ROOT / 'mindmap-agent-kit'
sys.path.insert(0, str(KIT_ROOT / 'python'))
SMM_V2 = 2
TWO_NODES = 2

from mindmap_agent_kit import (  # noqa: E402
    ArtifactValidationError,
    MindmapBuilder,
    validate_artifact,
)
from mindmap_agent_kit.cli import main as cli_main  # noqa: E402
from mindmap_agent_kit.mcp_server import MindmapMcpServer  # noqa: E402

from module_mindmap.ai.document import validate_smm_artifact  # noqa: E402


def test_python_builder_output_is_accepted_by_platform_validator() -> None:
    builder = MindmapBuilder('支付测试')
    builder.add_nodes([{'parentUid': builder.root_uid, 'text': '支付成功'}])
    result = builder.complete_artifact(
        title='支付测试',
        agent_key='future_agent',
        adapter_version='1.0.0',
        prompt_version='future-1',
        artifact_id='kit-artifact',
    )

    kit_report = validate_artifact(result['artifact'])
    platform_artifact, platform_summary = validate_smm_artifact(result['artifact'])

    assert kit_report['platformTrust'] == 'external_unverified'
    assert platform_artifact['manifest']['provenance'] == 'external_unverified'
    assert platform_summary['nodeCount'] == TWO_NODES


def test_fixed_fixtures_have_expected_positive_and_negative_results() -> None:
    valid = json.loads((KIT_ROOT / 'conformance/valid-create.smm.json').read_text(encoding='utf-8'))
    invalid = json.loads((KIT_ROOT / 'conformance/invalid-hash.smm.json').read_text(encoding='utf-8'))

    assert validate_artifact(valid)['nodeCount'] == TWO_NODES
    validate_smm_artifact(valid)
    with pytest.raises(ArtifactValidationError, match='documentHash'):
        validate_artifact(invalid)


def test_cli_validate_and_render_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fixture = KIT_ROOT / 'conformance/valid-create.smm.json'
    artifact_path = tmp_path / 'artifact.smm'
    artifact_path.write_bytes(fixture.read_bytes())

    assert cli_main(['validate', str(artifact_path)]) == 0
    assert '"nodeCount": 2' in capsys.readouterr().out
    assert cli_main(['render-summary', str(artifact_path)]) == 0
    assert '# 支付测试' in capsys.readouterr().out


def test_stdio_mcp_contract_builds_artifact_and_rejects_unknown_arguments() -> None:
    server = MindmapMcpServer()
    started = server.call_tool('mindmap.start_document', {'title': '订单'})
    with pytest.raises(ArtifactValidationError, match='unknown field'):
        server.call_tool('mindmap.read_projection', {'draftId': started['draftId'], 'path': '/tmp'})

    created = server.call_tool('mindmap.add_nodes', {
        'draftId': started['draftId'],
        'nodes': [{'parentUid': started['rootUid'], 'text': '创建订单'}],
    })
    assert created['created'][0]['nodeUid']
    completed = server.call_tool('mindmap.complete_artifact', {
        'draftId': started['draftId'],
        'title': '订单',
        'agentKey': 'future_agent',
        'adapterVersion': '1.0.0',
        'promptVersion': 'future-1',
    })
    validate_smm_artifact(completed['artifact'])


def test_published_schema_declares_closed_smm_v2_envelope() -> None:
    schema_path = KIT_ROOT / 'python/mindmap_agent_kit/schema/smm-v2.schema.json'
    schema = json.loads(schema_path.read_text(encoding='utf-8'))

    assert schema['properties']['format']['const'] == 'ruoyi-mindmap'
    assert schema['properties']['formatSchemaVersion']['const'] == SMM_V2
    assert schema['additionalProperties'] is False
