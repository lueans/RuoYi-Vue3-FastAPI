"""Run the fixed SMM v2 conformance fixtures without platform access."""
from __future__ import annotations

import json
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT_ROOT / 'python'))

from mindmap_agent_kit import ArtifactValidationError, validate_artifact  # noqa: E402


def main() -> int:
    fixture_dir = Path(__file__).resolve().parent
    cases = json.loads((fixture_dir / 'cases.json').read_text(encoding='utf-8'))
    failures: list[str] = []
    for case in cases:
        artifact = json.loads((fixture_dir / case['file']).read_text(encoding='utf-8'))
        try:
            validate_artifact(artifact)
            actual_valid, error = True, ''
        except ArtifactValidationError as exc:
            actual_valid, error = False, str(exc)
        if actual_valid != case['valid']:
            failures.append(f"{case['file']}: expected valid={case['valid']}, got {actual_valid} ({error})")
        if case.get('errorContains') and case['errorContains'] not in error:
            failures.append(f"{case['file']}: expected error containing {case['errorContains']!r}, got {error!r}")
    if failures:
        for failure in failures:
            print(f'FAIL {failure}')
        return 1
    print(f'PASS {len(cases)} SMM v2 conformance fixtures')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
