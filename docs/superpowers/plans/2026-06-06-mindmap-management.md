# 脑图管理全功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 RuoYi-Vue3-FastAPI 后台集成完整的脑图管理功能，包括后端 CRUD API、前端管理列表、实时协作、版本历史、分享权限和模板市场。

**Architecture:** 后端补全 Controller 层暴露 REST API，前端新建管理列表页 + 改造编辑器对接后端存储。Phase 2+ 在此基础上叠加 WebSocket(Yjs)、版本历史、分享权限、模板市场。

**Tech Stack:** FastAPI + SQLAlchemy Async + Vue 3 + Element Plus + simple-mind-map + Yjs (Phase 2)

---

## 阶段总览

| Phase | 内容 | 前置依赖 |
|-------|------|----------|
| 1 | 后端 API + 前端对接 + 脑图管理列表页 | 无 |
| 2 | Yjs + WebSocket 实时协作 | Phase 1 |
| 3 | 版本历史（智能版本） | Phase 1 |
| 4 | 分享与协作权限 | Phase 1 + 2 |
| 5 | 模板市场 | Phase 1 |

---

# Phase 1: 后端 API + 前端对接 + 脑图管理列表页

## File Structure

### 新建文件
- `ruoyi-fastapi-backend/module_mindmap/controller/mindmap_controller.py` — REST API 路由
- `ruoyi-fastapi-frontend/src/api/mindmap/mindmap.js` — 前端 API 层
- `ruoyi-fastapi-frontend/src/views/mindmap/index.vue` — 脑图管理列表页
- `ruoyi-fastapi-frontend/src/views/mindmap/edit.vue` — 脑图编辑器页面
- `ruoyi-fastapi-test/mindmap/test_mindmap_management.py` — API 集成测试

### 修改文件
- `ruoyi-fastapi-backend/module_mindmap/service/mindmap_service.py` — 添加所有权校验、导入服务
- `ruoyi-fastapi-backend/module_mindmap/dao/mindmap_dao.py` — 添加导入 DAO、用户脑图查询
- `ruoyi-fastapi-frontend/src/components/MindMap/Edit.vue` — 对接后端 API 替代 localStorage
- `ruoyi-fastapi-frontend/src/components/MindMap/useStore.js` — 添加后端数据源支持
- `ruoyi-fastapi-frontend/src/router/index.js` — 移除 test 路由，添加正式路由
- `sql/ruoyi-fastapi.sql` — 添加脑图管理菜单和权限数据

---

## Task 1: 后端 Service 层 — 所有权校验与增强

**Files:**
- Modify: `ruoyi-fastapi-backend/module_mindmap/service/mindmap_service.py`

所有权校验必须在 Controller 之前就位，避免 Controller 调用时出现权限漏洞。

- [ ] **Step 1: 为 detail/edit/rename/delete 添加所有权校验**

修改 `mindmap_service.py`，完整替换以下方法：

```python
@classmethod
async def get_mindmap_detail_services(cls, query_db: AsyncSession, mindmap_id: int, user_id: int) -> MindmapModel:
    """获取思维导图详细信息（含所有权校验）"""
    mindmap = await MindmapDao.get_mindmap_by_id(query_db, mindmap_id)
    if not mindmap:
        raise ServiceException(message='思维导图不存在')
    if mindmap.owner_id != user_id:
        raise ServiceException(message='无访问权限')

    result_dict = CamelCaseUtil.transform_result(mindmap)
    if isinstance(result_dict.get('node_tree'), str):
        result_dict['node_tree'] = json.loads(result_dict['node_tree'])
    return MindmapModel(**result_dict)


@classmethod
async def edit_mindmap_services(cls, query_db: AsyncSession, page_object: MindmapModel, user_id: int) -> CrudResponseModel:
    """编辑思维导图元数据（名称、描述、封面等）"""
    mindmap = await MindmapDao.get_mindmap_by_id(query_db, page_object.id)
    if not mindmap:
        raise ServiceException(message='思维导图不存在')
    if mindmap.owner_id != user_id:
        raise ServiceException(message='无编辑权限')

    if page_object.name and page_object.name != mindmap.name:
        is_unique = await MindmapDao.check_name_unique(
            query_db, page_object.name, mindmap.owner_id, exclude_id=page_object.id
        )
        if not is_unique:
            raise ServiceException(message=f'修改思维导图失败，名称{page_object.name}已存在')

    try:
        update_data = page_object.model_dump(exclude_unset=True, exclude={'node_tree', 'view_data'})
        await MindmapDao.edit_mindmap_dao(query_db, update_data)
        await query_db.commit()
        return CrudResponseModel(is_success=True, message='更新成功')
    except Exception as e:
        await query_db.rollback()
        raise e


@classmethod
async def rename_mindmap_services(
    cls, query_db: AsyncSession, page_object: MindmapRenameModel, user_id: int
) -> CrudResponseModel:
    """重命名思维导图"""
    mindmap = await MindmapDao.get_mindmap_by_id(query_db, page_object.id)
    if not mindmap:
        raise ServiceException(message='思维导图不存在')
    if mindmap.owner_id != user_id:
        raise ServiceException(message='无编辑权限')

    is_unique = await MindmapDao.check_name_unique(
        query_db, page_object.name, mindmap.owner_id, exclude_id=page_object.id
    )
    if not is_unique:
        raise ServiceException(message=f'名称{page_object.name}已存在')

    try:
        await MindmapDao.edit_mindmap_dao(query_db, {
            'id': page_object.id,
            'name': page_object.name,
            'update_time': datetime.now(),
        })
        await query_db.commit()
        return CrudResponseModel(is_success=True, message='重命名成功')
    except Exception as e:
        await query_db.rollback()
        raise e


@classmethod
async def delete_mindmap_services(
    cls, query_db: AsyncSession, page_object: DeleteMindmapModel, user_id: int
) -> CrudResponseModel:
    """删除思维导图（含所有权校验）"""
    if not page_object.mindmap_ids:
        raise ServiceException(message='传入思维导图ID为空')

    id_list = [int(i) for i in page_object.mindmap_ids.split(',') if i.strip()]

    # 逐个校验所有权
    for mindmap_id in id_list:
        mindmap = await MindmapDao.get_mindmap_by_id(query_db, mindmap_id)
        if mindmap and mindmap.owner_id != user_id:
            raise ServiceException(message=f'无权限删除脑图ID={mindmap_id}')

    try:
        await MindmapDao.batch_delete_mindmap_dao(query_db, id_list)
        await query_db.commit()
        return CrudResponseModel(is_success=True, message='删除成功')
    except Exception as e:
        await query_db.rollback()
        raise e
```

注意 `get_mindmap_detail_services` 签名变更：新增 `user_id: int` 参数。`copy_mindmap_services` 已经接收 `user_id`，无需修改。

- [ ] **Step 2: 提交**

```bash
git add ruoyi-fastapi-backend/module_mindmap/service/mindmap_service.py
git commit -m "fix(mindmap): add ownership validation to detail/edit/rename/delete services"
```

---

## Task 2: 后端 Controller — 完整 CRUD 接口

**Files:**
- Create: `ruoyi-fastapi-backend/module_mindmap/controller/mindmap_controller.py`

注意：本 Task 创建 Controller 时已适配 Task 1 的 Service 签名（含 `user_id` 参数），无需后续返工。

- [ ] **Step 1: 创建 mindmap_controller.py**

```python
from datetime import datetime
from typing import Annotated

from fastapi import Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel, ResponseBaseModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_mindmap.entity.vo.mindmap_vo import (
    DeleteMindmapModel,
    MindmapContentUpdateModel,
    MindmapImportModel,
    MindmapModel,
    MindmapPageQueryModel,
    MindmapRenameModel,
)
from module_mindmap.service.mindmap_service import MindmapService
from utils.log_util import logger
from utils.response_util import ResponseUtil

mindmap_controller = APIRouterPro(
    prefix='/mindmap',
    order_num=20,
    tags=['脑图管理'],
    dependencies=[PreAuthDependency()],
)


# ──────────────────── 列表 ────────────────────

@mindmap_controller.get(
    '/list',
    summary='获取脑图分页列表接口',
    description='用于获取当前用户的脑图分页列表',
    response_model=PageResponseModel[MindmapModel],
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:list')],
)
async def get_mindmap_list(
    request: Request,
    mindmap_page_query: Annotated[MindmapPageQueryModel, Query()],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    mindmap_page_query.owner_id = current_user.user.user_id
    mindmap_page_query_result = await MindmapService.get_mindmap_list_services(
        query_db, mindmap_page_query, is_page=True
    )
    logger.info('获取脑图列表成功')
    return ResponseUtil.success(model_content=mindmap_page_query_result)


# ──────────────────── 详情 ────────────────────

@mindmap_controller.get(
    '/{mindmap_id}',
    summary='获取脑图详情接口',
    description='用于获取指定脑图的详细信息（含完整节点树）',
    response_model=DataResponseModel[MindmapModel],
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:query')],
)
async def get_mindmap_detail(
    request: Request,
    mindmap_id: Annotated[int, Path(description='脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    mindmap_detail_result = await MindmapService.get_mindmap_detail_services(
        query_db, mindmap_id, current_user.user.user_id
    )
    logger.info(f'获取脑图ID为{mindmap_id}的详情成功')
    return ResponseUtil.success(data=mindmap_detail_result)


# ──────────────────── 新增 ────────────────────

@mindmap_controller.post(
    '',
    summary='新增脑图接口',
    description='用于新增脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:add')],
)
@Log(title='脑图管理', business_type=BusinessType.INSERT)
async def add_mindmap(
    request: Request,
    add_mindmap: MindmapModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    add_mindmap.owner_id = current_user.user.user_id
    add_mindmap.create_by = current_user.user.user_name
    add_mindmap.create_time = datetime.now()
    add_mindmap.update_by = current_user.user.user_name
    add_mindmap.update_time = datetime.now()
    result = await MindmapService.add_mindmap_services(query_db, add_mindmap)
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 编辑元数据 ────────────────────

@mindmap_controller.put(
    '',
    summary='编辑脑图元数据接口',
    description='用于编辑脑图名称、描述、封面等元数据',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图管理', business_type=BusinessType.UPDATE)
async def edit_mindmap(
    request: Request,
    edit_mindmap: MindmapModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    edit_mindmap.update_by = current_user.user.user_name
    edit_mindmap.update_time = datetime.now()
    result = await MindmapService.edit_mindmap_services(
        query_db, edit_mindmap, current_user.user.user_id
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 删除 ────────────────────

@mindmap_controller.delete(
    '/{mindmap_ids}',
    summary='删除脑图接口',
    description='用于批量删除脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:remove')],
)
@Log(title='脑图管理', business_type=BusinessType.DELETE)
async def delete_mindmap(
    request: Request,
    mindmap_ids: Annotated[str, Path(description='需要删除的脑图ID，逗号分隔')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    delete_mindmap = DeleteMindmapModel(mindmapIds=mindmap_ids)
    result = await MindmapService.delete_mindmap_services(
        query_db, delete_mindmap, current_user.user.user_id
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 重命名 ────────────────────

@mindmap_controller.put(
    '/rename',
    summary='重命名脑图接口',
    description='用于重命名脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
@Log(title='脑图管理', business_type=BusinessType.UPDATE)
async def rename_mindmap(
    request: Request,
    rename_model: MindmapRenameModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.rename_mindmap_services(
        query_db, rename_model, current_user.user.user_id
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 复制 ────────────────────

@mindmap_controller.post(
    '/copy/{mindmap_id}',
    summary='复制脑图接口',
    description='用于复制指定脑图',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:add')],
)
@Log(title='脑图管理', business_type=BusinessType.INSERT)
async def copy_mindmap(
    request: Request,
    mindmap_id: Annotated[int, Path(description='源脑图ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.copy_mindmap_services(
        query_db, mindmap_id, current_user.user.user_id
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 更新内容（自动保存） ────────────────────

@mindmap_controller.put(
    '/content',
    summary='更新脑图内容接口',
    description='用于自动保存脑图内容（node_tree, view_data, layout, theme）',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:edit')],
)
async def update_mindmap_content(
    request: Request,
    content_model: MindmapContentUpdateModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    result = await MindmapService.update_content_services(
        query_db, content_model, current_user.user.user_id
    )
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)


# ──────────────────── 导入 ────────────────────

@mindmap_controller.post(
    '/import',
    summary='从本地存储导入脑图',
    description='将localStorage中的脑图数据导入到后端',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('mindmap:mindmap:add')],
)
@Log(title='脑图管理', business_type=BusinessType.INSERT)
async def import_mindmap(
    request: Request,
    import_model: MindmapImportModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    mindmap_model = MindmapModel(
        name=import_model.name,
        owner_id=current_user.user.user_id,
        layout=import_model.layout,
        theme=import_model.theme,
        node_tree=import_model.root,
        view_data=import_model.view,
        create_by=current_user.user.user_name,
        create_time=datetime.now(),
        update_by=current_user.user.user_name,
        update_time=datetime.now(),
    )
    result = await MindmapService.add_mindmap_services(query_db, mindmap_model)
    logger.info(result.message)
    return ResponseUtil.success(msg=result.message)
```

- [ ] **Step 2: 验证路由自动注册**

启动后端服务，检查 `/docs` 页面确认所有 8 个端点已注册：

```bash
cd ruoyi-fastapi-backend
python server.py
# 访问 http://localhost:9099/docs 确认路由
```

Expected: Swagger UI 中出现 `脑图管理` 分组，包含 GET `/list`、GET `/{id}`、POST `/`、PUT `/`、DELETE `/{ids}`、PUT `/rename`、POST `/copy/{id}`、PUT `/content`、POST `/import`。

- [ ] **Step 3: 提交**

```bash
git add ruoyi-fastapi-backend/module_mindmap/controller/mindmap_controller.py
git commit -m "feat(mindmap): add controller with all CRUD, rename, copy, content, import endpoints"
```

---

## Task 3: 菜单权限 SQL

**Files:**
- Create: `sql/mindmap_menu.sql`

- [ ] **Step 1: 创建菜单和权限 SQL**

使用 ID 9000+ 范围，避免与现有菜单冲突：

```sql
-- 脑图管理菜单（parent_id=0 为一级菜单）
INSERT INTO sys_menu VALUES('9000', '脑图管理', '0', '6', 'mindmap', NULL, '', '1', '0', 'M', '0', '0', '', 'mindmap', 'admin', NOW(), '', NULL, '脑图管理目录');

-- 脑图列表页（parent_id=9000）
INSERT INTO sys_menu VALUES('9001', '脑图列表', '9000', '1', 'index', 'mindmap/index', '', '1', '0', 'C', '0', '0', 'mindmap:mindmap:list', 'mindmap', 'admin', NOW(), '', NULL, '脑图列表菜单');

-- 脑图管理按钮权限
INSERT INTO sys_menu VALUES('9002', '脑图查询', '9001', '1', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:query', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES('9003', '脑图新增', '9001', '2', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:add', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES('9004', '脑图修改', '9001', '3', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:edit', '#', 'admin', NOW(), '', NULL, '');
INSERT INTO sys_menu VALUES('9005', '脑图删除', '9001', '4', '', '', '', '1', '0', 'F', '0', '0', 'mindmap:mindmap:remove', '#', 'admin', NOW(), '', NULL, '');
```

- [ ] **Step 2: 验证 ID 无冲突**

执行前在数据库中确认 ID 9000-9005 未被占用：

```sql
SELECT menu_id FROM sys_menu WHERE menu_id BETWEEN 9000 AND 9005;
```

Expected: 返回空结果。

- [ ] **Step 3: 执行 SQL 并提交**

```bash
git add sql/mindmap_menu.sql
git commit -m "feat(mindmap): add menu entries and permission data"
```

---

## Task 4: 前端 API 层

**Files:**
- Create: `ruoyi-fastapi-frontend/src/api/mindmap/mindmap.js`

- [ ] **Step 1: 创建 API 文件**

```javascript
import request from '@/utils/request'

// 查询脑图列表
export function listMindmap(query) {
  return request({
    url: '/mindmap/list',
    method: 'get',
    params: query
  })
}

// 查询脑图详情
export function getMindmap(mindmapId) {
  return request({
    url: '/mindmap/' + mindmapId,
    method: 'get'
  })
}

// 新增脑图
export function addMindmap(data) {
  return request({
    url: '/mindmap',
    method: 'post',
    data: data
  })
}

// 编辑脑图元数据
export function updateMindmap(data) {
  return request({
    url: '/mindmap',
    method: 'put',
    data: data
  })
}

// 删除脑图
export function delMindmap(mindmapIds) {
  return request({
    url: '/mindmap/' + mindmapIds,
    method: 'delete'
  })
}

// 重命名脑图
export function renameMindmap(data) {
  return request({
    url: '/mindmap/rename',
    method: 'put',
    data: data
  })
}

// 复制脑图
export function copyMindmap(mindmapId) {
  return request({
    url: '/mindmap/copy/' + mindmapId,
    method: 'post'
  })
}

// 更新脑图内容（自动保存）
export function updateMindmapContent(data) {
  return request({
    url: '/mindmap/content',
    method: 'put',
    data: data
  })
}

// 从本地存储导入脑图
export function importMindmap(data) {
  return request({
    url: '/mindmap/import',
    method: 'post',
    data: data
  })
}
```

- [ ] **Step 2: 提交**

```bash
git add ruoyi-fastapi-frontend/src/api/mindmap/mindmap.js
git commit -m "feat(mindmap): add frontend API layer for mindmap CRUD"
```

---

## Task 5: 前端脑图管理列表页

**Files:**
- Create: `ruoyi-fastapi-frontend/src/views/mindmap/index.vue`

- [ ] **Step 1: 创建列表页**

包含"查看"（只读）、"编辑"、"复制"、"删除"四个操作按钮：

```vue
<template>
  <div class="app-container">
    <el-form :model="queryParams" ref="queryRef" :inline="true" v-show="showSearch">
      <el-form-item label="脑图名称" prop="name">
        <el-input
          v-model="queryParams.name"
          placeholder="请输入脑图名称"
          clearable
          style="width: 200px"
          @keyup.enter="handleQuery"
        />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-select v-model="queryParams.status" placeholder="状态" clearable style="width: 200px">
          <el-option label="正常" :value="0" />
          <el-option label="归档" :value="1" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" icon="Search" @click="handleQuery">搜索</el-button>
        <el-button icon="Refresh" @click="resetQuery">重置</el-button>
      </el-form-item>
    </el-form>

    <el-row :gutter="10" class="mb8">
      <el-col :span="1.5">
        <el-button type="primary" plain icon="Plus" @click="handleAdd" v-hasPermi="['mindmap:mindmap:add']">
          新建脑图
        </el-button>
      </el-col>
      <el-col :span="1.5">
        <el-button type="danger" plain icon="Delete" :disabled="multiple" @click="handleDelete" v-hasPermi="['mindmap:mindmap:remove']">
          删除
        </el-button>
      </el-col>
      <right-toolbar v-model:showSearch="showSearch" @queryTable="getList"></right-toolbar>
    </el-row>

    <el-table v-loading="loading" :data="mindmapList" @selection-change="handleSelectionChange">
      <el-table-column type="selection" width="55" align="center" />
      <el-table-column label="ID" align="center" prop="id" width="80" />
      <el-table-column label="名称" align="center" prop="name" :show-overflow-tooltip="true" />
      <el-table-column label="描述" align="center" prop="description" :show-overflow-tooltip="true" />
      <el-table-column label="布局" align="center" prop="layout" width="140" />
      <el-table-column label="版本数" align="center" prop="versionCount" width="80" />
      <el-table-column label="状态" align="center" prop="status" width="80">
        <template #default="scope">
          <el-tag :type="scope.row.status === 0 ? 'success' : 'info'">
            {{ scope.row.status === 0 ? '正常' : '归档' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" align="center" prop="updateTime" width="180">
        <template #default="scope">
          <span>{{ parseTime(scope.row.updateTime) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="320" align="center" class-name="small-padding fixed-width">
        <template #default="scope">
          <el-button link type="primary" icon="View" @click="handleView(scope.row)" v-hasPermi="['mindmap:mindmap:query']">
            查看
          </el-button>
          <el-button link type="primary" icon="Edit" @click="handleEdit(scope.row)" v-hasPermi="['mindmap:mindmap:edit']">
            编辑
          </el-button>
          <el-button link type="primary" icon="CopyDocument" @click="handleCopy(scope.row)" v-hasPermi="['mindmap:mindmap:add']">
            复制
          </el-button>
          <el-button link type="primary" icon="Delete" @click="handleDelete(scope.row)" v-hasPermi="['mindmap:mindmap:remove']">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <pagination
      v-show="total > 0"
      :total="total"
      v-model:page="queryParams.pageNum"
      v-model:limit="queryParams.pageSize"
      @pagination="getList"
    />

    <!-- 重命名对话框 -->
    <el-dialog title="重命名" v-model="renameOpen" width="400px" append-to-body>
      <el-form ref="renameRef" :model="renameForm" :rules="renameRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="renameForm.name" placeholder="请输入新名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="primary" @click="submitRename">确定</el-button>
        <el-button @click="renameOpen = false">取消</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="MindmapManagement">
import { listMindmap, delMindmap, renameMindmap, copyMindmap, addMindmap } from '@/api/mindmap/mindmap'
import { useRouter } from 'vue-router'

const router = useRouter()
const { proxy } = getCurrentInstance()

const mindmapList = ref([])
const loading = ref(true)
const showSearch = ref(true)
const ids = ref([])
const multiple = ref(true)
const total = ref(0)
const renameOpen = ref(false)

const data = reactive({
  queryParams: {
    pageNum: 1,
    pageSize: 10,
    name: undefined,
    status: undefined
  },
  renameForm: {
    id: undefined,
    name: ''
  },
  renameRules: {
    name: [{ required: true, message: '名称不能为空', trigger: 'blur' }]
  }
})

const { queryParams, renameForm, renameRules } = toRefs(data)

/** 查询脑图列表 */
function getList() {
  loading.value = true
  listMindmap(queryParams.value).then(response => {
    mindmapList.value = response.rows
    total.value = response.total
    loading.value = false
  })
}

/** 搜索 */
function handleQuery() {
  queryParams.value.pageNum = 1
  getList()
}

/** 重置 */
function resetQuery() {
  proxy.resetForm('queryRef')
  handleQuery()
}

/** 多选 */
function handleSelectionChange(selection) {
  ids.value = selection.map(item => item.id)
  multiple.value = !selection.length
}

/** 新建脑图 */
function handleAdd() {
  addMindmap({
    name: '未命名脑图',
    nodeTree: { data: { text: '中心主题' }, children: [] }
  }).then(response => {
    proxy.$modal.msgSuccess('新建成功')
    getList()
  })
}

/** 查看（只读模式） */
function handleView(row) {
  router.push({ path: '/mindmap/edit', query: { id: row.id, readonly: '1' } })
}

/** 编辑（跳转到编辑器页面） */
function handleEdit(row) {
  router.push({ path: '/mindmap/edit', query: { id: row.id } })
}

/** 复制 */
function handleCopy(row) {
  copyMindmap(row.id).then(response => {
    proxy.$modal.msgSuccess('复制成功')
    getList()
  })
}

/** 删除 */
function handleDelete(row) {
  const mindmapIds = row.id || ids.value.join(',')
  proxy.$modal.confirm('是否确认删除所选脑图？').then(() => {
    return delMindmap(mindmapIds)
  }).then(() => {
    getList()
    proxy.$modal.msgSuccess('删除成功')
  }).catch(() => {})
}

/** 重命名 */
function handleRename(row) {
  data.renameForm = { id: row.id, name: row.name }
  renameOpen.value = true
}

function submitRename() {
  proxy.$refs['renameRef'].validate(valid => {
    if (valid) {
      renameMindmap(data.renameForm).then(response => {
        proxy.$modal.msgSuccess('重命名成功')
        renameOpen.value = false
        getList()
      })
    }
  })
}

getList()
</script>
```

- [ ] **Step 2: 提交**

```bash
git add ruoyi-fastapi-frontend/src/views/mindmap/index.vue
git commit -m "feat(mindmap): add mindmap management list page with view/edit/copy/delete"
```

---

## Task 6: 前端编辑器页面

**Files:**
- Create: `ruoyi-fastapi-frontend/src/views/mindmap/edit.vue`
- Modify: `ruoyi-fastapi-frontend/src/router/index.js`

- [ ] **Step 1: 创建编辑器页面**

```vue
<template>
  <div class="mindmap-edit-page">
    <div class="mindmap-edit-header">
      <el-page-header @back="goBack" :title="'返回列表'">
        <template #content>
          <span class="mindmap-title" @click="showRenameDialog">
            {{ mindmapName || '加载中...' }}
            <el-icon v-if="!isReadonly"><Edit /></el-icon>
          </span>
          <el-tag v-if="isReadonly" type="info" size="small" style="margin-left: 8px;">只读</el-tag>
        </template>
      </el-page-header>
    </div>
    <div class="mindmap-edit-body">
      <Toolbar v-if="!isZenMode && !isReadonly" />
      <div class="mindmap-editor-container">
        <Edit ref="editRef" :mindmap-id="mindmapId" :readonly="isReadonly" @name-change="onNameChange" />
      </div>
      <NavigatorToolbar v-if="!isZenMode" :mindMap="mindMapInstance" />
    </div>

    <!-- 重命名对话框 -->
    <el-dialog title="重命名" v-model="renameOpen" width="400px">
      <el-form ref="renameRef" :model="renameForm" :rules="renameRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="renameForm.name" placeholder="请输入新名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button type="primary" @click="submitRename">确定</el-button>
        <el-button @click="renameOpen = false">取消</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="MindmapEditorPage">
import { Edit as EditIcon } from '@element-plus/icons-vue'
import Toolbar from '@/components/MindMap/Toolbar.vue'
import Edit from '@/components/MindMap/Edit.vue'
import NavigatorToolbar from '@/components/MindMap/NavigatorToolbar.vue'
import { store } from '@/components/MindMap/useStore'
import { renameMindmap } from '@/api/mindmap/mindmap'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const { proxy } = getCurrentInstance()

const editRef = ref(null)
const mindmapId = computed(() => Number(route.query.id))
const isReadonly = computed(() => route.query.readonly === '1')
const mindmapName = ref('')
const renameOpen = ref(false)
const isZenMode = computed(() => store.localConfig.isZenMode)
const mindMapInstance = computed(() => editRef.value?.mindMap || null)

const renameForm = reactive({ id: undefined, name: '' })
const renameRules = {
  name: [{ required: true, message: '名称不能为空', trigger: 'blur' }]
}

function goBack() {
  router.push('/mindmap/index')
}

function onNameChange(name) {
  mindmapName.value = name
}

function showRenameDialog() {
  if (isReadonly.value) return
  renameForm.id = mindmapId.value
  renameForm.name = mindmapName.value
  renameOpen.value = true
}

function submitRename() {
  proxy.$refs['renameRef'].validate(valid => {
    if (valid) {
      renameMindmap(renameForm).then(response => {
        proxy.$modal.msgSuccess('重命名成功')
        mindmapName.value = renameForm.name
        renameOpen.value = false
      })
    }
  })
}
</script>

<style scoped lang="scss">
.mindmap-edit-page {
  height: calc(100vh - 84px);
  display: flex;
  flex-direction: column;
  background: #f5f5f5;
}
.mindmap-edit-header {
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  .mindmap-title {
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    &:hover { color: var(--el-color-primary); }
  }
}
.mindmap-edit-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}
.mindmap-editor-container {
  flex: 1;
  display: flex;
  overflow: hidden;
}
</style>
```

- [ ] **Step 2: 更新路由配置**

在 `src/router/index.js` 中，移除旧的 test/mindmap 路由，替换为：

```javascript
{
  path: '/mindmap/edit',
  component: Layout,
  hidden: true,
  children: [
    {
      path: '',
      component: () => import('@/views/mindmap/edit'),
      name: 'MindmapEditor',
      meta: { title: '脑图编辑' }
    }
  ]
}
```

- [ ] **Step 3: 提交**

```bash
git add ruoyi-fastapi-frontend/src/views/mindmap/edit.vue ruoyi-fastapi-frontend/src/router/index.js
git commit -m "feat(mindmap): add editor page with readonly mode and rename"
```

---

## Task 7: 前端编辑器对接后端 API

**Files:**
- Modify: `ruoyi-fastapi-frontend/src/components/MindMap/Edit.vue`

这是 Phase 1 最关键的一步：将 Edit.vue 从 localStorage 数据源切换到后端 API。

- [ ] **Step 1: 修改 Edit.vue — 添加 props 和 API 对接**

在 `<script setup>` 中添加 props：

```javascript
const props = defineProps({
  mindmapId: { type: Number, default: null },
  readonly: { type: Boolean, default: false }
})

const emit = defineEmits(['name-change'])
```

修改 `initMindMap` 函数，当有 `mindmapId` 时从后端加载：

```javascript
import { getMindmap, updateMindmapContent } from '@/api/mindmap/mindmap'

let autoSaveTimer = null
const isSaving = ref(false)
const lastSaveTime = ref(0)
const pendingSave = ref(false)

async function initMindMap() {
  if (!mindMapContainerRef.value) return

  let root = defaultData
  let layout = 'logicalStructure'
  let themeTemplate = 'default'
  let themeConfig = {}
  let viewData = null

  // 如果有 mindmapId，从后端加载
  if (props.mindmapId) {
    try {
      const response = await getMindmap(props.mindmapId)
      const data = response.data
      root = data.nodeTree || defaultData
      layout = data.layout || 'logicalStructure'
      themeTemplate = data.theme?.template || 'default'
      themeConfig = data.theme?.config || {}
      viewData = data.viewData || null
      emit('name-change', data.name)
    } catch (error) {
      ElMessage.error('加载脑图失败')
      return
    }
  } else {
    // 回退到 localStorage
    const savedData = actions.getData()
    const savedConfig = actions.getConfig() || {}
    root = savedData?.root || defaultData
    layout = savedData?.layout || 'logicalStructure'
    themeTemplate = savedData?.theme?.template || 'default'
    themeConfig = savedData?.theme?.config || {}
    viewData = savedData?.view || null
  }

  // ... 后续 MindMap 初始化代码不变（new MindMap({...})）
}
```

- [ ] **Step 2: 修改自动保存逻辑**

替换 `onBusDataChange` 和 `manualSave`，使用 5 秒防抖 + 并发控制：

```javascript
const AUTO_SAVE_DELAY = 5000 // 5秒防抖，避免频繁请求

function onBusDataChange(data) {
  if (props.mindmapId) {
    // 后端模式：防抖自动保存到后端
    clearTimeout(autoSaveTimer)
    autoSaveTimer = setTimeout(() => {
      saveToBackend()
    }, AUTO_SAVE_DELAY)
  } else {
    // localStorage 模式：保持不变
    actions.storeData({ root: data })
  }
}

async function saveToBackend() {
  if (!mindMap.value || !props.mindmapId || props.readonly) return

  // 并发控制：如果正在保存，标记为待保存，等当前保存完成后再触发
  if (isSaving.value) {
    pendingSave.value = true
    return
  }

  isSaving.value = true
  pendingSave.value = false
  try {
    const fullData = mindMap.value.getData(true)
    await updateMindmapContent({
      id: props.mindmapId,
      nodeTree: fullData.root,
      viewData: fullData.view,
      layout: fullData.layout,
      theme: fullData.theme
    })
    lastSaveTime.value = Date.now()
  } catch (error) {
    console.error('自动保存失败:', error)
  } finally {
    isSaving.value = false
    // 如果在保存期间有新的变更，立即触发下一次保存
    if (pendingSave.value) {
      pendingSave.value = false
      clearTimeout(autoSaveTimer)
      autoSaveTimer = setTimeout(() => saveToBackend(), AUTO_SAVE_DELAY)
    }
  }
}

function manualSave() {
  if (!mindMap.value) return
  const fullData = mindMap.value.getData(true)
  if (props.mindmapId) {
    // 手动保存：跳过防抖，立即保存
    clearTimeout(autoSaveTimer)
    saveToBackend()
    ElMessage.success('已保存到服务器')
  } else {
    actions.storeData(fullData)
    ElMessage.success('已保存')
  }
}
```

- [ ] **Step 3: 只读模式支持**

在 MindMap 初始化配置中，当 `props.readonly` 为 true 时设置只读：

```javascript
// 在 new MindMap({...}) 的配置中添加
const mm = new MindMap({
  el: mindMapContainerRef.value,
  data: root,
  // ... 其他配置不变
  readonly: props.readonly,  // 只读模式
  // ...
})

// 只读模式下不绑定保存事件
if (!props.readonly) {
  bus.on('data_change', onBusDataChange)
  bus.on('view_data_change', onBusViewDataChange)
  mm.keyCommand.addShortcut('Control+s', () => {
    manualSave()
  })
}
```

- [ ] **Step 4: 清理 onBeforeUnmount**

```javascript
onBeforeUnmount(() => {
  unbindBusEvents()
  window.removeEventListener('resize', handleResize)
  clearTimeout(autoSaveTimer)
  if (mindMap.value) {
    mindMap.value.destroy()
    mindMap.value = null
  }
  clearTimeout(storeConfigTimer)
  actions.resetState()
})
```

- [ ] **Step 5: 提交**

```bash
git add ruoyi-fastapi-frontend/src/components/MindMap/Edit.vue
git commit -m "feat(mindmap): integrate editor with backend API, add readonly mode and safe auto-save"
```

---

## Task 8: 集成测试

**Files:**
- Create: `ruoyi-fastapi-test/mindmap/test_mindmap_management.py`
- Create: `ruoyi-fastapi-test/mindmap/__init__.py`

- [ ] **Step 1: 创建测试文件**

```python
"""脑图管理模块集成测试"""
import pytest
from common.login_helper import LoginHelper
from common.config import test_config
import requests


BASE_URL = f'{test_config.base_url}/mindmap'


class TestMindmapManagement:
    """脑图管理测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """获取管理员 token"""
        self.headers = LoginHelper.get_admin_headers()
        self.created_ids = []

    def teardown_method(self):
        """清理创建的脑图"""
        for mid in self.created_ids:
            requests.delete(f'{BASE_URL}/{mid}', headers=self.headers)

    def test_add_mindmap(self):
        """测试新增脑图"""
        data = {
            'name': '测试脑图',
            'nodeTree': {'data': {'text': '根节点'}, 'children': []},
            'layout': 'logicalStructure'
        }
        res = requests.post(BASE_URL, json=data, headers=self.headers)
        assert res.json()['code'] == 200

    def test_list_mindmap(self):
        """测试查询脑图列表"""
        res = requests.get(f'{BASE_URL}/list', params={'pageNum': 1, 'pageSize': 10}, headers=self.headers)
        assert res.json()['code'] == 200
        assert 'rows' in res.json()

    def test_crud_lifecycle(self):
        """测试完整 CRUD 生命周期"""
        # 1. 新增
        data = {
            'name': 'CRUD测试脑图',
            'nodeTree': {'data': {'text': '中心'}, 'children': []},
        }
        res = requests.post(BASE_URL, json=data, headers=self.headers)
        assert res.json()['code'] == 200

        # 2. 列表查找
        res = requests.get(f'{BASE_URL}/list', params={'name': 'CRUD测试脑图'}, headers=self.headers)
        rows = res.json()['rows']
        assert len(rows) > 0
        mindmap_id = rows[0]['id']
        self.created_ids.append(mindmap_id)

        # 3. 详情
        res = requests.get(f'{BASE_URL}/{mindmap_id}', headers=self.headers)
        assert res.json()['code'] == 200
        assert res.json()['data']['name'] == 'CRUD测试脑图'

        # 4. 重命名
        res = requests.put(f'{BASE_URL}/rename', json={'id': mindmap_id, 'name': '已重命名'}, headers=self.headers)
        assert res.json()['code'] == 200

        # 5. 更新内容
        res = requests.put(f'{BASE_URL}/content', json={
            'id': mindmap_id,
            'nodeTree': {'data': {'text': '更新后'}, 'children': [{'data': {'text': '新子节点'}}]}
        }, headers=self.headers)
        assert res.json()['code'] == 200

        # 6. 复制
        res = requests.post(f'{BASE_URL}/copy/{mindmap_id}', headers=self.headers)
        assert res.json()['code'] == 200

        # 7. 删除
        res = requests.delete(f'{BASE_URL}/{mindmap_id}', headers=self.headers)
        assert res.json()['code'] == 200
        self.created_ids.clear()

    def test_nonexistent_mindmap(self):
        """测试访问不存在的脑图"""
        res = requests.get(f'{BASE_URL}/999999999', headers=self.headers)
        assert res.json()['code'] != 200

    def test_duplicate_name(self):
        """测试同用户下名称唯一性"""
        data = {
            'name': '唯一性测试脑图',
            'nodeTree': {'data': {'text': '中心'}, 'children': []},
        }
        # 第一次创建应成功
        res1 = requests.post(BASE_URL, json=data, headers=self.headers)
        assert res1.json()['code'] == 200

        # 第二次同名创建应失败
        res2 = requests.post(BASE_URL, json=data, headers=self.headers)
        assert res2.json()['code'] != 200
```

- [ ] **Step 2: 运行测试**

```bash
cd ruoyi-fastapi-test
pytest mindmap/test_mindmap_management.py -v
```

Expected: 所有测试 PASS。

- [ ] **Step 3: 提交**

```bash
git add ruoyi-fastapi-test/mindmap/
git commit -m "test(mindmap): add integration tests for mindmap CRUD lifecycle and edge cases"
```

---

# Phase 2: Yjs + WebSocket 实时协作

## 技术方案

**Yjs (CRDT)** 是实现实时协作的最佳选择：
- 天然支持树形结构（`Y.Map` + `Y.Array`）
- 内置 Awareness 协议实现多人光标
- 前端生态成熟（`y-websocket`, `y-protocols`）

### Yjs 数据模型设计（细粒度，非整体替换）

**关键决策**：不能把整个 `nodeTree` 当作一个 `Y.Map` 值来存储，否则每次更新都是整体替换，失去 CRDT 的意义。

采用细粒度映射方案：

```
Y.Doc
├── Y.Map('meta')                     # 脑图元数据
│   ├── layout: string
│   ├── theme: Y.Map
│   └── viewData: Y.Map
└── Y.Map('nodes')                    # 节点存储（扁平化，以 nodeId 为 key）
    ├── "root": Y.Map                 # 每个节点
    │   ├── data: Y.Map { text, richText, ... }
    │   ├── children: Y.Array<string> # 子节点 ID 列表
    │   └── parent: string            # 父节点 ID
    ├── "node_1": Y.Map { ... }
    └── "node_2": Y.Map { ... }
```

**优势**：
- 修改单个节点文本只触发该节点的 `Y.Map` 变更，不影响其他节点
- 添加/删除子节点只操作 `Y.Array` 的增删，CRDT 自动合并
- 移动节点只需修改 `parent` 和 `children` 数组
- 两个用户同时编辑不同节点不会冲突

### WebSocket 认证方案（安全方式）

**不使用 URL query parameter 传递 token**。改为连接后发送认证消息：

```
客户端连接 → 服务端 accept
客户端发送: { "type": "auth", "token": "jwt_token_here" }
服务端验证: 通过 → 发送 { "type": "auth_ok", "user": {...} }
           失败 → 发送 { "type": "auth_error", "message": "..." } + close(4001)
后续消息正常处理
```

这样 token 不会出现在 URL、日志或浏览器历史中。

### 后端 WebSocket 架构
- FastAPI 原生 WebSocket 端点
- 每个脑图对应一个 "room"，用户加入/离开 room
- 内存中维护 Yjs 文档状态，定期持久化到数据库

## 新增数据库表

```sql
CREATE TABLE mindmap_ws_state (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL,
    yjs_state MEDIUMBLOB COMMENT 'Yjs 文档二进制状态',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_ws_mindmap (mindmap_id)
) COMMENT '脑图 Yjs 文档持久化状态表';
```

## 新增文件

### 后端
- `module_mindmap/websocket/__init__.py`
- `module_mindmap/websocket/mindmap_ws.py` — WebSocket 端点
- `module_mindmap/websocket/yjs_doc.py` — Yjs 文档管理
- `module_mindmap/websocket/room_manager.py` — 房间管理器
- `module_mindmap/entity/do/mindmap_ws_state_do.py` — WS 状态 ORM

### 前端
- `src/components/MindMap/Collaborators.vue` — 协作者头像列表
- `src/utils/yjs-sync.js` — Yjs 同步逻辑（细粒度数据模型）
- `src/utils/ws-client.js` — WebSocket 客户端封装

## WebSocket 消息协议

```json
// ─── 认证 ───
// 客户端 → 服务端
{ "type": "auth", "token": "jwt_token" }
// 服务端 → 客户端
{ "type": "auth_ok", "user": { "id": 1, "name": "张三", "avatar": "..." } }
{ "type": "auth_error", "message": "token无效" }

// ─── 协作同步 ───
// 客户端 → 服务端
{ "type": "sync_step1", "state": "<base64>" }
{ "type": "sync_step2", "update": "<base64>" }
{ "type": "update", "update": "<base64>" }
{ "type": "awareness", "update": "<base64>" }

// 服务端 → 客户端
{ "type": "sync_init", "state": "<base64>" }
{ "type": "update", "update": "<base64>", "origin": "user_123" }
{ "type": "awareness", "update": "<base64>", "userId": 1 }
{ "type": "user_joined", "user": { "id": 1, "name": "张三", "avatar": "..." } }
{ "type": "user_left", "userId": 1 }
{ "type": "room_users", "users": [...] }
{ "type": "error", "message": "权限不足" }
```

## Task 1: WebSocket 基础设施

**Files:**
- Create: `ruoyi-fastapi-backend/module_mindmap/websocket/room_manager.py`
- Create: `ruoyi-fastapi-backend/module_mindmap/websocket/yjs_doc.py`
- Create: `ruoyi-fastapi-backend/module_mindmap/entity/do/mindmap_ws_state_do.py`

- [ ] **Step 1: 实现 RoomManager**

```python
"""脑图 WebSocket 房间管理器"""
import asyncio
from typing import Any


class RoomManager:
    """管理 WebSocket 房间：每个脑图一个房间"""

    def __init__(self):
        self._rooms: dict[int, set] = {}  # mindmap_id -> set of websocket connections
        self._user_info: dict[int, dict] = {}  # id(websocket) -> user info
        self._lock = asyncio.Lock()

    async def join(self, mindmap_id: int, websocket, user_info: dict):
        async with self._lock:
            if mindmap_id not in self._rooms:
                self._rooms[mindmap_id] = set()
            self._rooms[mindmap_id].add(websocket)
            self._user_info[id(websocket)] = user_info

    async def leave(self, mindmap_id: int, websocket):
        async with self._lock:
            if mindmap_id in self._rooms:
                self._rooms[mindmap_id].discard(websocket)
                if not self._rooms[mindmap_id]:
                    del self._rooms[mindmap_id]
            self._user_info.pop(id(websocket), None)

    async def broadcast(self, mindmap_id: int, message: Any, exclude=None):
        if mindmap_id not in self._rooms:
            return
        for ws in list(self._rooms[mindmap_id]):
            if ws != exclude:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    def get_room_users(self, mindmap_id: int) -> list[dict]:
        result = []
        if mindmap_id in self._rooms:
            for ws in self._rooms[mindmap_id]:
                info = self._user_info.get(id(ws))
                if info:
                    result.append(info)
        return result


room_manager = RoomManager()
```

- [ ] **Step 2: 创建 WS 状态 ORM 模型**

参照 `mindmap_do.py` 的模式：

```python
"""脑图 Yjs 文档持久化状态模型"""
from sqlalchemy import BigInteger, Column, DateTime
from sqlalchemy.dialects import mysql, postgresql
from config.database import Base
from config.env import DataBaseConfig
from datetime import datetime


class MindmapWsState(Base):
    __tablename__ = 'mindmap_ws_state'
    __table_args__ = ({'comment': '脑图Yjs文档持久化状态表'},)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    mindmap_id = Column(BigInteger, nullable=False, unique=True, comment='脑图ID')
    yjs_state = Column(
        mysql.MEDIUMBLOB if DataBaseConfig.db_type == 'mysql' else postgresql.BYTEA,
        nullable=True,
        comment='Yjs文档二进制状态',
    )
    updated_at = Column(DateTime, nullable=True, default=datetime.now, onupdate=datetime.now, comment='更新时间')
```

- [ ] **Step 3: 实现 Yjs 文档管理**

```python
"""Yjs 文档持久化管理"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from module_mindmap.entity.do.mindmap_ws_state_do import MindmapWsState


class YjsDocManager:
    """Yjs 文档的数据库持久化"""

    @classmethod
    async def load_state(cls, db: AsyncSession, mindmap_id: int) -> bytes | None:
        """从数据库加载 Yjs 文档状态"""
        result = (await db.execute(
            select(MindmapWsState.yjs_state)
            .where(MindmapWsState.mindmap_id == mindmap_id)
        )).scalar_one_or_none()
        return result

    @classmethod
    async def save_state(cls, db: AsyncSession, mindmap_id: int, state: bytes):
        """保存 Yjs 文档状态到数据库（upsert）"""
        existing = (await db.execute(
            select(MindmapWsState).where(MindmapWsState.mindmap_id == mindmap_id)
        )).scalar_one_or_none()

        if existing:
            await db.execute(
                update(MindmapWsState)
                .where(MindmapWsState.mindmap_id == mindmap_id)
                .values(yjs_state=state)
            )
        else:
            db.add(MindmapWsState(mindmap_id=mindmap_id, yjs_state=state))
        await db.commit()
```

- [ ] **Step 4: 提交**

```bash
git add ruoyi-fastapi-backend/module_mindmap/websocket/ ruoyi-fastapi-backend/module_mindmap/entity/do/mindmap_ws_state_do.py
git commit -m "feat(mindmap): add WebSocket room manager, Yjs doc persistence and WS state ORM"
```

---

## Task 2: WebSocket 端点

**Files:**
- Create: `ruoyi-fastapi-backend/module_mindmap/websocket/mindmap_ws.py`

- [ ] **Step 1: 实现 WebSocket 端点（连接后认证）**

```python
"""脑图 WebSocket 端点"""
import asyncio
import base64
from fastapi import WebSocket, WebSocketDisconnect
from utils.log_util import logger

from module_mindmap.websocket.room_manager import room_manager
from module_mindmap.websocket.yjs_doc import YjsDocManager
from config.get_db import AsyncSessionLocal

# 认证超时：连接后 10 秒内必须发送 auth 消息
AUTH_TIMEOUT_SECONDS = 10
# Yjs 状态持久化间隔：每 30 秒最多持久化一次
PERSIST_INTERVAL_SECONDS = 30


async def mindmap_websocket_endpoint(websocket: WebSocket, mindmap_id: int):
    """脑图实时协作 WebSocket 端点"""
    await websocket.accept()

    # ── 连接后认证（不通过 URL 传递 token） ──
    try:
        auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_SECONDS)
        if auth_msg.get('type') != 'auth' or not auth_msg.get('token'):
            await websocket.send_json({'type': 'auth_error', 'message': '请发送认证消息'})
            await websocket.close(code=4001)
            return

        from module_admin.service.login_service import LoginService
        current_user = await LoginService.validate_token_for_ws(auth_msg['token'])
    except asyncio.TimeoutError:
        await websocket.send_json({'type': 'auth_error', 'message': '认证超时'})
        await websocket.close(code=4001)
        return
    except Exception as e:
        await websocket.send_json({'type': 'auth_error', 'message': str(e)})
        await websocket.close(code=4001)
        return

    user_info = {
        'id': current_user.user.user_id,
        'name': current_user.user.nick_name,
        'avatar': current_user.user.avatar or '',
    }

    # 认证通过
    await websocket.send_json({'type': 'auth_ok', 'user': user_info})
    await room_manager.join(mindmap_id, websocket, user_info)

    # 通知其他人
    await room_manager.broadcast(mindmap_id, {
        'type': 'user_joined', 'user': user_info,
    }, exclude=websocket)

    # 发送当前房间用户列表
    users = room_manager.get_room_users(mindmap_id)
    await websocket.send_json({'type': 'room_users', 'users': users})

    # 加载持久化的 Yjs 状态
    try:
        async with AsyncSessionLocal() as db:
            state = await YjsDocManager.load_state(db, mindmap_id)
            if state:
                await websocket.send_json({
                    'type': 'sync_init',
                    'state': base64.b64encode(state).decode(),
                })
    except Exception as e:
        logger.error(f'加载 Yjs 状态失败: {e}')

    # ── 消息循环 ──
    last_persist_time = 0
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type')

            if msg_type in ('sync_step1', 'sync_step2', 'update'):
                await room_manager.broadcast(mindmap_id, {
                    'type': msg_type,
                    'update': data.get('update'),
                    'origin': str(user_info['id']),
                }, exclude=websocket)

                # 节流持久化：每 30 秒最多一次
                import time
                now = time.monotonic()
                if msg_type == 'update' and (now - last_persist_time) >= PERSIST_INTERVAL_SECONDS:
                    last_persist_time = now
                    try:
                        state_b64 = data.get('state', '')
                        if state_b64:
                            state_bytes = base64.b64decode(state_b64)
                            async with AsyncSessionLocal() as db:
                                await YjsDocManager.save_state(db, mindmap_id, state_bytes)
                    except Exception as e:
                        logger.error(f'持久化 Yjs 状态失败: {e}')

            elif msg_type == 'awareness':
                await room_manager.broadcast(mindmap_id, {
                    'type': 'awareness',
                    'update': data.get('update'),
                    'userId': user_info['id'],
                }, exclude=websocket)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f'WebSocket 错误: {e}')
    finally:
        await room_manager.leave(mindmap_id, websocket)
        await room_manager.broadcast(mindmap_id, {
            'type': 'user_left', 'userId': user_info['id'],
        })
```

- [ ] **Step 2: 注册 WebSocket 路由**

在 `server.py` 中 `create_app()` 函数内添加：

```python
from module_mindmap.websocket.mindmap_ws import mindmap_websocket_endpoint
app.websocket('/ws/mindmap/{mindmap_id}')(mindmap_websocket_endpoint)
```

- [ ] **Step 3: 提交**

```bash
git add ruoyi-fastapi-backend/module_mindmap/websocket/mindmap_ws.py
git commit -m "feat(mindmap): add WebSocket endpoint with post-connect auth and throttled persistence"
```

---

## Task 3: 前端 WebSocket 客户端 + Yjs 集成

**Files:**
- Create: `ruoyi-fastapi-frontend/src/utils/ws-client.js`
- Create: `ruoyi-fastapi-frontend/src/utils/yjs-sync.js`

- [ ] **Step 1: WebSocket 客户端封装（连接后发送 auth 消息）**

```javascript
// src/utils/ws-client.js
import { getToken } from '@/utils/auth'

export class MindmapWsClient {
  constructor(mindmapId, handlers) {
    this.mindmapId = mindmapId
    this.handlers = handlers || {}
    this.ws = null
    this.reconnectTimer = null
    this.reconnectAttempts = 0
    this.maxReconnectAttempts = 5
    this.isAuthenticated = false
  }

  connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/mindmap/${this.mindmapId}`

    this.ws = new WebSocket(wsUrl)

    this.ws.onopen = () => {
      // 连接建立后发送认证消息（token 不在 URL 中）
      const token = getToken()
      this.ws.send(JSON.stringify({ type: 'auth', token }))
    }

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'auth_ok') {
          this.isAuthenticated = true
          this.reconnectAttempts = 0
          this.handlers.onAuthenticated?.(data.user)
        } else if (data.type === 'auth_error') {
          this.handlers.onAuthError?.(data.message)
          this.ws.close()
        } else if (this.isAuthenticated) {
          this.handlers[data.type]?.(data)
        }
      } catch (e) {
        console.error('WS message parse error:', e)
      }
    }

    this.ws.onclose = () => {
      this.isAuthenticated = false
      this.handlers.onClose?.()
      this._scheduleReconnect()
    }

    this.ws.onerror = (error) => {
      console.error('WS error:', error)
      this.handlers.onError?.(error)
    }
  }

  send(data) {
    if (this.ws?.readyState === WebSocket.OPEN && this.isAuthenticated) {
      this.ws.send(JSON.stringify(data))
    }
  }

  disconnect() {
    clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
    this.isAuthenticated = false
  }

  _scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++
      this.connect()
    }, delay)
  }
}
```

- [ ] **Step 2: Yjs 同步逻辑（细粒度数据模型）**

```javascript
// src/utils/yjs-sync.js
import * as Y from 'yjs'
import { MindmapWsClient } from '@/utils/ws-client'

/**
 * Yjs 脑图同步管理器
 *
 * 数据模型（细粒度，非整体替换）：
 *   Y.Doc
 *   ├── Y.Map('meta')           → { layout, theme: Y.Map, viewData: Y.Map }
 *   └── Y.Map('nodes')          → { [nodeId]: Y.Map({ data: Y.Map, children: Y.Array<string>, parent: string }) }
 *
 * 优势：修改单个节点只触发该节点的变更，CRDT 自动合并不同节点的并发编辑。
 */
export class YjsMindmapSync {
  constructor(mindmapId, mindMapInstance) {
    this.mindmapId = mindmapId
    this.mindMap = mindMapInstance
    this.doc = new Y.Doc()
    this.collaborators = ref([])
    this.isSynced = ref(false)
    this._applyingRemote = false // 防止远程更新触发本地变更事件

    this.yMeta = this.doc.getMap('meta')
    this.yNodes = this.doc.getMap('nodes')

    this.wsClient = new MindmapWsClient(mindmapId, {
      onAuthenticated: (user) => { this.isSynced.value = true },
      onClose: () => { this.isSynced.value = false },
      sync_init: (data) => this._handleSyncInit(data),
      update: (data) => this._handleUpdate(data),
      user_joined: (data) => this._handleUserJoined(data),
      user_left: (data) => this._handleUserLeft(data),
      room_users: (data) => this._handleRoomUsers(data),
    })
  }

  start() {
    // 监听 Yjs 文档变更，转发到 WebSocket
    this.doc.on('update', (update, origin) => {
      if (origin !== 'remote') {
        this.wsClient.send({
          type: 'update',
          update: this._encodeUpdate(update),
          state: this._encodeUpdate(Y.encodeStateAsUpdate(this.doc)),
        })
      }
    })

    // 监听节点变更，同步到脑图实例
    this.yNodes.observeDeep(() => {
      if (!this._applyingRemote) {
        this._applyYjsToMindmap()
      }
    })

    this.wsClient.connect()
  }

  destroy() {
    this.wsClient.disconnect()
    this.doc.destroy()
  }

  /** 将脑图的完整节点树写入 Yjs（初始化或加载远程数据后调用） */
  initFromMindmap(nodeTree) {
    this.doc.transact(() => {
      this._flattenTreeToYjs(nodeTree, null)
    })
  }

  /** 将 simple-mind-map 的树形结构扁平化写入 Y.Map('nodes') */
  _flattenTreeToYjs(node, parentId, index = 0) {
    const nodeId = node.data?.uuid || node.data?.id || `node_${index}`
    const yNode = new Y.Map()
    yNode.set('data', new Y.Map(Object.entries(node.data || {})))
    yNode.set('children', new Y.Array())
    yNode.set('parent', parentId || '')
    this.yNodes.set(nodeId, yNode)

    if (node.children?.length) {
      const childIds = node.children.map((child, i) => {
        const childId = this._flattenTreeToYjs(child, nodeId, i)
        return childId
      })
      yNode.get('children').push(childIds)
    }

    return nodeId
  }

  /** 从 Yjs 扁平节点重建 simple-mind-map 树形结构 */
  _rebuildTreeFromYjs() {
    const nodes = {}
    this.yNodes.forEach((yNode, nodeId) => {
      nodes[nodeId] = {
        data: Object.fromEntries(yNode.get('data')?.entries() || []),
        children: [],
        _parentId: yNode.get('parent') || '',
        _childIds: yNode.get('children')?.toArray() || [],
      }
    })

    // 构建树
    const rootId = Object.keys(nodes).find(id => !nodes[id]._parentId)
    if (!rootId || !nodes[rootId]) return null

    function buildTree(id) {
      const node = nodes[id]
      if (!node) return null
      return {
        data: node.data,
        children: node._childIds.map(buildTree).filter(Boolean),
      }
    }

    return buildTree(rootId)
  }

  _applyYjsToMindmap() {
    if (!this.mindMap) return
    this._applyingRemote = true
    try {
      const tree = this._rebuildTreeFromYjs()
      if (tree) {
        this.mindMap.setData(tree)
      }
    } finally {
      this._applyingRemote = false
    }
  }

  _handleSyncInit(data) {
    const state = this._decodeUpdate(data.state)
    Y.applyUpdate(this.doc, state, 'remote')
  }

  _handleUpdate(data) {
    const update = this._decodeUpdate(data.update)
    Y.applyUpdate(this.doc, update, 'remote')
  }

  _handleUserJoined(data) {
    this.collaborators.value = [...this.collaborators.value, data.user]
  }

  _handleUserLeft(data) {
    this.collaborators.value = this.collaborators.value.filter(u => u.id !== data.userId)
  }

  _handleRoomUsers(data) {
    this.collaborators.value = data.users
  }

  _encodeUpdate(uint8Array) {
    return btoa(String.fromCharCode(...uint8Array))
  }

  _decodeUpdate(base64Str) {
    return Uint8Array.from(atob(base64Str), c => c.charCodeAt(0))
  }
}
```

- [ ] **Step 3: 在 Edit.vue 中集成**

在 Edit.vue 的 `initMindMap` 中，创建 MindMap 实例后启动 Yjs 同步：

```javascript
import { YjsMindmapSync } from '@/utils/yjs-sync'

let yjsSync = null

// 在 MindMap 创建成功后（非只读模式）
if (props.mindmapId && !props.readonly) {
  yjsSync = new YjsMindmapSync(props.mindmapId, mm)
  yjsSync.start()
  yjsSync.initFromMindmap(root) // 将当前数据写入 Yjs
}

// 在 onBeforeUnmount 中
if (yjsSync) {
  yjsSync.destroy()
  yjsSync = null
}
```

- [ ] **Step 4: 提交**

```bash
git add ruoyi-fastapi-frontend/src/utils/ws-client.js ruoyi-fastapi-frontend/src/utils/yjs-sync.js ruoyi-fastapi-frontend/src/components/MindMap/Edit.vue
git commit -m "feat(mindmap): integrate Yjs CRDT with fine-grained node model for real-time collaboration"
```

---

## Task 4: 协作者 UI

**Files:**
- Create: `ruoyi-fastapi-frontend/src/components/MindMap/Collaborators.vue`

- [ ] **Step 1: 创建协作者头像列表组件**

```vue
<template>
  <div class="collaborators" v-if="collaborators.length > 0">
    <el-tooltip
      v-for="user in displayUsers"
      :key="user.id"
      :content="user.name"
      placement="bottom"
    >
      <el-avatar :size="32" :src="user.avatar || undefined">
        {{ user.name?.charAt(0) || '?' }}
      </el-avatar>
    </el-tooltip>
    <el-tooltip v-if="extraCount > 0" :content="`${extraCount} 人`" placement="bottom">
      <el-avatar :size="32" class="extra-count">+{{ extraCount }}</el-avatar>
    </el-tooltip>
  </div>
</template>

<script setup>
const props = defineProps({
  collaborators: { type: Array, default: () => [] },
  maxDisplay: { type: Number, default: 5 }
})

const displayUsers = computed(() => props.collaborators.slice(0, props.maxDisplay))
const extraCount = computed(() => Math.max(0, props.collaborators.length - props.maxDisplay))
</script>

<style scoped>
.collaborators {
  display: flex;
  align-items: center;
}
.collaborators .el-avatar {
  border: 2px solid #fff;
  margin-left: -8px;
}
.collaborators .el-avatar:first-child {
  margin-left: 0;
}
.extra-count {
  background: #e8e8e8;
  color: #666;
  font-size: 12px;
}
</style>
```

- [ ] **Step 2: 在编辑器页面中引入**

在 `views/mindmap/edit.vue` 的 header 区域添加协作者列表。

- [ ] **Step 3: 提交**

```bash
git add ruoyi-fastapi-frontend/src/components/MindMap/Collaborators.vue
git commit -m "feat(mindmap): add collaborators avatar list component"
```

---

# Phase 3: 版本历史（智能版本）

> **注意：** 以下 Phase 3-5 为结构化大纲。每个阶段开始前，会参照 Phase 1 的详细程度编写独立的 step-by-step 实施计划。

## 技术方案

- **草稿版本**：自动保存时创建，保留最近 **10 个**（减少存储开销）
- **正式版本**：用户手动 Ctrl+S 时创建，永久保留
- **版本数据结构**：快照式存储（存完整 node_tree）
- **存储估算**：10 个草稿 × 平均 200KB = 2MB/脑图，可接受

## 新增数据库表

```sql
CREATE TABLE mindmap_version (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL COMMENT '脑图ID',
    version_number INT NOT NULL COMMENT '版本号',
    version_type SMALLINT NOT NULL DEFAULT 0 COMMENT '版本类型: 0=草稿 1=正式',
    name VARCHAR(200) COMMENT '版本名称（仅正式版本）',
    node_tree LONGTEXT NOT NULL COMMENT '节点树快照JSON',
    view_data JSON COMMENT '视图状态快照',
    layout VARCHAR(50) COMMENT '布局类型',
    theme JSON COMMENT '主题配置',
    created_by VARCHAR(64) NOT NULL COMMENT '创建者',
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_version_mindmap (mindmap_id, version_type),
    INDEX idx_version_time (mindmap_id, created_time DESC)
) COMMENT '脑图版本历史表';
```

## 新增文件

### 后端
- `module_mindmap/entity/do/mindmap_version_do.py` — 版本 ORM 模型
- `module_mindmap/entity/vo/mindmap_version_vo.py` — 版本 Pydantic 模型
- `module_mindmap/dao/mindmap_version_dao.py` — 版本 DAO
- `module_mindmap/service/mindmap_version_service.py` — 版本 Service

### 前端
- `src/components/MindMap/VersionHistory.vue` — 版本历史侧边栏
- `src/api/mindmap/version.js` — 版本 API

## API 设计

| Method | Path | Description |
|--------|------|-------------|
| GET | `/mindmap/version/list/{mindmap_id}` | 获取版本列表（分页，按类型筛选） |
| GET | `/mindmap/version/{version_id}` | 获取版本详情（完整 node_tree） |
| POST | `/mindmap/version/restore/{version_id}` | 回滚到指定版本 |
| POST | `/mindmap/version/save` | 手动创建正式版本 |
| DELETE | `/mindmap/version/{version_id}` | 删除指定版本（仅正式版本可删） |

## Task 1: 版本数据模型与 DAO

**Files:**
- Create: `module_mindmap/entity/do/mindmap_version_do.py`
- Create: `module_mindmap/dao/mindmap_version_dao.py`

- [ ] **Step 1: 创建 ORM 模型和 DAO**

参照 Task 1 中 `mindmap_do.py` 和 `mindmap_dao.py` 的模式。DAO 需包含：
- `add_version()` — 插入版本记录
- `get_version_list()` — 分页查询，支持 `version_type` 筛选
- `get_version_by_id()` — 单条查询
- `delete_old_drafts()` — 删除超过 10 个的旧草稿版本
- `delete_version()` — 删除指定版本

- [ ] **Step 2: 提交**

```bash
git add module_mindmap/entity/do/mindmap_version_do.py module_mindmap/dao/mindmap_version_dao.py
git commit -m "feat(mindmap): add version history ORM model and DAO"
```

---

## Task 2: 版本 Service 与 Controller

**Files:**
- Create: `module_mindmap/service/mindmap_version_service.py`
- Modify: `module_mindmap/controller/mindmap_controller.py` — 添加版本端点

- [ ] **Step 1: 实现 Service 层**

核心方法：
- `create_draft_version()` — 创建草稿版本，自动清理超出 10 个的旧草稿
- `create_formal_version()` — 创建正式版本，递增主表 version_count
- `get_version_list()` — 分页查询版本列表（不含 node_tree 大字段）
- `get_version_detail()` — 查询单个版本完整数据
- `restore_version()` — 回滚到指定版本（将版本的 node_tree 写回主表 + 创建新的正式版本记录）
- `delete_version()` — 仅允许删除正式版本

- [ ] **Step 2: 添加 Controller 端点**

在 `mindmap_controller.py` 中添加 5 个版本相关端点，均需要所有权校验。

- [ ] **Step 3: 修改自动保存流程**

在 `update_content_services` 中，每次保存成功后自动调用 `create_draft_version()`。在 `manualSave`（Ctrl+S）时调用 `create_formal_version()`。

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(mindmap): add version history service and controller endpoints"
```

---

## Task 3: 前端版本历史 UI

**Files:**
- Create: `src/components/MindMap/VersionHistory.vue`
- Create: `src/api/mindmap/version.js`

- [ ] **Step 1: 创建版本 API**

```javascript
import request from '@/utils/request'

export function listVersions(mindmapId, query) {
  return request({ url: `/mindmap/version/list/${mindmapId}`, method: 'get', params: query })
}

export function getVersionDetail(versionId) {
  return request({ url: `/mindmap/version/${versionId}`, method: 'get' })
}

export function restoreVersion(versionId) {
  return request({ url: `/mindmap/version/restore/${versionId}`, method: 'post' })
}

export function saveFormalVersion(data) {
  return request({ url: '/mindmap/version/save', method: 'post', data })
}

export function deleteVersion(versionId) {
  return request({ url: `/mindmap/version/${versionId}`, method: 'delete' })
}
```

- [ ] **Step 2: 创建版本历史侧边栏组件**

功能：
- 分 Tab 显示"正式版本"和"草稿版本"
- 每个版本显示时间、创建者、版本号
- 点击"查看"可预览该版本（只读模式加载）
- 点击"恢复"回滚到该版本（需确认对话框）
- "保存正式版本"按钮（调用 Ctrl+S 逻辑）

- [ ] **Step 3: 集成到编辑器**

在 `SidebarTrigger` 中添加"版本历史"入口，在 `Sidebar` 中加载 `VersionHistory` 组件。

- [ ] **Step 4: 提交**

```bash
git commit -m "feat(mindmap): add version history sidebar with draft/formal versions"
```

---

# Phase 4: 分享与协作权限

## 技术方案

- **分享链接**：生成唯一 token 的 URL，支持设置过期时间和权限级别
- **协作者管理**：脑图所有者可以添加/移除协作者，设置读/写权限
- **权限模型**：Phase 4 先实现简单模型（查看/编辑），后续升级到精细权限

## 新增数据库表

```sql
-- 分享链接表
CREATE TABLE mindmap_share (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL,
    share_token VARCHAR(64) NOT NULL UNIQUE COMMENT '分享token（uuid4）',
    share_type SMALLINT NOT NULL DEFAULT 0 COMMENT '0=查看 1=编辑',
    expire_time DATETIME COMMENT '过期时间（NULL=永久）',
    created_by BIGINT NOT NULL,
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active SMALLINT NOT NULL DEFAULT 1,
    INDEX idx_share_token (share_token),
    INDEX idx_share_mindmap (mindmap_id)
) COMMENT '脑图分享链接表';

-- 协作者表
CREATE TABLE mindmap_collaborator (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL COMMENT '协作用户ID',
    permission SMALLINT NOT NULL DEFAULT 0 COMMENT '0=查看 1=编辑',
    created_by BIGINT NOT NULL,
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_collab_unique (mindmap_id, user_id),
    INDEX idx_collab_user (user_id)
) COMMENT '脑图协作者表';
```

## 新增文件

### 后端
- `module_mindmap/entity/do/mindmap_share_do.py`
- `module_mindmap/entity/do/mindmap_collaborator_do.py`
- `module_mindmap/controller/mindmap_share_controller.py`
- `module_mindmap/service/mindmap_share_service.py`
- `module_mindmap/dao/mindmap_share_dao.py`

### 前端
- `src/components/MindMap/ShareDialog.vue` — 分享对话框
- `src/components/MindMap/CollaboratorManager.vue` — 协作者管理
- `src/api/mindmap/share.js`

## API 设计

| Method | Path | Description |
|--------|------|-------------|
| POST | `/mindmap/share/link` | 生成分享链接 |
| GET | `/mindmap/share/link/{mindmap_id}` | 获取当前分享链接列表 |
| DELETE | `/mindmap/share/link/{share_id}` | 删除/禁用分享链接 |
| GET | `/mindmap/share/view/{share_token}` | 通过分享链接查看脑图（**公开接口**，无需登录） |
| POST | `/mindmap/collaborator` | 添加协作者 |
| GET | `/mindmap/collaborator/list/{mindmap_id}` | 获取协作者列表 |
| PUT | `/mindmap/collaborator` | 修改协作者权限 |
| DELETE | `/mindmap/collaborator/{id}` | 移除协作者 |

## Task 1: 分享链接功能

- [ ] **Step 1: 创建数据模型和 DAO**
- [ ] **Step 2: 实现 Service 和 Controller**（公开查看接口使用 `PreAuthDependency(exclude_routes=[...])` 跳过认证）
- [ ] **Step 3: 前端分享对话框 UI**
- [ ] **Step 4: 公开查看页面**（新增 `/mindmap/view/:share_token` 路由，只读模式）

---

## Task 2: 协作者管理

- [ ] **Step 1: 创建协作者数据模型和 DAO**
- [ ] **Step 2: 实现协作者 CRUD Service 和 Controller**
- [ ] **Step 3: 前端协作者管理 UI**（在编辑器侧边栏中添加）
- [ ] **Step 4: 权限校验集成** — 修改 `get_mindmap_detail_services` 和 `update_content_services`，在所有权校验之后增加协作者权限检查：`owner_id == user_id` OR `mindmap_collaborator 中存在该用户且权限匹配`

---

# Phase 5: 模板市场

## 技术方案

- **Phase 5 初版**：管理员发布官方模板，用户使用模板创建脑图
- **数据复用**：复用 `mindmap` 表的 `is_template` 字段
- **新增模板分类**：独立的模板分类表

## 新增数据库表

```sql
CREATE TABLE mindmap_template_category (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL COMMENT '分类名称',
    sort_order INT DEFAULT 0,
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP
) COMMENT '脑图模板分类表';

-- mindmap 表新增 category_id 字段
ALTER TABLE mindmap ADD COLUMN template_category_id BIGINT DEFAULT NULL COMMENT '模板分类ID';
```

## 新增文件

### 后端
- `module_mindmap/controller/mindmap_template_controller.py` — 模板管理 Controller
- `module_mindmap/service/mindmap_template_service.py`
- `module_mindmap/dao/mindmap_template_dao.py`

### 前端
- `src/views/mindmap/templates.vue` — 模板市场页面
- `src/api/mindmap/template.js`

## API 设计

| Method | Path | Description |
|--------|------|-------------|
| GET | `/mindmap/template/list` | 获取模板列表（公开） |
| GET | `/mindmap/template/categories` | 获取模板分类 |
| GET | `/mindmap/template/{id}` | 获取模板详情 |
| POST | `/mindmap/template/use/{id}` | 使用模板创建脑图（复制为新脑图） |
| POST | `/mindmap/template` | 管理员发布模板（需 `mindmap:template:add` 权限） |
| PUT | `/mindmap/template` | 管理员编辑模板（需 `mindmap:template:edit` 权限） |
| DELETE | `/mindmap/template/{id}` | 管理员删除模板（需 `mindmap:template:remove` 权限） |

## Task 1: 模板管理后端

- [ ] **Step 1: 创建模板分类表和 ORM 模型**
- [ ] **Step 2: 实现模板 CRUD Service 和 Controller**（模板查询接口 `is_template=1`）
- [ ] **Step 3: "使用模板"功能** — 调用 `copy_mindmap_services`，将模板脑图复制为用户的新脑图，修改 `owner_id` 为当前用户

---

## Task 2: 模板市场前端

- [ ] **Step 1: 创建模板市场页面** — 卡片式布局，分类筛选，搜索
- [ ] **Step 2: 模板预览功能** — 只读模式打开脑图（复用 edit.vue 的 readonly 模式）
- [ ] **Step 3: "使用模板"按钮** → 调用 API 创建新脑图并跳转编辑器
- [ ] **Step 4: 管理后台模板管理页面** — 标准 CRUD 列表（参照 post/index.vue 模式）

---

# 附录

## 权限字符串对照表

| 权限字符串 | 说明 |
|-----------|------|
| `mindmap:mindmap:list` | 查看脑图列表 |
| `mindmap:mindmap:query` | 查看脑图详情 |
| `mindmap:mindmap:add` | 新增脑图 |
| `mindmap:mindmap:edit` | 编辑脑图 |
| `mindmap:mindmap:remove` | 删除脑图 |
| `mindmap:template:list` | 查看模板列表（公开） |
| `mindmap:template:add` | 发布模板（管理员） |
| `mindmap:template:edit` | 编辑模板（管理员） |
| `mindmap:template:remove` | 删除模板（管理员） |

## 前端路由规划

| 路径 | 组件 | 说明 |
|------|------|------|
| `/mindmap/index` | `views/mindmap/index.vue` | 脑图管理列表 |
| `/mindmap/edit?id=X` | `views/mindmap/edit.vue` | 脑图编辑器（编辑模式） |
| `/mindmap/edit?id=X&readonly=1` | `views/mindmap/edit.vue` | 脑图查看器（只读模式） |
| `/mindmap/templates` | `views/mindmap/templates.vue` | 模板市场（Phase 5） |
| `/mindmap/view/:token` | `views/mindmap/view.vue` | 公开查看页（Phase 4） |

## 安全与性能约束

| 约束 | 措施 |
|------|------|
| 脑图大小限制 | `MindmapModel.node_tree` JSON 序列化后不超过 **5MB**，在 Service 层校验 |
| 自动保存频率 | 前端 5 秒防抖 + 后端 `@ApiRateLimit`（每用户每秒最多 2 次） |
| WebSocket 认证 | 连接后发送 auth 消息（token 不在 URL 中），10 秒超时 |
| 所有权校验 | 所有写操作（edit/delete/rename/content）均校验 `owner_id == user_id` |
| 草稿版本上限 | 每个脑图最多 10 个草稿版本，超出自动清理 |
| 菜单 ID 范围 | 使用 9000+ 避免与现有菜单冲突 |
