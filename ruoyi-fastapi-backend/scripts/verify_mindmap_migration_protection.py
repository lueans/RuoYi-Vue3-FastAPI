"""在真实数据库事务中验证迁移失败文件的只读保护，最后整体回滚。"""

import asyncio
from datetime import datetime

from sqlalchemy import select

from config.database import AsyncSessionLocal
from exceptions.exception import ServiceException
from module_mindmap.entity.do.mindmap_content_do import MindmapMigrationRecord
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.entity.vo.mindmap_vo import MindmapPageQueryModel
from module_mindmap.service.mindmap_service import MindmapService


async def verify() -> int:
    async with AsyncSessionLocal() as db:
        try:
            mindmap = (await db.execute(
                select(Mindmap)
                .where(Mindmap.del_flag == '0')
                .order_by(Mindmap.id)
                .limit(1)
            )).scalars().first()
            if not mindmap:
                raise RuntimeError('开发库中没有可用脑图')

            record = (await db.execute(
                select(MindmapMigrationRecord)
                .where(MindmapMigrationRecord.file_id == mindmap.id)
            )).scalars().first()
            if record is None:
                record = MindmapMigrationRecord(
                    file_id=mindmap.id,
                    batch_id='verification',
                    status='failed',
                    error_message='验证用失败状态',
                    started_time=datetime.now(),
                    finished_time=datetime.now(),
                )
                db.add(record)
            else:
                record.batch_id = 'verification'
                record.status = 'failed'
                record.error_message = '验证用失败状态'
            await db.flush()

            page = await MindmapService.get_mindmap_list_services(
                db,
                MindmapPageQueryModel(ownerId=mindmap.owner_id, pageSize=100),
            )
            row = next(item for item in page.rows if item['id'] == mindmap.id)
            if row['contentState'] != 'migration_failed' or row['canEdit'] is not False:
                raise AssertionError(f'列表迁移保护状态错误: {row}')

            detail = await MindmapService.get_mindmap_detail_services(
                db, mindmap.id, mindmap.owner_id,
            )
            if detail.content_state != 'migration_failed' or detail.can_edit is not False:
                raise AssertionError('详情未进入迁移只读保护')

            try:
                await MindmapService.resolve_mindmap_access(
                    db, mindmap.id, mindmap.owner_id, require_edit=True,
                )
            except ServiceException as error:
                if '仅可只读访问' not in error.message:
                    raise
            else:
                raise AssertionError('迁移失败文件仍然通过编辑权限检查')

            print(
                f'PASS file_id={mindmap.id} list=readonly detail=readonly write=denied rollback=true'
            )
            return 0
        finally:
            await db.rollback()


if __name__ == '__main__':
    raise SystemExit(asyncio.run(verify()))
