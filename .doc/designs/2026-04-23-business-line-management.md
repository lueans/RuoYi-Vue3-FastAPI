# 业务线管理功能设计文档

## Context

用户需要在「测试管理」模块下新增「业务线管理」功能，支持树形层级结构（父子业务线），每个业务线有业务标识、负责人等属性。设计完全遵循现有项目架构模式，以 `sys_dept`（部门管理）为参考蓝本。

---

## 1. 数据库设计

### 表结构：`test_business_line`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `line_id` | bigint(20) | PK, AUTO_INCREMENT | 业务线ID |
| `parent_id` | bigint(20) | DEFAULT 0 | 父业务线ID |
| `ancestors` | varchar(50) | DEFAULT '' | 祖级列表（如 `0,100,101`） |
| `line_code` | varchar(50) | UNIQUE, NOT NULL | 业务线编码（业务标识） |
| `line_name` | varchar(30) | DEFAULT '' | 业务线名称 |
| `order_num` | int(4) | DEFAULT 0 | 显示顺序 |
| `leader` | varchar(20) | NULL | 负责人 |
| `phone` | varchar(11) | NULL | 联系电话 |
| `email` | varchar(50) | NULL | 邮箱 |
| `status` | char(1) | DEFAULT '0' | 状态（0正常 1停用） |
| `del_flag` | char(1) | DEFAULT '0' | 删除标志（0存在 2删除） |
| `create_by` | varchar(64) | DEFAULT '' | 创建者 |
| `create_time` | datetime | | 创建时间 |
| `update_by` | varchar(64) | DEFAULT '' | 更新者 |
| `update_time` | datetime | | 更新时间 |
| `remark` | varchar(500) | DEFAULT '' | 备注 |

树形结构方案：`parent_id`（邻接表）+ `ancestors`（物化路径），与 `sys_dept` 一致。

### 种子数据

```
100 - 全部业务线 (ROOT, parent_id=0, ancestors='0')
├── 101 - 业务线A (BL001, parent_id=100, ancestors='0,100')
└── 102 - 业务线B (BL002, parent_id=100, ancestors='0,100')
```

### 菜单数据（sys_menu）

| menu_id | menu_name | parent_id | type | perms | component |
|---------|-----------|-----------|------|-------|-----------|
| 2000 | 测试管理 | 0 | M | - | null |
| 2001 | 业务线管理 | 2000 | C | test:businessLine:list | test/businessLine/index |
| 2002 | 业务线查询 | 2001 | F | test:businessLine:query | - |
| 2003 | 业务线新增 | 2001 | F | test:businessLine:add | - |
| 2004 | 业务线修改 | 2001 | F | test:businessLine:edit | - |
| 2005 | 业务线删除 | 2001 | F | test:businessLine:remove | - |

---

## 2. 后端设计

### 目录结构（新建 `module_test/`）

```
ruoyi-fastapi-backend/module_test/
├── controller/
│   └── business_line_controller.py
├── dao/
│   └── business_line_dao.py
├── entity/
│   ├── do/
│   │   └── business_line_do.py
│   └── vo/
│       └── business_line_vo.py
└── service/
    └── business_line_service.py
```

无需 `__init__.py`，路由自动发现机制（`common/router.py`）会自动扫描注册。

### DO 模型（`business_line_do.py`）

参照：`module_admin/entity/do/dept_do.py`

`TestBusinessLine(Base)` — 映射 `test_business_line` 表全部字段。

### VO 模型（`business_line_vo.py`）

参照：`module_admin/entity/vo/dept_vo.py`

| 类名 | 用途 |
|------|------|
| `BusinessLineModel` | 基础模型，含全部字段 + `@NotBlank`/`@Size` 校验 |
| `BusinessLineQueryModel` | 继承基础模型，增加 `begin_time`/`end_time` |
| `BusinessLineTreeModel` | 树节点模型（id, label, parent_id, children 递归引用） |
| `DeleteBusinessLineModel` | 删除模型（line_ids 逗号分隔） |

### DAO（`business_line_dao.py`）

参照：`module_admin/dao/dept_dao.py`

`BusinessLineDao` 类，关键方法：

| 方法 | 说明 |
|------|------|
| `get_business_line_by_id` | 按 ID 查询 |
| `get_business_line_detail_by_id` | 按 ID 查询（排除已删除） |
| `get_business_line_detail_by_info` | 按 parent_id + name 查重 |
| `get_business_line_detail_by_code` | 按 line_code 查重 |
| `get_business_line_info_for_edit_option` | 编辑时排除自身及后代 |
| `get_children_business_line_dao` | 通过 `func.find_in_set` 查询全部后代 |
| `get_business_line_list_for_tree` | 获取树列表 |
| `get_business_line_list` | 获取列表（支持多条件过滤） |
| `add_business_line_dao` | 新增 |
| `edit_business_line_dao` | 修改 |
| `update_business_line_children_dao` | 批量更新子节点 ancestors |
| `delete_business_line_dao` | 软删除 |
| `count_normal_children_dao` | 统计正常子节点数 |
| `count_children_dao` | 统计直接子节点数 |

### Service（`business_line_service.py`）

参照：`module_admin/service/dept_service.py`

`BusinessLineService` 类，关键方法：

| 方法 | 说明 |
|------|------|
| `get_business_line_list_services` | 获取列表 |
| `get_business_line_tree_services` | 获取树形数据 |
| `get_business_line_for_edit_option_services` | 获取编辑选项（排除自身子树） |
| `business_line_detail_services` | 获取详情 |
| `add_business_line_services` | 新增（名称+编码唯一性校验，计算 ancestors） |
| `edit_business_line_services` | 修改（级联更新后代 ancestors） |
| `delete_business_line_services` | 删除（有子节点时禁止删除） |
| `list_to_tree` | 扁平列表转树形结构 |

### Controller（`business_line_controller.py`）

参照：`module_admin/controller/dept_controller.py`

`APIRouterPro(prefix='/test/businessLine', tags=['测试管理-业务线管理'])`

| 方法 | 路径 | 权限 |
|------|------|------|
| GET | `/list` | `test:businessLine:list` |
| GET | `/list/exclude/{line_id}` | `test:businessLine:list` |
| GET | `/{line_id}` | `test:businessLine:query` |
| POST | `/` | `test:businessLine:add` |
| PUT | `/` | `test:businessLine:edit` |
| DELETE | `/{line_ids}` | `test:businessLine:remove` |

---

## 3. 前端设计

### API 文件：`src/api/test/businessLine.js`

参照：`src/api/system/dept.js`

6 个函数：`listBusinessLine`, `listBusinessLineExcludeChild`, `getBusinessLine`, `addBusinessLine`, `updateBusinessLine`, `delBusinessLine`

### 页面：`src/views/test/businessLine/index.vue`

参照：`src/views/system/dept/index.vue`

**页面布局：**

1. **搜索栏** — 业务线名称 / 业务线编码 / 状态下拉
2. **工具栏** — 新增按钮 + 展开/折叠按钮
3. **树形表格**（`el-table` + `row-key="lineId"` + `tree-props`）
   - 列：业务线名称 / 编码 / 负责人 / 排序 / 状态 / 创建时间 / 操作
   - 操作：修改 / 新增子业务线 / 删除（根节点不可删）
4. **新增/编辑对话框**
   - 上级业务线（`el-tree-select`）
   - 业务线编码 / 名称 / 排序 / 负责人 / 电话 / 邮箱 / 状态 / 备注

---

## 4. 关键参照文件

| 用途 | 文件路径 |
|------|----------|
| DO 模板 | `module_admin/entity/do/dept_do.py` |
| VO 模板 | `module_admin/entity/vo/dept_vo.py` |
| DAO 模板 | `module_admin/dao/dept_dao.py` |
| Service 模板 | `module_admin/service/dept_service.py` |
| Controller 模板 | `module_admin/controller/dept_controller.py` |
| 前端 API 模板 | `src/api/system/dept.js` |
| 前端页面模板 | `src/views/system/dept/index.vue` |
| 树形工具函数 | `src/utils/ruoyi.js` (`handleTree`) |
| 路由自动注册 | `common/router.py` (`RouterRegister`) |

## 5. 实施顺序

1. 执行 SQL：建表 + 种子数据 + 菜单 + 角色授权
2. 创建后端 `module_test/` 目录结构
3. 依次创建：DO → VO → DAO → Service → Controller
4. 创建前端 API 文件 + Vue 页面
5. 重启后端，刷新前端验证

## 6. 验证方式

1. 重启后端，确认路由自动注册日志中包含 `/test/businessLine`
2. 刷新前端页面，确认左侧菜单出现「测试管理 → 业务线管理」
3. 功能测试：新增根业务线、新增子业务线、编辑（修改上级）、删除
4. 边界测试：重复编码校验、重复名称校验、有子节点禁止删除、根节点不可删除
