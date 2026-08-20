"""脑图模板服务层"""
import json
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from module_mindmap.dao.mindmap_dao import MindmapDao
from module_mindmap.dao.mindmap_template_dao import MindmapTemplateDao
from module_mindmap.entity.vo.mindmap_template_vo import (
    MAX_TEMPLATE_CATEGORY_NAME_LENGTH,
    MindmapTemplatePublishModel,
    MindmapTemplateQueryModel,
    normalize_template_text,
)
from module_mindmap.service.mindmap_document_service import MindmapDocumentService
from module_mindmap.service.mindmap_tag_portability import MindmapTagPortabilityService
from module_mindmap.service.simple_mind_document_codec import SCHEMA_VERSION
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
        node_tree = result.get('nodeTree') or result.get('node_tree')
        if isinstance(node_tree, str):
            node_tree = json.loads(node_tree)
        if isinstance(node_tree, dict):
            node_tree = await MindmapTagPortabilityService.prepare_tree_for_owner(
                db,
                node_tree,
                target_owner_id=0,
            )
            result['nodeTree'] = node_tree
            result.pop('node_tree', None)
        return result

    @classmethod
    async def use_template(
        cls,
        db: AsyncSession,
        template_id: int,
        user_id: int,
        user_name: str,
        *,
        creation_request_id: str | None = None,
    ) -> CrudResponseModel:
        """使用模板创建新脑图"""
        template = await MindmapTemplateDao.get_template_by_id(db, template_id)
        if not template:
            raise ServiceException(message='模板不存在')

        # 解析 node_tree
        node_tree = template.node_tree
        if isinstance(node_tree, str):
            node_tree = json.loads(node_tree)
        node_tree = await MindmapTagPortabilityService.prepare_tree_for_owner(
            db,
            node_tree,
            target_owner_id=user_id,
        )

        # 复制为新脑图 (lazy import to avoid circular dependency)
        from module_mindmap.entity.vo.mindmap_vo import MindmapModel  # noqa: PLC0415
        new_mindmap = MindmapModel(
            name=f'{template.name}',
            description=template.description,
            owner_id=user_id,
            layout=template.layout,
            theme=template.theme,
            node_tree=node_tree,
            view_data=template.view_data,
            document_data=template.document_data,
            create_by=user_name,
            create_time=datetime.now(),
            update_by=user_name,
            update_time=datetime.now(),
        )

        from module_mindmap.service.mindmap_service import MindmapService  # noqa: PLC0415
        return await MindmapService.add_mindmap_services(
            db,
            new_mindmap,
            creation_request_id=creation_request_id,
            creation_operation='template',
            creation_intent={'templateId': template_id},
        )

    # ── 管理接口（管理员） ──

    @classmethod
    async def publish_template(
        cls, db: AsyncSession, model: MindmapTemplatePublishModel, user_name: str,
    ) -> CrudResponseModel:
        """发布模板（从现有脑图复制）"""
        source = await MindmapDao.get_mindmap_by_id(db, model.mindmap_id)
        if not source:
            raise ServiceException(message='源脑图不存在')
        if model.template_category_id is not None:
            category = await MindmapTemplateDao.get_category_by_id(
                db,
                model.template_category_id,
                for_update=True,
            )
            if not category:
                raise ServiceException(message='模板分类不存在')

        node_tree = None
        if getattr(source, 'schema_version', 1) >= SCHEMA_VERSION:
            node_tree = await MindmapDocumentService.load_tree(db, source.id, required=True)
        if not node_tree:
            node_tree = source.node_tree
        if isinstance(node_tree, str):
            node_tree = json.loads(node_tree)
        node_tree = await MindmapTagPortabilityService.prepare_tree_for_owner(
            db,
            node_tree,
            target_owner_id=0,
        )
        node_tree_str = node_tree if isinstance(node_tree, str) else json.dumps(node_tree, ensure_ascii=False)

        try:
            template = await MindmapTemplateDao.publish_template(db, {
                'name': model.name,
                'description': model.description,
                'owner_id': 0,  # 系统模板
                'layout': source.layout,
                'theme': source.theme,
                'node_tree': node_tree_str,
                'view_data': source.view_data,
                'document_data': source.document_data,
                'cover_image': model.cover_image,
                'is_template': 1,
                'template_category_id': model.template_category_id,
                'create_by': user_name,
                'create_time': datetime.now(),
                'update_by': user_name,
                'update_time': datetime.now(),
                'del_flag': '0',
            })
            # AsyncSession 默认会在 commit 后使 ORM 属性过期；主键必须在提交前固定，
            # 避免响应阶段隐式触发缺少 greenlet 上下文的异步查询。
            template_id = template.id
            await db.commit()
            return CrudResponseModel(
                is_success=True,
                message='模板发布成功',
                result={'id': template_id},
            )
        except Exception:
            await db.rollback()
            raise

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
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def add_category(cls, db: AsyncSession, name: str, sort_order: int = 0) -> CrudResponseModel:
        """新增模板分类"""
        normalized_name = normalize_template_text(name)
        if not normalized_name:
            raise ServiceException(message='分类名称不能为空')
        if len(normalized_name) > MAX_TEMPLATE_CATEGORY_NAME_LENGTH:
            raise ServiceException(message=f'分类名称不能超过 {MAX_TEMPLATE_CATEGORY_NAME_LENGTH} 个字符')
        if await MindmapTemplateDao.get_category_by_name(db, normalized_name):
            raise ServiceException(message='模板分类名称已存在')
        try:
            await MindmapTemplateDao.add_category(db, {
                'name': normalized_name,
                'sort_order': sort_order,
            })
            await db.commit()
            return CrudResponseModel(is_success=True, message='分类创建成功')
        except IntegrityError as exc:
            await db.rollback()
            raise ServiceException(message='模板分类名称已存在') from exc
        except Exception:
            await db.rollback()
            raise

    @classmethod
    async def delete_category(cls, db: AsyncSession, category_id: int) -> CrudResponseModel:
        """删除模板分类"""
        category = await MindmapTemplateDao.get_category_by_id(db, category_id, for_update=True)
        if not category:
            raise ServiceException(message='模板分类不存在')
        template_count = await MindmapTemplateDao.count_templates_in_category(db, category_id)
        if template_count:
            raise ServiceException(message=f'该分类仍有 {template_count} 个模板，请先下架或调整模板分类')
        try:
            await MindmapTemplateDao.delete_category(db, category_id)
            await db.commit()
            return CrudResponseModel(is_success=True, message='分类删除成功')
        except Exception:
            await db.rollback()
            raise
