# 脑图管理功能设计文档

**日期**：2026-06-06
**状态**：已批准，待实施
**实施计划**：`docs/superpowers/plans/2026-06-06-mindmap-management.md`

---

## 一、需求摘要

在 RuoYi-Vue3-FastAPI 后台集成完整的脑图管理功能，分 5 个阶段交付。

### 需求决策矩阵

| 维度 | 决策 | 理由 |
|------|------|------|
| **功能范围** | 全套（管理 + 分享 + 版本 + 模板 + 协作） | 完整产品闭环 |
| **使用场景** | 多人团队协作编辑同一脑图 | 对标 Google Docs / Figma |
| **实时同步粒度** | 操作级同步（每次操作实时可见） | 最佳协作体验 |
| **技术方案** | Yjs (CRDT) | 天然支持树形结构 + 离线合并 + Awareness 协议 |
| **模板市场** | Phase 5 先官方模板，后扩展社区 | 降低初期运营复杂度 |
| **分享权限** | Phase 4 先链接分享 + 指定协作者，后升级精细权限 | 最小可行权限模型 |
| **版本历史** | 智能版本：自动保存=草稿（最近10个），手动保存=正式（永久） | 平衡存储与可用性 |
| **离线编辑** | 不支持，必须在线 | 简化架构，不需要 IndexedDB 缓存 |

### 阶段路线图

```
Phase 1 ──────────────────────────────→ 可用基线
  后端 API + 前端对接 + 脑图管理列表页
      │
      ├─→ Phase 2 ─→ 实时协作 (Yjs + WebSocket)
      ├─→ Phase 3 ─→ 版本历史
      ├─→ Phase 4 ─→ 分享与协作权限（依赖 Phase 2）
      └─→ Phase 5 ─→ 模板市场
```

---

## 二、simple-mind-map 数据结构深度分析

### 2.1 顶层导出格式 `getData(true)`

```javascript
{
  root: { /* 节点树（递归结构） */ },
  layout: "logicalStructure",          // 布局类型
  theme: {
    template: "default",               // 主题模板名
    config: { /* 主题覆盖配置 */ }
  },
  view: {
    transform: { scaleX, scaleY, translateX, translateY, origin: [0,0] },
    state: { scale, x, y, sx, sy }
  },
  smmVersion: "0.14.0-fix.2"
}
```

### 2.2 节点数据结构

每个节点是 `{ data: {...}, children: [...] }` 的递归结构，`data` 包含 **67 个可能的字段**：

| 类别 | 数量 | 字段举例 |
|------|------|---------|
| **身份标识** | 1 | `uid` (UUID v4) |
| **内容字段** | 20 | `text`, `image`, `icon`, `tag`, `hyperlink`, `note`, `richText`, `checkbox`, `attachmentUrl` 等 |
| **状态字段** | 5 | `expand`, `isActive`, `customLeft`, `customTop`, `dir` |
| **概要/总结** | 2 | `generalization`, `range` |
| **关联线（插件）** | 5 | `associativeLineTargets`, `associativeLinePoint`, `associativeLineText`, `associativeLineStyle` 等 |
| **外框（插件）** | 1 | `outerFrame` |
| **样式覆盖** | 33 | `shape`, `fillColor`, `color`, `fontSize`, `fontWeight`, `borderColor`, `lineWidth`, `paddingX` 等 |

**关键约束**：`constant.js` 中的 `nodeDataNoStylePropList` 定义了哪些字段**不是**样式，其余均视为样式覆盖。

### 2.3 节点大小基准

| 节点类型 | 使用字段数 | 单节点 JSON 大小 |
|---------|-----------|-----------------|
| 最小（纯文字） | 3 | **~79 字节** |
| 典型（文字+少量样式） | 7 | **~171 字节** |
| 富节点（文字+图片+标签+链接+备注+样式） | 46 | **~1,533 字节** |

### 2.4 整树大小基准

| 脑图规模 | 节点数 | JSON 大小 | 常见场景 |
|---------|--------|----------|---------|
| 小型 | 20 | **~3 KB** | 简单提纲 |
| 中型 | 100 | **~24 KB** | 日常思维导图 |
| 大型 | 500 | **~156 KB** | 复杂项目规划 |
| 超大型 | 2000 | **~776 KB** | 知识库全景图 |
| 极端 | 5000 | **~2.6 MB** | 几乎不会遇到 |

### 2.5 操作类型（Command 系统）

所有操作通过 Command 系统执行，触发两种事件：

- `data_change`：每次操作后触发，携带**完整树**
- `data_change_detail`：每次操作后触发，携带**增量变更列表**（当前未被使用）

```javascript
// data_change_detail 格式（增量事件，Phase 1.2 的关键桥梁）
mindMap.on('data_change_detail', (detailList) => {
  detailList.forEach(detail => {
    // detail.action: 'create' | 'update' | 'delete'
    // detail.data: 变更后的节点
    // detail.oldData: 变更前的节点（update/delete 时）
  })
})
```

主要操作类型：

| 操作 | 实际修改数据量 | 操作频率 |
|------|--------------|---------|
| `SET_NODE_TEXT` | ~10 字节（1 个字段） | 高 |
| `SET_NODE_STYLE` | ~20 字节（1 个字段） | 高 |
| `SET_NODE_EXPAND` | 1 个 boolean | 高 |
| `INSERT_CHILD_NODE` | ~200 字节（新节点） | 中 |
| `REMOVE_NODE` | 删除子树 | 中 |
| `UP_NODE / DOWN_NODE` | 数组顺序变更 | 中 |
| `MOVE_NODE_TO` | 修改 parent + children | 低 |

### 2.6 Undo/Redo 历史系统

```javascript
history: string[]           // JSON 快照数组
maxHistoryCount: 500        // 最多 500 个快照
addHistoryTime: 100         // 100ms 节流
```

**内存占用**：大型脑图 (156KB) × 500 快照 = **78MB 前端内存**。这是 simple-mind-map 库自身的设计，非我们引入。

---

## 三、后端存储设计

### 3.1 当前设计（保持）

```
┌─ mindmap 表 ──────────────────────────────┐
│  id, name, description, owner_id, layout   │
│  node_tree (LONGTEXT) ← 完整节点树 JSON    │
│  theme (JSON), view_data (JSON)            │
│  is_template, version_count, status        │
│  del_flag, create_by, create_time, ...     │
└────────────────────────────────────────────┘
```

**设计决策：保持现状，不做表结构重构。**

理由：
1. 中型脑图 (~24KB) 每次写入 < 5ms，不是性能瓶颈
2. LONGTEXT 支持 4GB，远超实际需求
3. 单次 `SELECT node_tree` 比查询 500 行节点表再建树更快
4. 引入节点行表会大幅增加 Phase 1 实施复杂度

### 3.2 Phase 1 增量传输优化（不改表结构）

利用 `data_change_detail` 事件，前端自动保存时只发送变更部分：

```
┌─ 前端 ──────────────────────────────────────────────┐
│                                                      │
│  data_change_detail 事件（增量）                       │
│    → 收集 5 秒内的增量操作                              │
│    → PUT /mindmap/content/incremental                │
│    → body: { operations: [{ action, uid, data }] }   │
│    → 网络传输: ~50-200 字节                            │
│                                                      │
│  Ctrl+S 手动保存（全量）                                │
│    → PUT /mindmap/content                            │
│    → body: { nodeTree, viewData, layout, theme }     │
│    → 网络传输: ~24KB (中型脑图)                         │
│                                                      │
└──────────────────────┬───────────────────────────────┘
                       │
                       ↓
┌─ 后端 ──────────────────────────────────────────────┐
│                                                      │
│  增量接口:                                            │
│    1. 加载当前 node_tree (JSON.loads)                 │
│    2. 在内存中应用增量变更 (find_node_by_uid + merge)  │
│    3. 写回 (JSON.dumps → UPDATE)                      │
│                                                      │
│  全量接口:                                            │
│    1. JSON.dumps(nodeTree)                            │
│    2. UPDATE mindmap SET node_tree = ...              │
│                                                      │
└──────────────────────────────────────────────────────┘
```

**效果**：

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 网络传输（自动保存） | ~24KB（中型脑图） | ~50-200 字节 |
| 数据库写入 | 不变（整体覆盖） | 不变 |
| 实现复杂度 | 低 | 中 |

### 3.3 Phase 2 新增表

```sql
CREATE TABLE mindmap_ws_state (
    id           BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id   BIGINT NOT NULL,
    yjs_state    MEDIUMBLOB COMMENT 'Yjs 文档二进制状态',
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE INDEX idx_ws_mindmap (mindmap_id)
) COMMENT '脑图 Yjs 文档持久化状态表';
```

协作时 `yjs_state` 成为主数据源，`node_tree` 降级为最后已知快照。

### 3.4 Phase 3 新增表

```sql
CREATE TABLE mindmap_version (
    id            BIGINT PRIMARY KEY AUTO_INCREMENT,
    mindmap_id    BIGINT NOT NULL,
    version_type  TINYINT NOT NULL DEFAULT 0 COMMENT '0=草稿 1=正式',
    node_tree     LONGTEXT NOT NULL COMMENT '节点树快照',
    theme         JSON,
    layout        VARCHAR(50),
    view_data     JSON,
    created_by    VARCHAR(64) NOT NULL,
    created_time  DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ver (mindmap_id, version_type, created_time DESC)
) COMMENT '脑图版本历史表';
```

| 版本类型 | 触发 | 保留策略 | 存储估算 |
|---------|------|---------|---------|
| 正式版本 | Ctrl+S | 永久 | 10个/月 × 24KB = 240KB/月 |
| 草稿版本 | 自动保存 | 最近 10 个 | 10 × 24KB = 240KB |

### 3.5 总表结构演进

| 阶段 | 表 | 数量 |
|------|-----|------|
| Phase 1 | `mindmap` | 1（现有） |
| Phase 2 | + `mindmap_ws_state` | +1 |
| Phase 3 | + `mindmap_version` | +1 |
| Phase 4 | + `mindmap_share` + `mindmap_collaborator` | +2 |
| Phase 5 | + `mindmap_template_category` | +1 |
| **总计** | | **6 张表** |

---

## 四、性能风险分析

### 4.1 已识别风险

| # | 风险 | 严重度 | 触发条件 | 缓解措施 |
|---|------|--------|---------|---------|
| 1 | 前端主线程阻塞 | ⚠️ 中 | 500+ 节点 + 自动保存 | `requestIdleCallback` 延迟序列化 |
| 2 | 前端内存（Undo 栈） | ⚠️ 中 | 2000+ 节点 | 库自身问题，不可控 |
| 3 | 网络传输延迟 | ✅ 低 | 弱网 + 大节点树 | Phase 1.2 增量传输 |
| 4 | 数据库写入 | ✅ 无 | — | 3-5ms，非瓶颈 |
| 5 | Buffer Pool 污染 | ⚠️ 中 | 100+ 并发 | Phase 2 Yjs 增量写入 |
| 6 | 并发写入覆盖 | 🔴 高 | 多标签/多人 | Phase 1 乐观锁 → Phase 2 Yjs |
| 7 | JSON 序列化 CPU | ✅ 无 | — | <15ms |

### 4.2 数据库写入性能基准

```
MySQL InnoDB + LONGTEXT (200KB):
  - 查找行（主键索引）: <0.1ms
  - 标记旧 LOB 页可回收: <0.1ms
  - 写入新 LOB 数据: ~1-3ms
  - Redo log: ~1ms
  - 总计: ~3-5ms
```

连接池配置（pool_size=50, max_overflow=10）足够支撑 Phase 1。

### 4.3 Phase 1 必做：乐观锁

防止多标签页编辑同一脑图时后写入覆盖先写入：

```sql
ALTER TABLE mindmap ADD COLUMN version INT DEFAULT 1 COMMENT '乐观锁版本号';
```

```python
result = await db.execute(
    update(Mindmap)
    .where(Mindmap.id == model.id, Mindmap.version == mindmap.version)
    .values(node_tree=..., version=Mindmap.version + 1)
)
if result.rowcount == 0:
    raise ServiceException(message='脑图已被其他人修改，请刷新后重试')
```

---

## 五、技术架构

### 5.1 Phase 1 架构

```
┌─ 前端 ─────────────────────────────┐
│  /mindmap/index  — 管理列表页        │
│  /mindmap/edit   — 编辑器页          │
│    ├── Edit.vue (改造: API 对接)     │
│    ├── Toolbar.vue                   │
│    └── NavigatorToolbar.vue          │
│                                      │
│  src/api/mindmap/mindmap.js          │
└───────────────┬──────────────────────┘
                │ REST API
                ↓
┌─ 后端 ─────────────────────────────┐
│  module_mindmap/                     │
│    ├── controller/mindmap_controller │  ← 新建
│    ├── service/mindmap_service       │  ← 增强（所有权校验）
│    ├── dao/mindmap_dao               │  ← 现有
│    └── entity/vo/mindmap_vo          │  ← 现有
│                                      │
│  mindmap 表                          │
└──────────────────────────────────────┘
```

### 5.2 Phase 2 架构（实时协作）

```
┌─ 用户A ──┐              ┌─ 用户B ──┐
│           │              │           │
│ simple-   │              │ simple-   │
│ mind-map  │              │ mind-map  │
│    ↕      │              │    ↕      │
│ YjsMindmap│              │ YjsMindmap│
│ Sync      │              │ Sync      │
│    ↕      │              │    ↕      │
│ Yjs Doc   │              │ Yjs Doc   │
│    ↕      │              │    ↕      │
│ WS Client │              │ WS Client │
└─────┬─────┘              └─────┬─────┘
      │ WebSocket                │ WebSocket
      ↓                          ↓
┌──────────────────────────────────────┐
│  FastAPI WebSocket 端点               │
│    ├── RoomManager (内存房间管理)      │
│    ├── YjsDocManager (持久化)         │
│    └── 认证: 连接后发送 auth 消息      │
│                                      │
│  mindmap_ws_state 表                  │
└──────────────────────────────────────┘
```

**Yjs 数据模型（细粒度，非整体替换）**：

```
Y.Doc
├── Y.Map('meta')           → { layout, theme: Y.Map, viewData: Y.Map }
└── Y.Map('nodes')          → { [uid]: Y.Map({ data, style, parentUid, sortOrder }) }
```

每个节点独立 Y.Map，修改一个节点只触发该节点的增量更新（~50 字节），不影响其他节点。

**关键桥梁**：`data_change_detail` 事件 → Yjs 操作翻译

### 5.3 WebSocket 认证方案

**不使用 URL query parameter 传递 token**。改为连接后发送认证消息：

```
客户端连接 → 服务端 accept
客户端: { "type": "auth", "token": "jwt..." }
服务端: { "type": "auth_ok", "user": {...} }
      或 { "type": "auth_error", "message": "..." } + close(4001)
后续: 正常消息处理
```

### 5.4 Yjs 持久化策略

- 每次 `update` 消息到达时，节流 30 秒持久化一次
- 最后一个用户离开房间时，立即持久化 + 同步回 `node_tree`
- 新用户加入时，先发送 `sync_init`（从 DB 加载 yjs_state）

---

## 六、API 设计

### 6.1 Phase 1 REST API

| Method | Path | 权限 | 描述 |
|--------|------|------|------|
| GET | `/mindmap/list` | `mindmap:mindmap:list` | 分页列表 |
| GET | `/mindmap/{id}` | `mindmap:mindmap:query` | 详情（含所有权校验） |
| POST | `/mindmap` | `mindmap:mindmap:add` | 新增 |
| PUT | `/mindmap` | `mindmap:mindmap:edit` | 编辑元数据 |
| DELETE | `/mindmap/{ids}` | `mindmap:mindmap:remove` | 批量删除 |
| PUT | `/mindmap/rename` | `mindmap:mindmap:edit` | 重命名 |
| POST | `/mindmap/copy/{id}` | `mindmap:mindmap:add` | 复制 |
| PUT | `/mindmap/content` | `mindmap:mindmap:edit` | 全量更新内容 |
| PUT | `/mindmap/content/incremental` | `mindmap:mindmap:edit` | 增量更新（Phase 1.2） |
| POST | `/mindmap/import` | `mindmap:mindmap:add` | 从 localStorage 导入 |

### 6.2 Phase 2 WebSocket API

```
WS /ws/mindmap/{mindmap_id}
```

消息协议见 §5.3。

### 6.3 Phase 3 版本 API

| Method | Path | 描述 |
|--------|------|------|
| GET | `/mindmap/version/list/{mindmap_id}` | 版本列表 |
| GET | `/mindmap/version/{version_id}` | 版本详情 |
| POST | `/mindmap/version/restore/{version_id}` | 回滚 |
| POST | `/mindmap/version/save` | 创建正式版本 |
| DELETE | `/mindmap/version/{version_id}` | 删除版本 |

### 6.4 Phase 4 分享 API

| Method | Path | 描述 |
|--------|------|------|
| POST | `/mindmap/share/link` | 生成分享链接 |
| GET | `/mindmap/share/link/{mindmap_id}` | 分享链接列表 |
| DELETE | `/mindmap/share/link/{share_id}` | 删除分享链接 |
| GET | `/mindmap/share/view/{share_token}` | 公开查看（无需登录） |
| POST | `/mindmap/collaborator` | 添加协作者 |
| GET | `/mindmap/collaborator/list/{mindmap_id}` | 协作者列表 |
| PUT | `/mindmap/collaborator` | 修改权限 |
| DELETE | `/mindmap/collaborator/{id}` | 移除协作者 |

### 6.5 Phase 5 模板 API

| Method | Path | 描述 |
|--------|------|------|
| GET | `/mindmap/template/list` | 模板列表（公开） |
| GET | `/mindmap/template/categories` | 分类列表 |
| GET | `/mindmap/template/{id}` | 模板详情 |
| POST | `/mindmap/template/use/{id}` | 使用模板创建脑图 |
| POST | `/mindmap/template` | 发布模板（管理员） |
| PUT | `/mindmap/template` | 编辑模板（管理员） |
| DELETE | `/mindmap/template/{id}` | 删除模板（管理员） |

---

## 七、前端路由规划

| 路径 | 组件 | 说明 |
|------|------|------|
| `/mindmap/index` | `views/mindmap/index.vue` | 管理列表页 |
| `/mindmap/edit?id=X` | `views/mindmap/edit.vue` | 编辑器（编辑模式） |
| `/mindmap/edit?id=X&readonly=1` | `views/mindmap/edit.vue` | 编辑器（只读模式） |
| `/mindmap/templates` | `views/mindmap/templates.vue` | 模板市场（Phase 5） |
| `/mindmap/view/:token` | `views/mindmap/view.vue` | 公开查看（Phase 4） |

---

## 八、安全与性能约束

| 约束 | 措施 |
|------|------|
| 脑图大小限制 | `node_tree` JSON 序列化后 ≤ **5MB**，Service 层校验 |
| 自动保存频率 | 前端 **5 秒**防抖 + 后端 rate limit |
| WebSocket 认证 | 连接后发送 auth 消息（token 不在 URL），10 秒超时 |
| 所有权校验 | 所有写操作均校验 `owner_id == current_user_id` |
| 并发覆盖防护 | Phase 1 乐观锁（version 字段），Phase 2 Yjs CRDT |
| 草稿版本上限 | 每个脑图最多 **10 个**草稿，超出自动清理 |
| 菜单 ID 范围 | 使用 **9000+** 避免与现有菜单冲突 |
| 传输加密 | 复用现有 TransportCryptoMiddleware |

---

## 九、关键文件清单

### 现有文件（需修改）

| 文件 | 变更内容 |
|------|---------|
| `module_mindmap/service/mindmap_service.py` | 添加所有权校验、乐观锁 |
| `module_mindmap/entity/do/mindmap_do.py` | 添加 `version` 字段 |
| `src/components/MindMap/Edit.vue` | 对接后端 API、增量保存、只读模式 |
| `src/router/index.js` | 替换 test 路由为正式路由 |

### 新建文件（Phase 1）

| 文件 | 职责 |
|------|------|
| `module_mindmap/controller/mindmap_controller.py` | REST API 端点 |
| `src/api/mindmap/mindmap.js` | 前端 API 层 |
| `src/views/mindmap/index.vue` | 管理列表页 |
| `src/views/mindmap/edit.vue` | 编辑器页面 |
| `sql/mindmap_menu.sql` | 菜单权限数据 |
| `ruoyi-fastapi-test/mindmap/test_mindmap_management.py` | 集成测试 |

### 新建文件（Phase 2）

| 文件 | 职责 |
|------|------|
| `module_mindmap/websocket/mindmap_ws.py` | WebSocket 端点 |
| `module_mindmap/websocket/room_manager.py` | 房间管理 |
| `module_mindmap/websocket/yjs_doc.py` | Yjs 持久化 |
| `module_mindmap/entity/do/mindmap_ws_state_do.py` | WS 状态 ORM |
| `src/utils/ws-client.js` | WS 客户端 |
| `src/utils/yjs-sync.js` | Yjs 同步桥 |
| `src/components/MindMap/Collaborators.vue` | 协作者 UI |

---

## 十、关键设计决策记录

### 决策 1：保持 mindmap 表整体覆盖设计

**决策**：不引入节点行表（mindmap_node），保持 node_tree LONGTEXT 整体存储。

**理由**：
- Phase 1 单人使用场景下，DB 写 200KB 仅需 3-5ms，不是瓶颈
- 加载性能优于查询 500 行节点表再建树
- 三张表方案引入大量一致性维护代码，Phase 1 性价比低
- Phase 2 的 Yjs 增量同步解决了真正的并发写入问题

**替代方案**：节点行表 + 快照缓存 + 操作日志三层方案 → 被否决（过度设计）

### 决策 2：Yjs 细粒度数据模型

**决策**：Yjs 中每个节点用独立的 `Y.Map`，而非把整棵树当作一个 `Y.Map` 值。

**理由**：
- 整体替换会失去 CRDT 的冲突自动解决能力
- 细粒度映射使单节点编辑只产生 ~50 字节增量
- 与 `data_change_detail` 事件天然对应，同步桥实现更简单

### 决策 3：WebSocket 连接后认证

**决策**：不在 URL query 中传递 token，改为连接建立后发送 auth 消息。

**理由**：URL 中的 token 会出现在服务器日志、浏览器历史、代理日志中，有泄露风险。

### 决策 4：Phase 1 增量传输优化

**决策**：利用 `data_change_detail` 事件，自动保存时只发送变更部分到后端，后端在内存中 merge 后整体写回。

**理由**：网络传输从 ~24KB 降到 ~50-200 字节，而 DB 写入不变。这是性价比最高的优化 —— 不改表结构，只改接口。

### 决策 5：草稿版本存快照而非 op_log 引用

**决策**：版本历史表存完整 node_tree 快照，而非引用 op_log ID 范围。

**理由**：快照方案回滚时一次查询即可，简单可靠。op_log 回放需要重放操作序列，实现复杂且容易出错。每个脑图最多 10 个草稿 × 24KB = 240KB，存储完全可接受。
