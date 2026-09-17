"""CLI for provider-neutral AI mind-map quality evaluation reports."""

from __future__ import annotations

import argparse
import asyncio
import json
from importlib import metadata
from pathlib import Path
from typing import Any

from module_mindmap.ai.evals.dataset import load_eval_dataset
from module_mindmap.ai.evals.runner import run_quality_evaluation, write_evaluation_report

EXECUTOR_ENTRY_POINT = 'ruoyi.mindmap_ai_eval_executors'


def _load_executor(name: str | None) -> Any | None:
    if name is None:
        return None
    discovered = metadata.entry_points()
    candidates = (
        list(discovered.select(group=EXECUTOR_ENTRY_POINT, name=name))
        if hasattr(discovered, 'select')
        else [item for item in discovered.get(EXECUTOR_ENTRY_POINT, ()) if item.name == name]
    )
    if len(candidates) != 1:
        raise ValueError(f'未找到唯一的真实供应商评测执行器: {name}')
    loaded = candidates[0].load()
    return loaded() if isinstance(loaded, type) else loaded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='运行版本化 AI 脑图质量与安全评测')
    parser.add_argument('--agent', required=True, help='Agent key，例如 native_mindmap、codex、claude')
    parser.add_argument('--model', help='可选模型标识')
    parser.add_argument('--dataset', type=Path, help='数据集路径；默认使用内置 dataset-v1')
    parser.add_argument('--fixture', action='append', default=[], help='只运行指定 fixture，可重复')
    parser.add_argument('--executor', help=f'已安装的 {EXECUTOR_ENTRY_POINT} entry point 名称')
    parser.add_argument('--quality-threshold', type=float, default=80.0)
    parser.add_argument('--output', type=Path, required=True, help='脱敏 JSON 报告落盘路径')
    parser.add_argument('--list-fixtures', action='store_true')
    return parser


async def _run(args: argparse.Namespace) -> int:
    dataset = load_eval_dataset(args.dataset)
    if args.list_fixtures:
        print('\n'.join(case.case_id for case in dataset.cases))
        return 0
    report = await run_quality_evaluation(
        dataset,
        agent_key=args.agent,
        model_ref=args.model,
        fixture_ids=set(args.fixture),
        quality_threshold=args.quality_threshold,
        executor=_load_executor(args.executor),
    )
    write_evaluation_report(report, args.output)
    print(json.dumps({
        'overallStatus': report['overallStatus'],
        'releaseEligible': report['releaseEligible'],
        'report': str(args.output),
    }, ensure_ascii=False))
    if report['releaseEligible']:
        return 0
    return 2 if report['overallStatus'] == 'blocked' else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run(build_parser().parse_args())))


if __name__ == '__main__':
    main()
