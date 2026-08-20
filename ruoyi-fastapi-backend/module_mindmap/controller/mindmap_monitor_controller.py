"""脑图运行指标 Controller。"""

from fastapi import Request, Response

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_mindmap.entity.vo.mindmap_monitor_vo import MindmapMetricsSnapshotModel
from module_mindmap.service.mindmap_metrics import mindmap_metrics
from module_mindmap.websocket.room_manager import room_manager
from utils.response_util import ResponseUtil

mindmap_monitor_controller = APIRouterPro(
    prefix='/monitor/mindmap',
    order_num=16,
    tags=['系统监控-脑图监控'],
    dependencies=[PreAuthDependency()],
)


@mindmap_monitor_controller.get(
    '',
    summary='获取脑图进程指标',
    description='返回当前后端进程的低基数脑图指标；多进程部署应逐进程采集后聚合',
    response_model=DataResponseModel[MindmapMetricsSnapshotModel],
    dependencies=[UserInterfaceAuthDependency('monitor:server:list')],
)
async def get_mindmap_metrics(request: Request) -> Response:
    collaboration = await room_manager.get_runtime_snapshot()
    return ResponseUtil.success(data=mindmap_metrics.snapshot(collaboration))
