# 脑图 Agent 接入、管理与执行工作台规划

状态：产品与技术设计稿；不代表已实现。参考 `open-design` 的运行时/流式事件架构，但不复制其“项目文件即产物”的写入模型。本文以当前仓库代码为准；已有文档仅作背景材料，不作为执行指令。

## 1. 结论与边界

目标是在脑图画布内提供可观察、可中断、可接力的 Agent 执行体验，并让普通用户管理自己可用的本地与平台 Agent。

最重要的部署边界：远端 FastAPI 只能检测服务器上的可执行文件，不能扫描用户电脑。用户本地 Claude Code、Codex、Kimi CLI 的发现与运行，需要用户主动安装、配对和启用一个本地桥接进程。只有当浏览器、FastAPI 和 CLI 都运行在同一台机器上时，服务端检测才能被称为“本地扫描”。

不承诺展示 Claude/Codex 等模型的隐藏完整推理链。界面展示用户可见回复、供应商确实公开的思考摘要或思考中状态、工具调用、Todo、脑图提交与用量；供应商没有公开的内容明确标为“未提供”，不能伪造。

## 2. 当前基线与缺口

| 能力 | 当前代码事实 | 本次规划 |
| --- | --- | --- |
| Agent 注册 | `module_mindmap/ai/adapters/factory.py` 静态注册 Native/Codex/Claude，并接纳服务端 Python entry point；`registry.py` 做合同校验。 | 在现有 Adapter 上叠加“定义 / 用户设备安装 / 用户偏好”，不要把动态发现塞进单例静态注册表。 |
| Agent 管理 | `src/views/mindmap/ai-agents.vue` 和 `/mindmap/ai/admin/connectors` 是管理员运营面，负责启用、灰度、预算、密钥引用、健康与合同。 | 新增普通用户的“我的 Agent”；管理员页不降权复用，仍控制全局策略。 |
| Agent 选择 | `MindmapAiDialog.vue` 在高级设置中选择 Agent；服务端继续/重试可改 `agent_key`。 | 将当前 Agent/模型/执行位置前置到面板头部；正在执行时提供显式“停止并接力”。 |
| 执行过程 | 已有 SSE、会话历史、工具起止事件、草稿和云端直写回执；历史每轮 UI 只显示最近 20 条过程摘要。 | 完整可分页的实时轨迹，工具参数/结果的安全详情，稳定的 Todo 对象，断线续播。 |
| Claude | `claude-agent-sdk` Adapter 当前仅将 SDK 信封类型记录为 `agent_event`，正文与隐藏推理不进入审计。 | 增加独立的用户可见增量与可公开摘要映射；不把 SDK 信封或隐藏推理原样入库。 |
| Codex | 当前 Codex Adapter 已借助隔离 worker 与 app-server 调受限 MCP bridge；进度被收敛成 `agent_progress`。 | 保留现有安全执行；补充统一的 message/tool/todo 事件，不为了“参考 OpenDesign”而重写底层。 |
| 取消与脑图提交 | 已有 `cancel_requested`、execution epoch、任务租约、实时草稿保留、云端受控提交与撤销。 | 把这些语义做成用户可理解的状态；新增跨 Agent 接力事务，避免旧 Agent 晚到提交。 |

证据入口：`module_mindmap/ai/adapters/base.py`、`factory.py`、`claude.py`、`codex.py`；`module_mindmap/service/mindmap_ai_service.py`；`module_mindmap/entity/do/mindmap_ai_do.py`；`src/components/MindMap/MindmapAiDialog.vue`。本仓库 `mindmap-agent-kit` 的 stdio MCP 只在进程内维护 Artifact 草稿，不能直接写真实平台脑图；不能将其误作云端写入网关。

## 3. 从 OpenDesign 取什么、不取什么

| OpenDesign 机制 | 参考源 | 在本项目的落点 |
| --- | --- | --- |
| 声明式 `RuntimeAgentDef`：bin、版本探测、能力、模型、流格式、MCP 注入 | `apps/daemon/src/runtimes/types.ts` | 新建 `RuntimeDefinition`/driver catalog。定义与设备安装实例分离，CLI 新版本重新探测能力。 |
| 并行增量发现、逐项回报探测结果 | `apps/daemon/src/runtimes/detection.ts` | 本地桥接做受限扫描；前端逐条显示“发现 / 检查中 / 可用 / 需登录 / 不兼容”。 |
| 无 shell 的子进程、隔离 cwd、进程组取消与遗留进程清理 | `apps/daemon/src/runtimes/agent-process.ts` | 本地桥接用明确二进制与参数数组启动；运行目录临时隔离；取消杀进程树并保留崩溃恢复记录。 |
| Claude `stream-json`、Codex `app-server`、Kimi `acp` | `apps/daemon/src/runtimes/defs/{claude,codex,kimi}.ts` | 三个驱动各自做协议握手/解析，再归一到平台 `RunEvent`。Codex app-server 是 JSON-RPC，但不是 ACP；Kimi ACP 使用 JSON-RPC stdio；Claude 是 JSONL 流。 |
| 原始流 → 统一聊天块、工具块、思考状态 | `apps/web/src/providers/daemon.ts`、`runtime/chat/build-turn-blocks.ts` | FastAPI 先做可信规范化、脱敏和持久化；Vue 只展示统一事件，不解析各家原始帧。 |
| 项目文件作为 Agent 产物、较宽的本地工具权限 | OpenDesign daemon/project 模型 | **不照搬。** 脑图的权威版本在平台；所有节点写入仍走现有授权投影、`MindmapToolService`、修订/幂等校验和云端提交。 |

能力探测不能只看 `--version`。必须验证具体传输、取消、流式消息、模型列表、MCP 注入和 Todo/计划事件；OpenDesign 的 Kimi 定义也说明不同版本的 ACP stdio MCP 能力会变化。发现 ≠ 已认证 ≠ 可执行，状态必须分开。

## 4. 产品模型与用户流程

### 4.1 “我的 Agent”与管理员 Connector 分工

普通用户可：扫描自己设备上的已知 CLI；手动指定受信二进制；查看版本/协议/认证/能力；启用或隐藏；选择默认 Agent/模型；运行安全连接测试；查看数据流向与权限；解绑自己的设备。新发现项默认“待添加”，不能自动获得脑图权限。

管理员仍独占：是否允许某类 Agent、数据区域、网络/工具策略、模型白名单、灰度、预算上限、并发、保留期、服务端密钥引用与合同发布。用户偏好和管理员约束取交集；被管理员禁用的 Agent 在用户中心显示原因但不可启用。

扫描流程：用户点击“扫描本机 Agent” → 本地桥接仅检查注册表中允许的可执行文件名及用户明确添加的路径 → 每个候选执行有超时的无模型调用版本/帮助/能力探测 → 返回安装元数据与状态 → 用户逐个添加、测试连接、设为默认。未知可执行文件不能只因存在就被当成 Agent；需用户填写协议模板并通过合同测试。

状态建议：`not_installed`、`detected`、`needs_auth`、`ready`、`incompatible`、`disabled_by_admin`、`bridge_offline`、`probe_failed`。每个状态给出下一步动作与最后检测时间。

### 4.2 脑图里的执行与接力

1. 用户选 Agent、模型和授权范围（整图/分支/节点），看到执行位置和数据去向，再输入要求。
2. 建立任务，面板出现对话与执行时间线。Todo、工具、节点提交均有可点击回执；画布高亮此次影响节点。
3. 运行中追加要求沿用现有“加入当前任务的安全边界 / 排到下一轮”语义，不暗改已经在执行的工具参数。
4. 点击“停止”后立即显示 `停止请求已收到`；直到进程退出和提交栅栏落定前，不能假称已停止。已提交的节点保留，未提交的候选草稿保留或丢弃按现有模式明确提示；“撤销本轮”是单独动作。
5. 点击“切换 Agent”时，弹出接力确认：原 Agent、目标 Agent、授权范围/数据去向变化、当前已提交修改、未完成 Todo 与排队消息。确认后先停止旧 run，等待终态与文档修订确认，再创建新 job/run。不得把 Claude/Codex 的供应商会话 ID 当成跨 Agent 上下文。
6. 新 Agent 获得平台生成的接力摘要：原始用户目标、用户可见对话、已提交脑图修订、未完成 Todo、授权范围和未解决问题。旧工具结果与隐藏推理不直接作为新 Agent 指令。排队消息由用户选择保留/迁移，默认不静默转移。

任务状态机建议：`queued → preparing → running → cancel_requested → canceled`；正常则 `running → validating → completed`。跨 Agent 接力是新 job，带 `handoff_from_job_id` 和 `handoff_revision`，不是在原 job 内热换进程。复用现有 `execution_epoch`/租约，旧 epoch 一律禁止新增事件与云端提交；并发文档修改需比较修订，冲突时提示重新读取，不覆盖。

## 5. 技术架构

```text
Vue Agent 工作台 / 我的 Agent
  ├─ 现有 FastAPI：会话、任务、权限、修订、受控工具网关、SSE/历史
  │    ├─ 现有平台 Adapter：Native / Codex SDK worker / Claude SDK
  │    └─ 新 LocalRuntimeAdapter：按 user + device + installation 路由
  │         └─ 已配对的用户本地桥接（出站 WSS）
  │              ├─ 发现/能力探测
  │              ├─ Claude stream-json driver
  │              ├─ Codex app-server JSON-RPC driver
  │              └─ Kimi ACP JSON-RPC stdio driver
  └─ 统一 RunEvent 轨迹 + 画布变更回执
```

桥接采用本机安装、用户显式配对、主动向 FastAPI 建立出站加密连接，避免网页直接访问 localhost 和混合内容/CORS 障碍。设备密钥绑定用户与设备，可撤销。平台仅保存可公开安装元数据与偏好；本地 CLI 认证令牌不上传。桥接重连时上报设备/运行状态，服务端持有任务租约；离线超时后收束任务，不允许离线期间未确认的写入补报覆盖云端。

桥接每个 run 都要有：`run_id`、`job_id`、`execution_epoch`、设备/安装 ID、进程组 ID、协议会话 ID、启动时间、退出原因；不使用 shell 拼接命令，不继承全量环境变量，不把提示词放进 argv，限制 cwd、输入大小、运行时长、并发、stdout/stderr 速率。自定义 Agent 需经过协议合同测试及单独告知：平台能约束脑图工具调用，但本机程序对文件系统/网络的其他能力还取决于其自身和操作系统权限。

### 5.1 统一事件合同

新增版本化事件信封（示意）：

```json
{
  "schemaVersion": 2,
  "jobId": "...",
  "runId": "...",
  "executionEpoch": 3,
  "sequence": 42,
  "timestamp": "...",
  "source": "agent|platform|tool",
  "type": "tool_started",
  "payload": { "callId": "...", "toolName": "add_nodes", "targetUids": ["..."], "displayInput": { "nodeCount": 3 } }
}
```

核心类型：`run_status`、`assistant_delta`、`assistant_message`、`thinking_state`、`thinking_summary_delta`、`tool_started`、`tool_progress`、`tool_completed`、`tool_failed`、`todo_snapshot`、`todo_item_changed`、`mindmap_commit`、`approval_required`、`usage_updated`、`error`、`run_completed`。所有工具事件必须有稳定 `callId`，Todo 有稳定 `todoId`、状态和 `origin`（`agent_reported` 或 `platform_derived`）。不支持 Todo 的运行时可显示平台阶段清单，但不能标成 Agent 自己的计划。

Claude 若支持、且确实发出可公开思考摘要，可展示摘要增量；只发空 `thinking_delta` 时展示“正在思考”与耗时/用量，不展示伪造的文本。当前 SDK Adapter 必须显式映射可见消息与工具流；不能仅扩大 `agent_event` 审计信封。Codex app-server 的文本/推理摘要/工具通知、Kimi ACP 的 session updates 也分别映射。提供能力标记 `thinkingVisibility: none|status|summary`。

当前 `_safe_event_payload` 是严格白名单，不能简单加入 `arguments`、`stdout` 等原始字段。规范化层按工具 schema 生成可显示输入/输出：目标节点、操作数量、精简文本、耗时、结果/错误；权限外内容、密钥、路径、环境和大块正文一律裁剪/脱敏。需要更长详情时走鉴权详情接口与独立保留策略，不把原始供应商帧放进可重放审计表。

沿用现有事件表与 SSE 序号做持久化后推送，新增 schema/version 与 UI 投影；高频文本增量按短时间窗口合并，但保留顺序。前端以 `jobId + sequence` 去重，重连使用最后序号补播；历史分页加载，不再只截最近 20 条。进度、断线、停止中、取消完成要区分。

### 5.2 数据模型与接口增量

数据实体（名称可依项目命名规范调整）：

- `agent_runtime_definition`：内置/管理员允许的驱动、协议、能力、可探测版本范围；可代码定义并在接口输出，不强制建表。
- `user_agent_device`：用户设备、配对公钥/状态、最后在线时间，可撤销；不保存本地认证密钥。
- `user_agent_installation`：设备上发现的定义、版本、二进制引用/指纹、探测能力与结果、上次扫描；真实绝对路径仅本机保存，服务端最多保存非敏感显示名或不透明引用。
- `user_agent_preference`：用户启用、默认、模型、显示顺序；始终受管理员 Connector 上限约束。
- 现有 `mindmap_ai_job`：增加执行位置/设备/安装引用及 `handoff_from_job_id`、`handoff_revision`；沿用 `execution_epoch`、`parent_job_id`、幂等键。
- 现有 `mindmap_ai_job_event`：增加规范化事件 schema；Todo 可由事件重放，必要时建当前快照表供快速查询。

接口建议：`GET /mindmap/ai/agents/catalog`（用户可见合并列表），`POST /mindmap/ai/devices/pair`，`POST /mindmap/ai/agents/discover`（启动并流式返回扫描结果），`PATCH /mindmap/ai/agents/me/{installationId}`（偏好），`POST /mindmap/ai/agents/me/{installationId}/test`，`GET /mindmap/ai/jobs/{id}/events?afterSequence=`，`POST /mindmap/ai/jobs/{id}/cancel`（复用），`POST /mindmap/ai/jobs/{id}/handoff`。所有写入需用户鉴权、文档权限、幂等键和审计；配对/解绑需要明确用户确认。

## 6. UI 实现设计

### 6.1 脑图 Agent 工作台

桌面沿用顶部文档栏与中央画布，把当前 500px 左侧 `el-drawer` 升级为可调整宽度的左工作台（建议 420–520px，保证画布最小可用宽度）；窄屏退化成覆盖式抽屉。AI 工作台不与右侧属性面板同时挤占画布。面板结构：

```text
Agent / 模型 / 本机或平台 / 连接状态 / 切换 / 管理
任务状态、耗时、当前授权范围、实时连接状态
Todo 进度（可收起，但有持续可见的当前项）
按时间排序的会话：用户消息 → Agent 可见回复 → 工具卡 → 脑图提交卡
固定输入区：上下文范围、输入、加入当前/排下一轮、停止
```

工具卡默认展示名称、目标、状态、耗时与变更数；展开才展示脱敏参数、结果及错误。脑图提交卡点击定位节点、显示修订与“撤销本轮”入口。滚动到底部时自动跟随；用户向上读历史时停止自动跟随，并显示“有 N 条新记录”。`aria-live` 只播报关键状态，逐字增量不频繁抢屏幕阅读器。显示“思考中/公开摘要/未提供”，不可写“查看完整思维链”。

与现有 `MindmapAiDialog.vue` 的职责拆分：`AgentWorkbenchShell`、`AgentSelector`、`RunTimeline`、`AssistantMessage`、`ToolCallCard`、`TodoPanel`、`MindmapCommitCard`、`RunControls`、`AgentHandoffDialog`。现有画布预览、提交/撤销和会话恢复逻辑先保留为 composable/service，避免一次性重写 9800 行组件。实现前应补组件状态表和交互测试。

### 6.2 我的 Agent

新用户路由独立于现有管理员 `ai-agents.vue`。顶部扫描与桥接连接状态；“本机 Agent / 平台 Agent”分组；列表展示来源、版本、协议、认证、流式/工具/取消/Todo 能力、默认模型和检测时间；右侧详情展示执行位置、数据去向、脑图工具权限、管理员只读限制、测试结果。状态驱动操作，例如 `needs_auth` → 打开本机 CLI 登录说明，`incompatible` → 查看探测报告，`bridge_offline` → 重连本地桥接。不能在 UI 中暗示本地扫描自动遍历全盘，也不能把平台密钥和用户本机令牌混为一谈。

设计草稿：Agent 工作台 `https://p.superdesign.dev/draft/3d378931-8a02-42cb-8c1f-342145003868`；我的 Agent `https://p.superdesign.dev/draft/be2a5d44-6631-4dfa-8296-130d2c9ad67c`。草稿仅用于评审，示例版本号、可用性和能力不能作为实际探测结果。

## 7. 实施顺序与验收

| 阶段 | 交付 | 关键验收 |
| --- | --- | --- |
| 1. 可观察性与工作台 | 统一事件 v2；现有 3 个 Adapter 的可见消息/工具/Todo 映射；分页时间线；面板拆分。 | 一轮运行的用户可见回复、每次工具起止、Todo 来源、画布提交可以串起来；SSE 重连无重复/丢序；无隐藏推理/密钥泄露。 |
| 2. 用户 Agent 中心与本地桥接 | 设备配对、受限扫描、能力探测、用户偏好、Claude/Codex/Kimi 驱动。 | 远端部署可发现用户电脑上新增的已知 CLI；未安装/未登录/不兼容状态正确；未知 CLI 不自动执行；管理员策略有效。 |
| 3. 停止接力与恢复 | 运行中切换、旧进程停止栅栏、接力摘要、文档修订冲突、断线恢复。 | 停止后旧 epoch 无新提交；已提交修改可见且撤销独立；新 Agent 只从平台确认的修订继续；崩溃/断线不产生幽灵进程或重复写入。 |

需要覆盖的测试矩阵：三种协议的增量、工具/计划缺失、Claude 空 thinking、取消与工具提交并发、切换时排队消息、桥接离线/重连、用户跨设备、文档权限撤销、管理员禁用、本地 CLI 升级后能力变化、审计脱敏/截断、浏览器刷新及 SSE 续播。

## 8. 设计评审时需确认的产品选择

1. 第一版是否只支持已知 Claude/Codex/Kimi 驱动，自定义 CLI 放在后续；建议是。
2. 本地桥接的分发形态：独立桌面伴随程序，还是并入现有桌面壳；纯网页 + 远端服务端不足以完成用户本机扫描。
3. 默认轨迹密度：建议“对话和当前 Todo 常显、工具卡收合可展开”，同时提供“详细模式”；这不是隐藏工具详情。
4. 跨 Agent 接力时的排队消息处理与数据区域变更确认文案。
