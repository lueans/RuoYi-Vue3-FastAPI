"""脑图核心算法性能基线。

默认生成 5000 节点的 simple-mind-map 文档，分别测量结构化编码、解码和
单节点并发合并。任一阶段中位耗时超过阈值时返回非零状态，便于在发布前或 CI
中发现明显的性能回退。

运行：``python -m scripts.benchmark_mindmap_core``
"""

import argparse
import copy
import json
import math
import statistics
import time
import tracemalloc
from collections.abc import Callable
from typing import Any

from module_mindmap.service.mindmap_service import merge_node_operations
from module_mindmap.service.simple_mind_document_codec import SimpleMindDocumentCodec

DEFAULT_NODE_COUNT = 5_000
DEFAULT_BRANCH_FACTOR = 8
DEFAULT_ROUNDS = 7
DEFAULT_MAX_SECONDS = 5.0


def build_tree(node_count: int, branch_factor: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if node_count < 1:
        raise ValueError('节点数量必须大于 0')
    if branch_factor < 1:
        raise ValueError('分支数必须大于 0')
    root = {
        'data': {'uid': 'node-0', 'text': '中心主题', 'fontSize': 28},
        'children': [],
    }
    nodes = [root]
    for index in range(1, node_count):
        node = {
            'data': {
                'uid': f'node-{index}',
                'text': f'主题 {index}',
                'note': f'性能基线备注 {index}',
                'tag': [{'tagId': index % 17 + 1, 'text': f'标签 {index % 17 + 1}'}]
                if index % 5 == 0 else [],
            },
            'children': [],
        }
        parent = nodes[(index - 1) // branch_factor]
        parent['children'].append(node)
        nodes.append(node)
    return root, nodes


def count_nodes(root: dict[str, Any] | None) -> int:
    if not root:
        return 0
    count = 0
    pending = [root]
    while pending:
        node = pending.pop()
        count += 1
        pending.extend(node.get('children') or [])
    return count


def measure_duration(operation: Callable[[], Any], rounds: int) -> tuple[float, float, Any]:
    durations = []
    result = None
    for _ in range(rounds):
        started_at = time.perf_counter()
        result = operation()
        durations.append(time.perf_counter() - started_at)
    ordered = sorted(durations)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return statistics.median(durations), ordered[p95_index], result


def benchmark(node_count: int, branch_factor: int, rounds: int) -> dict[str, Any]:
    tree, nodes = build_tree(node_count, branch_factor)
    client_tree = copy.deepcopy(tree)
    client_nodes = []
    pending = [client_tree]
    while pending:
        node = pending.pop()
        client_nodes.append(node)
        pending.extend(node.get('children') or [])
    target = client_nodes[-1]
    target['data']['text'] = '客户端更新后的主题'
    target_uid = target['data']['uid']

    tracemalloc.start()
    encode_seconds, encode_p95_seconds, encoded = measure_duration(
        lambda: SimpleMindDocumentCodec.encode(tree),
        rounds,
    )
    decode_seconds, decode_p95_seconds, decoded = measure_duration(
        lambda: SimpleMindDocumentCodec.decode(encoded),
        rounds,
    )
    merge_seconds, merge_p95_seconds, merged = measure_duration(
        lambda: merge_node_operations(
            tree,
            client_tree,
            [{'type': 'node.update', 'nodeUid': target_uid, 'payload': {'childUids': []}}],
        ),
        rounds,
    )
    _current_memory, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    if len(encoded.nodes) != node_count:
        raise AssertionError(f'编码节点数错误: {len(encoded.nodes)} != {node_count}')
    if count_nodes(decoded) != node_count:
        raise AssertionError('解码节点数错误')
    if count_nodes(merged) != node_count:
        raise AssertionError('并发合并节点数错误')

    return {
        'nodeCount': node_count,
        'branchFactor': branch_factor,
        'rounds': rounds,
        'encodeSeconds': round(encode_seconds, 6),
        'encodeP95Seconds': round(encode_p95_seconds, 6),
        'decodeSeconds': round(decode_seconds, 6),
        'decodeP95Seconds': round(decode_p95_seconds, 6),
        'mergeSeconds': round(merge_seconds, 6),
        'mergeP95Seconds': round(merge_p95_seconds, 6),
        'encodeNodesPerSecond': round(node_count / encode_seconds),
        'decodeNodesPerSecond': round(node_count / decode_seconds),
        'mergeNodesPerSecond': round(node_count / merge_seconds),
        'peakMemoryMiB': round(peak_memory / 1024 / 1024, 2),
        'generatedNodeReferences': len(nodes),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='运行脑图核心算法性能基线')
    parser.add_argument('--nodes', type=int, default=DEFAULT_NODE_COUNT)
    parser.add_argument('--branch-factor', type=int, default=DEFAULT_BRANCH_FACTOR)
    parser.add_argument('--rounds', type=int, default=DEFAULT_ROUNDS)
    parser.add_argument('--max-seconds', type=float, default=DEFAULT_MAX_SECONDS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.rounds < 1:
        raise ValueError('测试轮数必须大于 0')
    result = benchmark(args.nodes, args.branch_factor, args.rounds)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    slow_stages = [
        stage
        for stage in ('encode', 'decode', 'merge')
        if result[f'{stage}P95Seconds'] > args.max_seconds
    ]
    if slow_stages:
        print(f'性能基线失败，超过 {args.max_seconds}s: {", ".join(slow_stages)}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
