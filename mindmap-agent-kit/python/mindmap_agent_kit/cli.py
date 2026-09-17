"""Command-line interface for validating and inspecting SMM v2 artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from mindmap_agent_kit.artifact import (
    ArtifactValidationError,
    load_artifact,
    render_summary,
    validate_artifact,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='mindmap-agent', description='SMM v2 Agent Kit')
    subparsers = parser.add_subparsers(dest='command', required=True)
    validate_parser = subparsers.add_parser('validate', help='validate an SMM v2 JSON artifact')
    validate_parser.add_argument('artifact')
    validate_parser.add_argument('--allow-draft', action='store_true')
    summary_parser = subparsers.add_parser('render-summary', help='render a Markdown artifact summary')
    summary_parser.add_argument('artifact')
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
        if args.command == 'validate':
            report = validate_artifact(artifact, require_passed=not args.allow_draft)
            sys.stdout.write(f'{json.dumps(report, ensure_ascii=False, sort_keys=True)}\n')
        else:
            sys.stdout.write(f'{render_summary(artifact)}\n')
        return 0
    except ArtifactValidationError as exc:
        sys.stderr.write(f'invalid SMM v2 artifact: {exc}\n')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
