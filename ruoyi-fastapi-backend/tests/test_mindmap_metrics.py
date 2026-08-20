"""脑图低基数运行指标测试。"""

import inspect
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from exceptions.exception import ServiceWarning
from module_mindmap.controller import mindmap_monitor_controller
from module_mindmap.entity.vo.mindmap_monitor_vo import MindmapMetricsSnapshotModel
from module_mindmap.service.mindmap_metrics import (
    MindmapMetricsRegistry,
    mindmap_metrics,
    observe_mindmap_operation,
    record_mindmap_event,
)
from module_mindmap.websocket.yjs_doc import YjsDocManager
from server import create_app


class MindmapMetricsRegistryTest(unittest.TestCase):
    def test_registry_uses_only_fixed_dimensions_and_never_stores_business_labels(self) -> None:
        registry = MindmapMetricsRegistry()
        secret = '客户战略脑图-file-98231-user-779'

        with self.assertRaises(ValueError):
            registry.observe(secret, 'success', 0.1)
        with self.assertRaises(ValueError):
            registry.observe('detail_load', secret, 0.1)
        with self.assertRaises(ValueError):
            registry.increment_event(secret)

        serialized = json.dumps(registry.snapshot(), ensure_ascii=False, default=str)
        self.assertNotIn(secret, serialized)

    def test_snapshot_exposes_cumulative_duration_buckets_and_work_units(self) -> None:
        registry = MindmapMetricsRegistry()
        registry.observe('detail_load', 'success', 0.04, work_units=12)
        registry.observe('detail_load', 'success', 0.2, work_units=8)

        snapshot = registry.snapshot()
        validated = MindmapMetricsSnapshotModel.model_validate(snapshot)
        series = validated.series[0]

        self.assertEqual(series.count, 2)
        self.assertEqual(series.work_units_sum, 20)
        self.assertEqual(series.work_units_max, 12)
        self.assertEqual([bucket.count for bucket in series.duration_buckets[:3]], [0, 0, 1])
        self.assertEqual(series.duration_buckets[4].count, 2)
        self.assertEqual(len(validated.events), 11)
        self.assertEqual(validated.collaboration.active_connections, 0)
        self.assertEqual(validated.collaboration.redis_transport_state, 'stopped')

    def test_collaboration_snapshot_only_accepts_fixed_sanitized_runtime_fields(self) -> None:
        registry = MindmapMetricsRegistry()
        snapshot = registry.snapshot({
            'activeRooms': 2,
            'activeConnections': 5,
            'retiringConnections': -1,
            'redisTransportState': 'ready',
            'fileName': '不得进入指标的客户脑图',
        })

        self.assertEqual(snapshot['collaboration'], {
            'activeRooms': 2,
            'activeConnections': 5,
            'retiringConnections': 0,
            'redisTransportState': 'ready',
        })
        self.assertNotIn('客户脑图', json.dumps(snapshot, ensure_ascii=False, default=str))


class MindmapOperationObserverTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mindmap_metrics.reset_for_tests()

    async def asyncTearDown(self) -> None:
        mindmap_metrics.reset_for_tests()

    async def test_observer_records_outcome_units_and_fixed_events(self) -> None:
        @observe_mindmap_operation(
            'content_batch_save',
            outcome_getter=lambda result: 'replay' if result['replay'] else 'success',
            work_units_getter=lambda args, kwargs, result: kwargs['units'],
            result_hook=lambda result: record_mindmap_event('idempotent_replay'),
        )
        async def operation(*, units: int) -> dict:
            return {'replay': True}

        result = await operation(units=3)
        snapshot = mindmap_metrics.snapshot()

        self.assertEqual(result, {'replay': True})
        self.assertEqual(snapshot['series'][0]['outcome'], 'replay')
        self.assertEqual(snapshot['series'][0]['workUnitsSum'], 3)
        event_counts = {item['event']: item['count'] for item in snapshot['events']}
        self.assertEqual(event_counts['idempotent_replay'], 1)

    async def test_service_warning_is_counted_as_conflict_and_re_raised(self) -> None:
        @observe_mindmap_operation('content_batch_save')
        async def operation() -> None:
            raise ServiceWarning(message='版本冲突')

        with self.assertRaises(ServiceWarning):
            await operation()

        snapshot = mindmap_metrics.snapshot()
        self.assertEqual(snapshot['series'][0]['outcome'], 'conflict')
        event_counts = {item['event']: item['count'] for item in snapshot['events']}
        self.assertEqual(event_counts['conflict'], 1)

    async def test_regular_failure_is_counted_and_original_error_is_re_raised(self) -> None:
        error = RuntimeError('database unavailable')

        @observe_mindmap_operation('tag_replace')
        async def operation() -> None:
            raise error

        with self.assertRaises(RuntimeError) as context:
            await operation()

        self.assertIs(context.exception, error)
        self.assertEqual(mindmap_metrics.snapshot()['series'][0]['outcome'], 'error')

    async def test_monitoring_failures_never_change_business_results_or_errors(self) -> None:
        @observe_mindmap_operation('tag_archive', result_hook=lambda result: 1 / 0)
        async def success() -> str:
            return 'saved'

        business_error = LookupError('business failure')

        @observe_mindmap_operation('tag_archive')
        async def failure() -> None:
            raise business_error

        with patch.object(mindmap_metrics, 'observe', side_effect=RuntimeError('metrics down')):
            self.assertEqual(await success(), 'saved')
            with self.assertRaises(LookupError) as context:
                await failure()

        self.assertIs(context.exception, business_error)


class MindmapYjsMetricsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        mindmap_metrics.reset_for_tests()

    async def asyncTearDown(self) -> None:
        mindmap_metrics.reset_for_tests()

    async def test_load_and_save_revision_mismatches_use_one_fixed_event(self) -> None:
        load_db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(
                first=lambda: (b'stale-state', 3, 4),
            )),
        )

        def scalar_result(value: object) -> SimpleNamespace:
            return SimpleNamespace(scalar_one_or_none=lambda: value)

        save_db = SimpleNamespace(
            execute=AsyncMock(side_effect=[scalar_result(None), scalar_result(5)]),
            rollback=AsyncMock(),
        )

        self.assertEqual(await YjsDocManager.load_state_entries(load_db, 9), {})
        self.assertFalse(await YjsDocManager.save_state(
            save_db,
            9,
            b'current-state',
            content_revision=4,
        ))

        event_counts = {
            item['event']: item['count']
            for item in mindmap_metrics.snapshot()['events']
        }
        self.assertEqual(event_counts['yjs_revision_mismatch'], 2)
        save_db.rollback.assert_awaited_once()


class MindmapMetricsOpenApiTest(unittest.TestCase):
    def test_monitor_endpoint_is_typed_and_reuses_server_monitor_permission(self) -> None:
        schema = create_app().openapi()
        operation = schema['paths']['/monitor/mindmap']['get']
        response_schema = operation['responses']['200']['content']['application/json']['schema']
        response_model = schema['components']['schemas'][response_schema['$ref'].rsplit('/', 1)[-1]]
        snapshot_ref = response_model['properties']['data']['$ref']
        snapshot_model = schema['components']['schemas'][snapshot_ref.rsplit('/', 1)[-1]]

        self.assertEqual(snapshot_model['properties']['scope']['const'], 'process')
        series_properties = schema['components']['schemas']['MindmapMetricSeriesModel']['properties']
        event_properties = schema['components']['schemas']['MindmapMetricEventModel']['properties']
        self.assertEqual(len(series_properties['operation']['enum']), 5)
        self.assertEqual(len(series_properties['outcome']['enum']), 5)
        self.assertEqual(len(event_properties['event']['enum']), 11)
        self.assertIn('durationBuckets', series_properties)
        collaboration_ref = snapshot_model['properties']['collaboration']['$ref']
        collaboration_model = schema['components']['schemas'][
            collaboration_ref.rsplit('/', 1)[-1]
        ]
        self.assertEqual(
            collaboration_model['properties']['redisTransportState']['enum'],
            ['stopped', 'ready', 'degraded'],
        )
        self.assertIn(
            "UserInterfaceAuthDependency('monitor:server:list')",
            inspect.getsource(mindmap_monitor_controller),
        )


if __name__ == '__main__':
    unittest.main()
