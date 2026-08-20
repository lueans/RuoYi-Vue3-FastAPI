"""真实数据库验证 Yjs 同 revision 多来源状态持久化，数据最终回滚。"""

import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from config.database import async_engine
from module_mindmap.entity.do.mindmap_do import Mindmap
from module_mindmap.websocket.yjs_doc import YjsDocManager


async def verify() -> None:
    marker = uuid.uuid4().hex[:12]
    now = datetime.now()
    tree = {'data': {'uid': 'yjs-root', 'text': 'Yjs'}, 'children': []}
    async with async_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            mindmap = Mindmap(
                name=f'yjs-state-{marker}', owner_id=1, layout='logicalStructure',
                node_tree=json.dumps(tree, ensure_ascii=False), content_revision=1,
                node_count=1, schema_version=2, version_count=1, status=0, del_flag='0',
                create_by='verify', update_by='verify', create_time=now, update_time=now,
            )
            session.add(mindmap)
            await session.flush()

            assert await YjsDocManager.save_state(
                session, mindmap.id, b'client-a-state', 1, source_id='client-a',
            )
            assert await YjsDocManager.save_state(
                session, mindmap.id, b'client-b-state', 1, source_id='client-b',
            )
            assert await YjsDocManager.load_states(session, mindmap.id) == [
                b'client-a-state', b'client-b-state',
            ]

            mindmap.content_revision = 2
            await session.flush()
            assert await YjsDocManager.load_states(session, mindmap.id) == []
            print('mindmap Yjs state bundle verification passed')
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


if __name__ == '__main__':
    asyncio.run(verify())
