"""脑图模板服务层"""
import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_template_dao import MindmapTemplateDao
from module_mindmap.entity.vo.mindmap_template_vo import (
    MindmapTemplatePublishModel,
    MindmapTemplateQueryModel,
)
from utils.common_util import CamelCaseUtil


class MindmapTemplateService:
    """模板服务层"""

    # ── 公开接口 ──

    @classmethod
    async def get_template_list(cls, db: AsyncSession, query: MindmapTemplateQueryModel) -> PageModel:
        """获取模板列表（公开）"""
        return await MindmapTemplateDao.get_template_list(
            db, query.category_id, query.keyword, query.page_num, query.page_size,
        )

    @classmethod
    async def get_categories(cls, db: AsyncSession) -> list:
        """获取模板分类列表（公开）"""
        categories = await MindmapTemplateDao.get_categories(db)
        return [CamelCaseUtil.transform_result(c) for c in categories]

    @classmethod
    async def get_template_detail(cls, db: AsyncSession, template_id: int) -> dict:
        """获取模板详情（公开）"""
        template = await MindmapTemplateDao.get_template_by_id(db, template_id)
        if not template:
            raise ServiceException(message='模板不存在')

        result = CamelCaseUtil.transform_result(template)
        if isinstance(result.get('node_tree'), str):
            result['node_tree'] = json.loads(result['node_tree'])
        return result

    @classmethod
    async def use_template(
        cls, db: AsyncSession, template_id: int, user_id: int, user_name: str,
    ) -> CrudResponseModel:
        """使用模板创建新脑图"""
        template = await MindmapTemplateDao.get_template_by_id(db, template_id)
        if not template:
            raise ServiceException(message='模板不存在')

        # 解析 node_tree
        node_tree = template.node_tree
        if isinstance(node_tree, str):
            node_tree = json.loads(node_tree)

        # 复制为新脑图
        from module_mindmap.entity.vo.mindmap_vo import MindmapModel
        new_mindmap = MindmapModel(
            name=f'{template.name}',
            description=template.description,
            owner_id=user_id,
            layout=template.layout,
            theme=template.theme,
            node_tree=node_tree,
            view_data=template.view_data,
            create_by=user_name,
            create_time=datetime.now(),
            update_by=user_name,
            update_time=datetime.now(),
        )

        from module_mindmap.service.mindmap_service import MindmapService
        return await MindmapService.add_mindmap_services(db, new_mindmap)

    # ── 管理接口（管理员） ──

    @classmethod
    async def publish_template(
        cls, db: AsyncSession, model: MindmapTemplatePublishModel, user_name: str,
    ) -> CrudResponseModel:
        """发布模板（从现有脑图复制）"""
        source = await MindmapDao.get_mindmap_by_id(db, model.mindmap_id)
        if not source:
            raise ServiceException(message='源脑图不存在')

        node_tree = source.node_tree
        if isinstance(node_tree, str):
            node_tree_str = node_tree
        else:
            node_tree_str = json.dumps(node_tree, ensure_ascii=False)

        try:
            await MindmapTemplateDao.publish_template(db, {
                'name': model.name,
                'description': model.description,
                'owner_id': 0,  # 系统模板
                'layout': source.layout,
                'theme': source.theme,
                'node_tree': node_tree_str,
                'view_data': source.view_data,
                'cover_image': model.cover_image,
                'is_template': 1,
                'template_category_id': model.template_category_id,
                'create_by': user_name,
                'create_time': datetime.now(),
                'update_by': user_name,
                'update_time': datetime.now(),
                'del_flag': '0',
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='模板发布成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def unpublish_template(cls, db: AsyncSession, template_id: int) -> CrudResponseModel:
        """取消发布模板"""
        template = await MindmapTemplateDao.get_template_by_id(db, template_id)
        if not template:
            raise ServiceException(message='模板不存在')

        try:
            await MindmapTemplateDao.unpublish_template(db, template_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='模板已下架')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def add_category(cls, db: AsyncSession, name: str, sort_order: int = 0) -> CrudResponseModel:
        """新增模板分类"""
        try:
            await MindmapTemplateDao.add_category(db, {
                'name': name,
                'sort_order': sort_order,
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='分类创建成功')
        except Exception as e:
            await db.rollback()
            raise e

    @classmethod
    async def delete_category(cls, db: AsyncSession, category_id: int) -> CrudResponseModel:
        """删除模板分类"""
        try:
            await MindmapTemplateDao.delete_category(db, category_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='分类删除成功')
        except Exception as e:
            await db.rollback()
            raise e
