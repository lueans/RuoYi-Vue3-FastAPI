# 脑图评论功能发布清单（2026-08-26）

## 发布范围

- 节点评论线程、回复、待处理/已解决状态、重开与软删除。
- 节点评论数量标记、评论侧栏、当前节点/全部范围筛选。
- 创建评论和回复的端到端幂等保护：客户端复用请求键，服务端按“作者 + 请求键”唯一约束兜底。
- 点击评论卡片即可定位并选中画布节点，卡片内部操作不会误触节点定位。
- 用例评审导航：从头查看、查看下一个、返回筛选结果，并在画布渲染完成后聚焦目标节点。

## DDL 清单

| 场景 | MySQL 8+ | PostgreSQL 14+ |
| --- | --- | --- |
| 新建评论表与索引 | `migrations/20260825_mindmap_comments.sql` | `migrations/20260825_mindmap_comments_postgresql.sql` |
| 补齐写入幂等列与唯一索引 | `migrations/20260826_mindmap_comment_idempotency.sql` | `migrations/20260826_mindmap_comment_idempotency_postgresql.sql` |
| 全新脑图库基线 | `migrations/mindmap_tables.sql` | `migrations/20260820_mindmap_postgresql.sql` |

增量迁移均按可重复执行设计。PostgreSQL 幂等迁移只会在同名索引结构错误时重建索引，结构正确时不会无条件加锁重建。

已有数据库必须按以下顺序执行，不能只部署应用代码：

1. `20260825_mindmap_comments` 对应当前数据库方言的文件。
2. `20260826_mindmap_comment_idempotency` 对应当前数据库方言的文件。
3. 运行只读 Schema 校验。
4. 部署后端，再部署前端。
5. 执行本清单中的 E2E 验收。

全新环境只执行对应数据库的完整基线；不要再重复套用评论增量迁移。

## 发布前只读检查

在 `ruoyi-fastapi-backend` 目录执行：

```bash
.venv/bin/python -m scripts.plan_mindmap_schema_migrations
.venv/bin/python -m scripts.verify_mindmap_schema
```

- 计划命令会按依赖顺序输出迁移文件、缺失对象和实时 SHA-256，不执行 SQL。
- 校验命令会检查表、列、索引、唯一性和索引列顺序，不修改数据库。
- 只有最终输出为 `READY` 才代表整个脑图 Schema 完整。

2026-08-26 的本机 MySQL 校验结果：

- 评论专属 Schema：`READY`，评论缺口为 0。
- 全脑图 Schema：`NOT_READY`，存在 16 个历史缺口；发布计划包含 6 个历史迁移。
- 仍需人工核对 `20260818_mindmap_permission_namespace.sql`。
- `20260825_mindmap_markers_to_tags.sql`（PostgreSQL 使用对应 `_postgresql` 文件）属于数据改写迁移，也必须由运维确认执行。

因此，本机评论功能可以运行，但不能把当前数据库标记为“全脑图 Schema 已完成”。上线前应根据计划命令输出补齐历史迁移，并在备份后由运维执行数据改写项。

## 应用契约检查

后端应注册以下接口：

- `POST /mindmap/comment`
- `GET /mindmap/comment/list/{mindmap_id}`
- `POST /mindmap/comment/{thread_id}/reply`
- `PUT /mindmap/comment/{thread_id}/status`
- `DELETE /mindmap/comment/message/{comment_id}`

创建和回复请求必须携带 `Idempotency-Key`。同一用户、同一请求意图重试时必须复用同一键；相同键对应不同意图时服务端应拒绝请求。

## E2E 验收

使用有编辑权限的测试脑图和唯一测试标记，依次验证：

1. 选择节点并发布评论，发布成功后输入框清空，节点计数增加。
2. 回复评论，回复只出现一次且输入框关闭。
3. 标记为已解决，线程从“待处理”移入“已解决”。
4. 在已解决线程中回复，线程自动重开并回到“待处理”。
5. 删除首条评论，确认提示明确说明会删除整条线程。
6. 重新打开页面，确认测试线程不可见且没有写入错误提示。
7. 从数据库只读确认测试评论和线程均为软删除，所有写入均含 `client_request_id`。
8. 验证点击评论卡片可定位并选中画布节点，卡片不再显示独立的节点主题按钮，回复/解决/删除等内部操作不会误触定位。
9. 在用例筛选结果中验证“从头查看”“查看下一个用例”“返回筛选结果”和末尾提示。

本地实测已完成上述评论步骤；产生的 3 条测试消息均带幂等键，评论与线程均已软删除，没有触碰真实评论。

## 监控与回滚

上线后重点监控评论写接口的 4xx/5xx、唯一索引冲突、数据库连接异常和列表刷新失败。网络超时后客户端可以安全重试，但不得为同一意图生成新幂等键。

应用回滚时优先只回滚前后端版本，保留新增表、列和索引；这些结构是向后兼容的，保留它们不会影响旧版应用。除非已有完整备份并完成评论数据归档，不要在故障处理中直接删除评论表或幂等列。

## 本次质量门禁

- 后端：635 个测试通过，4 个按环境跳过，115 个子测试通过。
- 前端：591 个测试通过。
- 本次 Python 变更：Ruff 与字节码编译通过。
- 前端生产构建：通过。
- `git diff --check`：通过。
- 全模块 Ruff 基线仍有 5 个与本功能无关的历史问题，未混入本次改动。
