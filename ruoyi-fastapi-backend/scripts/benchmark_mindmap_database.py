"""真实数据库中的脑图结构化持久化性能基线。

默认构造 1000 个节点、32 个标签和每节点 3 个标签绑定，测量首次物化、
增量保存和加载的 P95 耗时及 SQL 往返数。所有基准数据都位于一个外层事务中，
脚本结束时统一回滚，不污染业务数据。

运行：``DB_ECHO=false python -m scripts.benchmark_mindmap_database``
"""

import argparse
import asyncio
import json
import math
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import async_engine
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.do.mindmap_tag_do import MindmapTag
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from scripts.benchmark_mindmap_core import build_tree, count_nodes

DEFAULT_NODE_COUNT = 1_000
DEFAULT_TAG_COUNT = 32
DEFAULT_TAGS_PER_NODE = 3
DEFAULT_ROUNDS = 5
DEFAULT_MAX_PERSIST_SECONDS = 12.0
DEFAULT_MAX_INCREMENTAL_SECONDS = 8.0
DEFAULT_MAX_LOAD_SECONDS = 3.0


def percentile95(values: list[float]) -> float:
    if not values:
        raise ValueError('性能样本不能为空')
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def attach_tags(
    nodes: list[dict[str, Any]],
    tag_ids: list[int],
    tags_per_node: int,
) -> None:
    if not tag_ids:
        raise ValueError('标签列表不能为空')
    if tags_per_node < 1 or tags_per_node > len(tag_ids):
        raise ValueError('每节点标签数必须介于 1 和标签总数之间')
    for node_index, node in enumerate(nodes):
        node['data']['tag'] = [
            {
                'tagId': tag_ids[(node_index + offset) % len(tag_ids)],
                'placement': 'right',
                'align': 'center',
            }
            for offset in range(tags_per_node)
        ]


async def measure_async(
    operation: Callable[[], Awaitable[Any]],
    rounds: int,
    statement_counter: Callable[[], int],
) -> tuple[list[float], list[int], Any]:
    durations: list[float] = []
    statement_counts: list[int] = []
    result = None
    for _ in range(rounds):
        statements_before = statement_counter()
        started_at = time.perf_counter()
        result = await operation()
        durations.append(time.perf_counter() - started_at)
        statement_counts.append(statement_counter() - statements_before)
    return durations, statement_counts, result


def summarize(durations: list[float], statement_counts: list[int]) -> dict[str, Any]:
    return {
        'medianSeconds': round(statistics.median(durations), 6),
        'p95Seconds': round(percentile95(durations), 6),
        'minSeconds': round(min(durations), 6),
        'maxSeconds': round(max(durations), 6),
        'sqlStatementsMedian': round(statistics.median(statement_counts), 1),
        'sqlStatementsMax': max(statement_counts),
    }


async def create_tags(
    session: AsyncSession,
    tag_count: int,
    marker: str,
    now: datetime,
) -> list[MindmapTag]:
    tags = [
        MindmapTag(
            uuid=str(uuid.uuid4()),
            tag_key=f'benchmark_{marker}_{index}',
            name=f'性能标签 {index}',
            owner_id=1,
            style={
                'fill': f'#{(index * 2654435761) & 0xFFFFFF:06x}',
                'color': '#ffffff',
                'radius': 4,
            },
            status=0,
            definition_revision=1,
            usage_node_count=0,
            usage_file_count=0,
            created_by='benchmark',
            created_time=now,
            update_by='benchmark',
            updated_time=now,
        )
        for index in range(tag_count)
    ]
    session.add_all(tags)
    await session.flush()
    return tags


async def create_mindmap(
    session: AsyncSession,
    tree: dict[str, Any],
    marker: str,
    now: datetime,
) -> Mindmap:
    mindmap = Mindmap(
        name=f'database-benchmark-{marker}',
        owner_id=1,
        layout='logicalStructure',
        node_tree=json.dumps(tree, ensure_ascii=False),
        content_revision=1,
        node_count=0,
        schema_version=1,
        version_count=1,
        status=0,
        del_flag='0',
        create_by='benchmark',
        update_by='benchmark',
        create_time=now,
        update_time=now,
    )
    session.add(mindmap)
    await session.flush()
    return mindmap


async def run_benchmark_stages(
    session: AsyncSession,
    mindmap: Mindmap,
    tree: dict[str, Any],
    nodes: list[dict[str, Any]],
    args: argparse.Namespace,
    statement_counter: Callable[[], int],
) -> dict[str, Any]:
    async def persist() -> dict[str, Any]:
        result = await MindmapDocumentService.persist_tree(
            session,
            mindmap.id,
            tree,
            owner_id=1,
            operator='benchmark',
        )
        await session.flush()
        return result

    persist_durations, persist_statements, persisted = await measure_async(
        persist,
        args.rounds,
        statement_counter,
    )
    mindmap.root_node_id = persisted['root_node_id']
    mindmap.node_count = persisted['node_count']
    await session.flush()

    update_round = 0

    async def persist_incremental() -> dict[str, Any]:
        nonlocal update_round
        update_round += 1
        target = nodes[-update_round]
        target['data']['text'] = f'增量更新 {update_round}'
        result = await MindmapDocumentService.persist_tree_incremental(
            session,
            mindmap.id,
            tree,
            owner_id=1,
            operator='benchmark',
        )
        await session.flush()
        return result

    incremental_durations, incremental_statements, incremental = await measure_async(
        persist_incremental,
        args.rounds,
        statement_counter,
    )

    async def load() -> dict[str, Any] | None:
        return await MindmapDocumentService.load_tree(session, mindmap.id)

    load_durations, load_statements, restored = await measure_async(
        load,
        args.rounds,
        statement_counter,
    )
    restored_node_count = count_nodes(restored)
    if restored_node_count != args.nodes:
        raise AssertionError(f'加载节点数错误: {restored_node_count} != {args.nodes}')
    if incremental['node_count'] != args.nodes:
        raise AssertionError('增量保存节点数错误')

    return {
        'persist': summarize(persist_durations, persist_statements),
        'incrementalPersist': summarize(incremental_durations, incremental_statements),
        'load': summarize(load_durations, load_statements),
    }


async def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    if args.nodes < 1 or args.tags < 1 or args.rounds < 1:
        raise ValueError('节点数、标签数和测试轮数必须大于 0')
    if args.tags_per_node < 1 or args.tags_per_node > args.tags:
        raise ValueError('每节点标签数必须介于 1 和标签总数之间')

    marker = uuid.uuid4().hex[:12]
    statement_total = 0

    def count_statement(*_args: Any, **_kwargs: Any) -> None:
        nonlocal statement_total
        statement_total += 1

    event.listen(async_engine.sync_engine, 'before_cursor_execute', count_statement)
    try:
        async with async_engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                now = datetime.now()
                tags = await create_tags(session, args.tags, marker, now)
                tree, nodes = build_tree(args.nodes, args.branch_factor)
                attach_tags(nodes, [int(tag.id) for tag in tags], args.tags_per_node)
                mindmap = await create_mindmap(session, tree, marker, now)
                stages = await run_benchmark_stages(
                    session,
                    mindmap,
                    tree,
                    nodes,
                    args,
                    lambda: statement_total,
                )
                return {
                    'nodeCount': args.nodes,
                    'tagCount': args.tags,
                    'tagsPerNode': args.tags_per_node,
                    'tagBindingCount': args.nodes * args.tags_per_node,
                    'branchFactor': args.branch_factor,
                    'roundsPerStage': args.rounds,
                    **stages,
                    'rolledBack': True,
                }
            finally:
                await session.close()
                if transaction.is_active:
                    await transaction.rollback()
    finally:
        event.remove(async_engine.sync_engine, 'before_cursor_execute', count_statement)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='运行脑图真实数据库性能基线')
    parser.add_argument('--nodes', type=int, default=DEFAULT_NODE_COUNT)
    parser.add_argument('--tags', type=int, default=DEFAULT_TAG_COUNT)
    parser.add_argument('--tags-per-node', type=int, default=DEFAULT_TAGS_PER_NODE)
    parser.add_argument('--branch-factor', type=int, default=8)
    parser.add_argument('--rounds', type=int, default=DEFAULT_ROUNDS)
    parser.add_argument('--max-persist-seconds', type=float, default=DEFAULT_MAX_PERSIST_SECONDS)
    parser.add_argument(
        '--max-incremental-seconds',
        type=float,
        default=DEFAULT_MAX_INCREMENTAL_SECONDS,
    )
    parser.add_argument('--max-load-seconds', type=float, default=DEFAULT_MAX_LOAD_SECONDS)
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    result = await benchmark(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    limits = {
        'persist': args.max_persist_seconds,
        'incrementalPersist': args.max_incremental_seconds,
        'load': args.max_load_seconds,
    }
    slow_stages = [
        stage
        for stage, limit in limits.items()
        if result[stage]['p95Seconds'] > limit
    ]
    if slow_stages:
        print(f'数据库性能基线失败，超过阈值: {", ".join(slow_stages)}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
