# AI 脑图生成、Agent SDK 与本地脑图集成产品需求文档（PRD）

| 项目 | 内容 |
| --- | --- |
| 文档版本 | V1.0 |
| 文档日期 | 2026-09-10 |
| 产品模块 | 脑图编辑器 / AI 脑图 / Agent 集成 |
| 文档状态 | 产品评审稿；UI 设计前置输入 |
| 核心范围 | AI 直接生成可编辑脑图文件、本地脑图双向集成、自研 MindMap Agent、Codex SDK、Claude Agent SDK、可扩展 Agent Adapter |
| 首发门槛 | 自研 MindMap Agent、Codex SDK、Claude Agent SDK 三条链路均通过统一协议与端到端验收 |

## 0. 本次规划结论

本 PRD 建立 AI 脑图产品线。产品不把 AI 返回的一段 JSON 直接写进编辑器，而是建立统一的“生成文件—校验—预览—应用”闭环：

~~~text
用户意图 / 本地脑图 / 选中分支
        ↓
MindMap Agent Gateway
        ↓
自研 MindMap Agent / Codex SDK / Claude Agent SDK
        ↓
统一 MindMap Tool Contract
        ↓
AI 脑图提案 + 可下载 .smm 文件
        ↓
确定性校验 + 差异预览
        ↓
打开为本地脑图 / 插入本地分支 / 替换本地脑图 / 保存为云端脑图
~~~

关键决策：

1. “AI 直接生成脑图文件”指最终交付真实、可下载、可再次编辑的 `.smm` 文件，而不是要求用户复制 Markdown 或 JSON。
2. “和本地脑图互相集成”同时包含：AI 结果进入本地脑图，以及本地脑图或选中分支进入 AI 后再安全回写。
3. 自研 MindMap Agent 是产品拥有的领域 Agent；Codex SDK 和 Claude Agent SDK 是另外两种执行适配器，三者复用同一文件、工具、校验和任务合同。
4. Claude 官方已将“Claude Code SDK”更名为“Claude Agent SDK”。产品需求和代码使用新名称，对外说明中可写“Claude Agent SDK（原 Claude Code SDK）”。
5. 首发不允许任何 Agent 直接操作在线画布、数据库正文或用户真实文件系统。Agent 只能操作隔离工作区中的提案，最终由确定性服务校验并由用户明确应用。
6. 后续接入其他 Agent 时，只新增适配器和能力清单，不修改脑图文件规范、应用逻辑或核心 UI 状态机。

## 1. 背景与问题

### 1.1 用户问题

现有脑图产品已经支持本地匿名工作区、服务端文件、SMM/JSON/XMind/Markdown 导入、可编辑格式导出、版本历史和协同编辑，但 AI 与脑图仍是两套割裂的工作流：

1. 用户在通用 AI 工具中获得的通常是 Markdown、缩进文本或不稳定 JSON，无法直接作为可靠脑图文件使用。
2. 用户需要反复复制、粘贴、调整层级和修复格式，AI 生成价值在进入编辑器前大量损耗。
3. 本地脑图无法方便地把当前结构或选中分支交给 AI 扩写、改写或重组。
4. 通用模型可能生成重复 UID、过深结构、危险链接、无效节点或不受支持字段，直接导入会带来数据与安全风险。
5. Codex、Claude 和产品已有模型能力具有不同会话、工具、权限和输出方式，如果分别接入，产品会快速出现三套任务和写入逻辑。
6. 未来接入其他 Agent 时，若没有统一协议，每接一个 Agent 都要改编辑器、存储和验收体系。

### 1.2 当前实现基线

以下是本 PRD 基于代码确认的现状，不作为待重新实现的功能：

| 能力 | 当前基线 |
| --- | --- |
| 脑图文档 | `root/layout/theme/view/documentData`，渲染引擎为 simple-mind-map |
| 可编辑导入 | `.xmind/.smm/.json/.md` |
| 导出 | SMM、JSON、PNG、SVG、PDF、Markdown、XMind、TXT |
| 通用导入上限 | 20 MB、20,000 节点、256 层、稳定 UID 最长 64 字符 |
| 匿名本地工作区 | `MIND_MAP_DATA` v1，完整 UTF-8 快照上限 2 MB |
| 云端保存 | 结构化节点、内容修订号、幂等批量操作、Yjs 协同和权威回源 |
| 云端创建 | 空白创建、复制、`POST /mindmap/import` 导入创建均已有幂等合同 |
| AI 基础 | FastAPI 后端已有 Agno 会话、流式响应、模型配置和 OpenAI/Anthropic 等模型提供商工厂 |
| Python 运行时 | 项目要求 Python 3.10+，与当前 Codex Python SDK、Claude Agent SDK 基线兼容 |

本 PRD 优先复用上述能力，不创建第二套脑图编辑器、第二套文档主数据或平行的云端保存协议。

## 2. 产品目标与非目标

### 2.1 产品目标

1. 用户可以从一句需求、粘贴文本或支持的本地文件直接获得可编辑 `.smm` 脑图文件。
2. 用户可以把 AI 结果安全地打开为本地脑图、插入现有本地脑图、替换本地脑图或保存为新的云端脑图。
3. 用户可以把当前本地脑图或选中分支交给 AI 扩写、改写、精简或重组，并在差异确认后回写。
4. 首发同时支持自研 MindMap Agent、Codex SDK 和 Claude Agent SDK。
5. 三类 Agent 使用统一任务状态、事件、工具、文件和错误合同，用户切换 Agent 不改变基本使用流程。
6. 通过可声明能力的 Agent Adapter 支持未来接入其他 Agent，而不把最低公共能力限制成所有供应商的最小交集。
7. AI 结果在进入本地或云端正文前必须经过与现有导入、存储兼容的确定性校验。
8. 对现有脑图的 AI 修改必须可预览、可拒绝、可恢复，不覆盖用户在任务期间的新修改。
9. 提供可观测的耗时、成本、成功率、无效输出率和人工采用率。

### 2.2 首个价值闭环

~~~text
输入主题或材料
→ 选择 Agent 和生成目标
→ 获得结构预览及真实 .smm 文件
→ 打开为本地脑图
→ 在本地继续编辑
→ 选中分支再次交给 AI 扩写
→ 查看差异并应用
→ 导出文件或保存到云端
~~~

只有当生成结果无需人工复制格式即可进入本地编辑，并能再次送回 AI 形成可控迭代，才视为闭环完成。

### 2.3 成功标准

- 三种首发 Agent 均能生成通过统一校验的 `.smm` 文件。
- AI 文件导入本地后可正常编辑、保存、再次导出和再次提交给 AI。
- 同一 AI 文件执行“导入—导出—再导入”后，规范化业务语义不丢失。
- Agent 任务运行期间本地或云端正文发生变化时，旧提案不得静默覆盖新内容。
- 所有写入现有脑图的 AI 操作均有差异摘要、明确确认和单次撤销能力。
- Agent 输出的重复 UID、危险协议、越界结构、未知字段和悬空引用进入正文的次数为 0。
- 用户选择某 Agent 后，系统不得因失败静默切换到另一 Agent 产生不同成本或数据边界。
- 新 Agent 只有通过统一适配器一致性测试后才能被启用。

### 2.4 非目标

- 首发不让 Agent 直接控制用户桌面、浏览器、任意代码仓库或真实文件目录。
- 首发不允许 Agent 无确认地修改现有本地或云端脑图。
- 首发不生成图片、音视频或二进制附件；已有资源只按授权范围保留，不发送给 Agent。
- 首发不提供多个 Agent 自动辩论、投票或串联执行。
- 首发不承诺不同 Agent 对同一提示生成相同内容，只要求协议、安全和文件结果一致可用。
- 首发不提供定时生成、批量生成数百个脑图或跨脑图知识库问答。
- 首发不允许租户上传并直接执行任意 Agent 二进制、脚本或容器镜像。

## 3. 名词定义

| 名词 | 定义 |
| --- | --- |
| AI 脑图文件 | 由 Agent 生成且通过确定性校验的可编辑 `.smm` 文件。 |
| 本地脑图 | 没有服务端文件 ID、保存在当前浏览器本地工作区中的脑图。 |
| 本地脑图文件 | 用户设备上的 `.smm/.json/.xmind/.md` 等文件，与浏览器本地工作区不同。 |
| 云端脑图 | 拥有服务端文件 ID、内容修订号、版本与协同能力的脑图。 |
| MindMap Agent | 产品自建的脑图领域 Agent，拥有规划、脑图工具调用、校验和修复能力。 |
| Agent Gateway | 统一接收任务、选择适配器、隔离运行、汇聚事件和产出提案的服务。 |
| Agent Adapter | 将统一任务合同映射为某个 Agent SDK 或执行环境的适配层。 |
| Codex Adapter | 基于官方 Codex SDK 的首发适配器。 |
| Claude Adapter | 基于 Claude Agent SDK（原 Claude Code SDK）的首发适配器。 |
| Native Adapter | 使用现有 Agno/模型工厂运行自研 MindMap Agent 的首发适配器。 |
| Tool Contract | 所有 Agent 调用的脑图读取、构建、校验和完成工具协议。 |
| 提案 | 尚未写入当前脑图的候选文档或候选变更集合。 |
| AI 生成包 | 含文件清单、规范脑图文档和可选来源声明的 SMM v2 信封。 |
| 基线快照 | 创建修改任务时冻结的本地或云端脑图内容及其哈希/修订。 |
| 本地应用包 | 服务端为本地编辑器返回的、绑定基线哈希的不可变提案。 |
| 云端应用 | 服务端在修订与协作栅栏下把已确认提案原子写入云端正文。 |
| 来源声明 | 文件中关于生成 Agent 和版本的可携带说明，不自动等于可信审计事实。 |

## 4. 用户与权限

### 4.1 用户角色

| 能力 | 匿名本地用户 | 登录用户 | 云端可编辑协作者 | 只读协作者 | 平台管理员 |
| --- | --- | --- | --- | --- | --- |
| 从提示生成 AI 文件 | 按租户策略；默认需登录 | 是 | 是 | 是，但不能回写云端 | 配置策略 |
| 下载 AI 文件 | 是 | 是 | 是 | 是 | 是 |
| 打开/替换本地脑图 | 是 | 是 | 是 | 是 | 是 |
| 修改本地脑图后交给 AI | 是 | 是 | 是 | 是 | 是 |
| 应用到云端脑图 | 否 | 自有文件可编辑时 | 是 | 否 | 依资源权限 |
| 保存 AI 文件为新云端脑图 | 否 | 需 `mindmap:add` | 需 `mindmap:add` | 需 `mindmap:add` | 依权限 |
| 选择已启用 Agent | 按策略 | 是 | 是 | 是 | 是 |
| 配置 Agent 连接与密钥 | 否 | 否 | 否 | 否 | 是 |
| 启停 Agent Adapter | 否 | 否 | 否 | 否 | 是 |
| 查看全局成本和健康状态 | 否 | 否 | 否 | 否 | 是 |

### 4.2 权限通用规则

1. “能查看脑图”不等于“能把脑图内容发送给 AI”。租户管理员可独立关闭 `mindmap.ai.use`。
2. 使用 AI 需同时满足用户能力、租户策略、Agent 已启用和连接健康。
3. 云端变更在创建任务、读取快照和最终应用时分别重新鉴权。
4. 归档、回收站、历史预览、分享匿名预览和完整性失败的云端文件不能应用 AI 修改。
5. 只读用户可基于其可读范围生成一个独立 AI 文件，但不能把结果写回原云端文件。
6. 匿名本地用户若被租户关闭匿名 AI，只保留本地文件导入导出，不上传内容。
7. 跨租户读取任务、会话、文件和 Agent 配置返回 404，避免泄露资源存在性。
8. 前端隐藏入口不代替服务端鉴权。

## 5. 范围与版本规划

### 5.1 首发 MVP

| 功能域 | 功能 | 是否首发 |
| --- | --- | --- |
| AI 创建 | 主题/文本/Markdown 生成新脑图 | 是 |
| 文件交付 | 生成、校验、预览、下载 SMM v2 | 是 |
| 本地打开 | AI 文件打开为当前本地脑图 | 是 |
| 本地集成 | 插入为分支、替换脑图、选区改写、撤销 | 是 |
| 云端集成 | 保存为新云端文件、对可编辑云端脑图 CAS 应用 | 是 |
| Agent | 自研 MindMap Agent | 是 |
| SDK | Codex SDK Adapter | 是 |
| SDK | Claude Agent SDK Adapter | 是 |
| 扩展 | Agent Adapter 注册与能力协商 | 是 |
| 多轮 | 对同一提案追问、精简和重新生成 | 是 |
| 输入文件 | SMM、JSON、XMind、Markdown、TXT | 是 |
| 媒体生成 | AI 新增图片、音频、视频、附件 | 否 |
| 多 Agent 编排 | 并行生成、评审、投票、自动择优 | 否 |
| 自动化 | 定时、批量、无人确认地回写 | 否 |

### 5.2 首发内部阶段

~~~text
M0 文件协议与安全校验
→ M1 自研 MindMap Agent + 本地闭环
→ M2 Codex SDK + Claude Agent SDK 适配
→ M3 云端 CAS 应用 + 全量灰度
~~~

M0～M3 都属于本 PRD 的首发范围。不得把 Codex 或 Claude 接入降级为“未来规划”后宣称首发完成。

## 6. 产品能力模型

### 6.1 生成意图

首发支持以下标准意图：

| 意图 | 输入 | 输出 | 默认应用方式 |
| --- | --- | --- | --- |
| `create` | 提示词或文本材料 | 新脑图文件 | 打开为本地脑图 |
| `expand` | 当前脑图 + 选中节点 | 在选中节点下新增完整分支 | 插入分支 |
| `rewrite_branch` | 当前脑图 + 选中分支 | 替换该分支的候选版本 | 差异确认后替换 |
| `condense_branch` | 当前脑图 + 选中分支 | 更精简的候选分支 | 差异确认后替换 |
| `reorganize` | 当前脑图或选中分支 | 重新组织后的候选结构 | 差异确认后替换 |

不允许 Agent 自造未知意图。未来增加意图必须升级能力清单和验收用例。

### 6.2 生成参数

请求允许设置：

- 输出语言；
- 目标布局：思维导图、逻辑结构、组织结构、目录组织图、时间轴、鱼骨图；
- 期望深度，范围 2～32；
- 最大节点数，范围 5～2,000，默认 100；
- 内容密度：简洁、标准、详细；
- 是否保留输入中的备注、安全链接和普通标签；
- 选用的 Agent；
- 可选的用户补充规则。

主题、颜色、字体和节点样式不由模型任意生成。首发由产品根据布局和当前文档主题确定性应用样式，减少跨 Agent 差异和非法 CSS 风险。

### 6.3 输入材料

| 输入 | 处理方式 |
| --- | --- |
| 直接提示词 | 作为主要目标 |
| 粘贴纯文本 | 规范化换行后作为材料 |
| Markdown/TXT | 提取文本与层级 |
| SMM/JSON | 先通过本地脑图解析器与校验器，再生成安全投影 |
| XMind | 浏览器本地解析选定画布，再生成安全投影 |
| 当前本地脑图 | 绑定本地文档 ID、修订和文档哈希 |
| 当前云端脑图 | 服务端读取权威内容，绑定内容修订和协作 epoch |
| 选中分支 | 包含从根到选中节点的最小路径上下文和完整分支 |

PDF、Word、网页抓取、数据库和第三方知识库不在首发输入范围，避免把文档解析与连接器权限混入 AI 脑图第一阶段。

### 6.4 Agent 能力矩阵

| 能力 | 自研 MindMap Agent | Codex SDK | Claude Agent SDK | 未来 Agent |
| --- | --- | --- | --- | --- |
| 创建新脑图 | 必须 | 必须 | 必须 | 由 manifest 声明 |
| 输出真实 `.smm` | 必须 | 必须 | 必须 | 必须后才可显示此能力 |
| 读取安全脑图投影 | 必须 | 必须 | 必须 | 可选 |
| 扩写/改写分支 | 必须 | 必须 | 必须 | 可选 |
| 多轮继续 | 必须 | 必须 | 必须 | 可选 |
| 流式事件 | 必须 | 必须 | 必须 | 可选，缺失时降级为阶段状态 |
| 结构化结果 | 原生工具结果 | 适配器规范化 | SDK JSON Schema | 必须经适配器规范化 |
| 取消 | 必须 | 必须 | 必须 | 必须 |
| 费用与用量 | 必须 | 尽力映射 | 必须映射 | 由 manifest 声明 |
| 任意外部写入 | 禁止 | 禁止 | 禁止 | 禁止 |

## 7. AI 脑图文件协议

### 7.1 格式选择

AI 生成文件统一使用 `.smm` 扩展名和 SMM v2 信封。`.json` 可继续作为兼容导出，但不作为 Agent 的默认交付格式。

~~~json
{
  "format": "ruoyi-mindmap",
  "formatSchemaVersion": 2,
  "manifest": {
    "artifactId": "optional-server-artifact-uuid",
    "title": "支付系统测试方案",
    "sourceType": "ai_generated",
    "createdAt": "2026-09-10T08:00:00Z",
    "generator": {
      "agentKey": "mindmap_native",
      "adapterVersion": "1.0.0",
      "promptVersion": "mindmap-create-1"
    },
    "validation": {
      "status": "passed",
      "validatorVersion": "mindmap-validator-2"
    },
    "documentHash": "mmf2:sha256:..."
  },
  "document": {
    "root": {
      "data": {"uid": "uuid", "text": "支付系统测试方案"},
      "children": []
    },
    "layout": "logicalStructure",
    "theme": {"template": "default", "config": {}},
    "view": null,
    "documentData": {}
  }
}
~~~

### 7.2 兼容规则

1. SMM v2 解析器识别 `format/formatSchemaVersion/manifest/document`。
2. 当前无信封、直接包含 `root` 的 SMM/JSON 视为 legacy v1，继续导入。
3. legacy v1 经校验后在下一次导出时升级为 v2，不在原文件上写回。
4. `formatSchemaVersion` 高于客户端支持版本时，禁止可写打开；可提供只读元信息和升级提示。
5. `document` 继续使用现有 `root/layout/theme/view/documentData` 语义，避免建立第二套树模型。
6. XMind、Markdown 和 TXT 先转换为规范 `document`，再进入统一校验与目标选择流程。

### 7.3 Manifest 可信度

1. `generator` 是可携带来源声明，不是权限、计费或审计事实。
2. 在线时，只有 `artifactId + documentHash` 能在当前租户的服务端记录中匹配，才显示“平台已验证生成来源”。
3. 外部 Codex/Claude 或其他工具直接生成、手工修改、服务端记录过期的文件显示“来源未验证”，但只要内容合法仍可导入。
4. 文件内的用户 ID、SDK 会话 ID、API Key、完整提示词、成本、内部路径和服务端审计 ID 一律忽略并在规范化导出时移除。
5. 修改文件内容后哈希不匹配，已验证状态立即失效。

### 7.4 文档哈希

`documentHash` 使用 `mmf2` 命名空间：

~~~text
mmf2:sha256:<RFC 8785 canonical document bytes>
~~~

哈希输入只包含规范化 `document`，不包含 manifest、自身哈希、临时选中态、渲染缓存和运行时回指。JS 与 Python 使用同一组 golden vectors。

### 7.5 节点与字段约束

1. 每份文档必须且只能有一个根节点。
2. AI 生成的最终 UID 由 MindMap Tool Service 分配；模型提交临时引用，不自行决定持久 UID。
3. 修改既有脑图时保留未删除节点的 UID；新节点使用新的稳定 UID。
4. 合并到现有脑图时，对全部传入新节点重新映射 UID，防止与当前文档或其他文件碰撞。
5. 所有父子、关联线、概要、外框和资源引用必须指向当前文档内存在的目标。
6. 移除 `isActive/inserting/needUpdate/resetRichText/activeStyle` 等运行时字段。
7. AI 首发允许生成：文本、备注、安全超链接、普通标签文本建议、受控图标和产品确定性样式意图。
8. AI 首发禁止生成：图片二进制、附件、Data URL、Blob URL、脚本协议、任意 CSS、事件处理器和未知可执行扩展。
9. 通用导入硬上限沿用 20 MB、20,000 节点和 256 层；AI 任务输出额外限制为 2,000 节点、32 层、规范化 `document` 不超过 1.8 MB、完整 SMM v2 文件不超过 2 MB，为现有匿名本地工作区元数据预留空间。
10. 超限结果整体失败，不截断前 N 个节点伪装为完整文件。

### 7.6 正式 Artifact 与草稿 Artifact

1. `validation.status=passed` 才是正式 artifact，可以进入 `ready` 并执行本地或云端应用。
2. `validation.status=draft` 用于结构与文件安全已通过、但仍需人工确认的结果；必须携带问题清单。
3. 草稿下载文件名包含 `.draft.smm`，再次导入时仍重新执行完整校验，不能通过改 manifest 绕过。
4. 结构、安全、大小或引用校验失败的内容不生成可下载 artifact，只保留脱敏诊断。
5. 客户端和未来 Agent 不能自行把 draft 改为 passed；正式状态由统一 Validator 签发并通过 hash 绑定。

## 8. MindMap Tool Contract

### 8.1 设计原则

Agent 不直接拼装最终 SMM JSON，不直接调用数据库或编辑器接口。三种首发 Agent 都通过同一组领域工具完成工作。

### 8.2 首发工具

| 工具 | 作用 | 是否修改真实脑图 |
| --- | --- | --- |
| `mindmap.read_projection` | 读取本次授权范围的安全层级投影 | 否 |
| `mindmap.start_document` | 创建隔离的候选文档及临时引用空间 | 否 |
| `mindmap.add_nodes` | 批量添加候选节点 | 否 |
| `mindmap.update_nodes` | 修改候选节点允许字段 | 否 |
| `mindmap.move_nodes` | 在候选文档内调整层级和顺序 | 否 |
| `mindmap.remove_nodes` | 从候选文档移除节点或分支 | 否 |
| `mindmap.set_document_meta` | 设置标题、布局和确定性样式意图 | 否 |
| `mindmap.validate_draft` | 运行结构、字段、安全与规模校验 | 否 |
| `mindmap.complete_artifact` | 冻结提案、生成 SMM v2 和哈希 | 否 |

### 8.3 工具约束

1. 每次工具调用输入都用 JSON Schema 校验，未知字段拒绝。
2. 每个 job 只能访问自己的临时文档和只读基线投影。
3. `read_projection` 不返回 API Key、用户身份、协作成员、评论、版本、附件二进制或未授权分支。
4. 工具服务分配持久 UID、修复临时引用并生成稳定顺序，不信任模型提供的最终 UID。
5. 单次 `add_nodes/update_nodes/move_nodes/remove_nodes` 最多处理 200 个目标；超出时 Agent 分批构建候选文档，但最终仍只形成一个提案。
6. `complete_artifact` 只有在完整校验后成功；Agent 最多自动修复三轮。结构或安全校验失败则任务进入 `failed`；可安全打开但仍需人工确认时，平台可冻结带问题清单的 draft artifact，并进入 `needs_review`。
7. 完成后的 artifact 不可变。继续修改必须生成新的 proposalVersion 和 documentHash。
8. 工具调用写入低敏审计：工具名、数量、耗时和结果码，不记录节点全文。

### 8.4 外部 AI 工具包

为满足 Codex、Claude 及未来外部 Agent 直接生成文件，发布独立的 MindMap Agent Kit：

- SMM v2 JSON Schema；
- Python/TypeScript 文件构建器；
- `validate` 与 `render-summary` 命令；
- 本地 stdio MCP Server，暴露 8.2 的工具；
- 示例 Skill/AGENTS/CLAUDE 指令，仅描述文件合同，不包含平台密钥；
- conformance fixtures 和版本兼容说明。

外部工具包默认只写用户明确提供的输出目录。生成文件没有平台服务端记录时按“来源未验证”导入，不能伪装成平台已验证任务。

## 9. Agent Gateway 与适配器架构

### 9.1 分层

~~~text
产品请求层
  └── 权限、配额、输入准备、任务和会话
        └── MindMap Agent Orchestrator
              ├── Native Adapter（Agno）
              ├── Codex Adapter（openai-codex）
              ├── Claude Adapter（claude-agent-sdk）
              └── Future Adapter
                    └── MindMap Tool Service
                          └── Validator / Artifact / Diff / Apply
~~~

领域编排、文件校验、差异和应用属于产品核心；SDK 只负责 Agent 执行，不拥有脑图写权限。

### 9.2 统一 Adapter 接口

~~~text
AgentAdapter {
  get_manifest() -> AgentManifest
  healthcheck() -> HealthStatus
  start(job_context) -> ExternalRunRef
  send_message(run_ref, message) -> AsyncEventStream
  cancel(run_ref) -> CancelResult
  resume(run_ref, checkpoint) -> AsyncEventStream
  collect_usage(run_ref) -> UsageRecord
  close(run_ref) -> None
}
~~~

`AgentManifest` 至少包含：

- `agentKey/displayName/adapterVersion`；
- `sdkName/sdkVersion/runtimeVersion`；
- 支持的意图、输入类型、最大节点、会话、流式、结构化输出和用量能力；
- 数据处理区域、认证类型和是否允许网络；
- 当前状态：enabled/degraded/disabled；
- 兼容的 Tool Contract 与 SMM 版本范围。

### 9.3 能力协商

1. 前端只展示服务端返回且当前用户可用的能力，不硬编码供应商能力。
2. 用户选择不支持某意图的 Agent 时，创建前拒绝并说明可用 Agent，不在后台自动换 Agent。
3. Adapter 可以保留供应商特有事件和用量字段，但必须同时映射统一字段。
4. 新 Agent 不需要实现所有能力；但必须实现任务取消、artifact 校验和错误映射，才能进入生产。
5. Adapter 版本升级先在影子环境跑 conformance suite，再灰度到租户。

### 9.4 失败隔离

1. 每个任务独立运行目录、进程/容器、临时凭据和资源限额。
2. 某一 Adapter 不健康只禁用自身，不影响本地导入导出或其他 Agent。
3. 选定 Agent 失败后保留输入快照与安全错误摘要，用户可明确选择“使用其他 Agent 重试”。
4. 重试其他 Agent 创建新 jobId，不复用原供应商 sessionId，不把原 Agent 的隐藏上下文传递过去。

## 10. 三种首发 Agent 的具体合同

### 10.1 自研 MindMap Agent

定位：产品默认 Agent，负责通用脑图生成和编辑，不依赖代码仓库能力。

实现要求：

1. 复用现有 Agno 会话基础设施和 `AiUtil` 模型工厂，但使用独立 `session_type=mindmap_agent`。
2. 系统指令、工具定义、示例和后处理由产品版本化，不复用用户通用聊天 system prompt。
3. Agent 只获得 MindMap Tool Contract，不获得 Shell、数据库、任意 HTTP 或文件系统工具。
4. 可选择管理员已配置的 OpenAI、Anthropic 或其他基础模型，但“运行时 Agent”仍显示为自研 MindMap Agent。
5. 每个意图拥有独立 promptVersion 和评测集。
6. 原生支持 `needs_input`，最多一次提出 1～3 个与结构结果直接相关的问题。

自研 Agent 由产品维护以下可独立版本化的领域组件：

| 组件 | 职责 | 是否调用模型 |
|---|---|---|
| Intent Resolver | 把用户输入映射为标准意图、范围和约束；信息不足时触发 `needs_input` | 可选 |
| Context Builder | 从本地/云端快照生成最小安全投影、路径上下文和业务规则 | 否 |
| Structure Planner | 规划根主题、层级和节点预算 | 是 |
| Draft Builder | 仅通过 MindMap Tool Contract 分批构建候选文档 | 是 |
| Rule Critic | 根据统一 Validator 的结构化错误提出定向修复，最多三轮 | 是 |
| Artifact Finalizer | 重新校验、规范化、计算 hash 并冻结正式或受限草稿 artifact | 否 |

模型负责内容与结构建议，UID、文件序列化、规则结论、hash 和写入决定均由确定性组件负责。更换底层模型不改变“自研 MindMap Agent”这一产品身份，也不得绕过组件边界。

### 10.2 Codex SDK Adapter

定位：使用官方 Codex SDK 执行脑图 Agent 任务，并交付与其他 Agent 相同的 SMM v2。

首发技术基线：

1. FastAPI 后端采用稳定版 Python 包 `openai-codex`，与项目 Python 3.10+ 对齐；SDK 通过其固定的 Codex app-server/CLI 运行时工作。
2. 每个任务使用独立临时工作区，线程可在同一提案会话内继续和恢复。
3. 运行权限固定为等价 `workspace_write` 的隔离目录，禁止 `full_access`。
4. 可写根只有任务临时目录；真实仓库、用户目录、上传目录、服务端源码和其他任务目录不可见。
5. 网络仅允许 Codex 认证/模型所需端点；不允许 Agent 自主浏览网页或访问用户 URL。
6. 提供 SMM schema、只读输入投影和 MindMap Tool Contract；最终结果以已冻结 artifact 为准，不解析自然语言回答来写正文。
7. SDK threadId 加密存储并与平台 job/session 绑定，不返回浏览器，也不写入 SMM 文件。
8. SDK 版本和固定运行时版本进入 AgentManifest、任务审计与回归矩阵。

### 10.3 Claude Agent SDK Adapter

定位：使用 Claude Agent SDK（原 Claude Code SDK）执行脑图 Agent 任务。

首发技术基线：

1. FastAPI Worker 使用 Python 包 `claude-agent-sdk`，与项目 Python 3.10+ 对齐。
2. 使用 Anthropic API Key 或管理员配置的 Bedrock/Vertex/Foundry 认证；未经 Anthropic 明确批准，不向终端用户提供 claude.ai 登录或转售其登录额度。
3. 运行在隔离容器或等价强度沙盒中，采用拒绝询问的非交互权限策略，只允许 MindMap 自定义工具和只读输入。
4. 禁止 Bash、任意文件编辑、WebFetch、浏览器和未列入允许清单的 MCP 工具；文件产物由 `complete_artifact` 工具生成。
5. 使用 SDK 的 JSON Schema 结构化输出作为任务摘要，真实脑图仍以工具服务生成的 artifact 为准。
6. 会话需要跨 Worker 恢复时，使用受控外部 SessionStore；不得依赖单机 `~/.claude/projects` 作为生产事实源。
7. sessionId 加密存储，不返回浏览器，不写入导出文件。
8. SDK、内置 Claude Code runtime 和模型版本分别记录，任一升级均重跑适配器验收。

### 10.4 未来 Agent Adapter

新 Agent 接入步骤：

1. 实现 9.2 的接口和版本化 manifest；
2. 只使用统一 Tool Contract；
3. 将供应商状态、错误、取消和用量映射到平台合同；
4. 通过文件、权限、沙盒、提示注入、取消、超时和并发 conformance suite；
5. 管理员显式启用并配置租户范围；
6. 灰度期间可随时只关闭该 Adapter，不影响已有文件和其他 Agent。

不得通过在前端增加供应商判断、允许 Agent 直接调用脑图保存接口或复制一份 Validator 来接入新 Agent。

## 11. 核心业务流程

### 11.1 AI 从零生成脑图文件

1. 用户输入主题、补充说明、目标深度、语言、脑图类型和期望 Agent。
2. 服务端校验权限、Agent 健康状态、参数上限和预计资源消耗，使用 `Idempotency-Key` 创建任务。
3. 系统生成隔离任务目录，写入只读上下文投影；不得把真实工作区路径暴露给 Agent。
4. Agent 通过 MindMap Tool Contract 分批创建草稿，期间持续执行节点数、深度、字段和引用校验。
5. `complete_artifact` 冻结草稿，服务端重新计算 `documentHash`，生成不可变 artifact。
6. 任务进入 `ready`。用户可以下载 `.smm`、在本地工作区打开、另存为云端脑图或继续迭代。
7. “文件生成成功”只表示 artifact 可下载，不等于已打开、已写入本地工作区或已保存云端。

完成标准：下载后的文件可以离线重新导入，结构、节点语义、标签和文档元数据保持一致。

### 11.2 本地脑图交给 AI 编辑

1. 客户端先保存当前本地草稿，再把规范化快照、`documentId`、`revision`、`documentHash` 和作用域提交给服务端。
2. 作用域必须是 `document`、`branch` 或明确的 `selectedNodes`；分支任务必须携带选中根节点 UID。
3. 服务端剥离 UI 临时状态、选择状态、撤销栈和本机路径，生成 Agent 可读投影。
4. Agent 生成提案，不直接修改本地数据；提案包含操作列表、结果快照、影响摘要和基线标识。
5. 客户端在影子副本上应用并校验提案，确认基线仍一致后才原子替换当前文档。
6. 应用成功形成一条撤销记录；应用前后的 hash、节点数量和本地 revision 记入审计回执。

若本地文档在任务期间发生变化，提案进入 `stale`，禁止静默覆盖。用户只能基于最新版本重新生成，或在可安全重放时显式选择重新计算差异。

### 11.3 AI 文件导入本地脑图

1. 客户端识别 SMM v2、历史 SMM 或现有支持的 XMind/SimpleMind/Markdown/JSON 格式。
2. 导入器完成解析、格式迁移、稳定 UID 校验、大小/深度校验与不受信内容清理。
3. 导入结果必须给出：来源可信度、格式版本、节点数、最大深度、迁移项、被丢弃字段和告警。
4. 用户明确选择：新建本地工作区、替换当前文档、插入选中节点，或另存为云端脑图。
5. 任一必需字段或结构校验失败时，不产生部分文档；保留原文档并提供错误清单。

### 11.4 插入为分支

1. 当前文档必须存在选中节点；导入文档的根节点作为其新子节点。
2. 系统为所有导入节点重新分配 UID，并维护一份旧 UID 到新 UID 的映射。
3. 文档级主题、布局、视图和画布设置沿用当前文档，不覆盖。
4. 节点标签、备注、链接和受支持的扩展字段随分支迁移；无法修复的跨分支引用必须移除并告警。
5. 插入操作必须作为一次原子变更和一条撤销记录提交。

### 11.5 替换当前本地文档

1. 客户端在替换前持久化原文档恢复快照。
2. 对有未保存改动的文档，必须明确提示替换范围和可恢复性。
3. 只有完整新文档通过校验且存储空间足够时才切换；存储失败时当前画布保持不变。
4. 恢复快照至少保留到用户完成下一次成功保存，或按本地保留策略过期。

### 11.6 保存到云端或修改云端脑图

- 另存为新云端脑图：复用现有 `POST /mindmap/import` 语义，携带 artifactId 和幂等键；重复请求只产生一个文件。
- 修改已有云端脑图：必须携带文件权限、`contentRevision`、`roomEpoch`、基线 hash 和 proposalId，通过协同写屏障后一次性提交。
- 服务端提交成功后产生唯一的新 revision，并返回权威快照；客户端不得把本地乐观结果当作最终事实源。
- 任一并发前置条件不成立时返回冲突，不写入部分操作；用户刷新到最新版本后重新生成或重新预览。

### 11.7 多轮调整

1. 用户可以在同一 AI 会话中要求“再精简一层”“补充异常分支”等。
2. 每轮消息创建新的 job 和不可变 artifact/proposal 版本，父子关系可追溯。
3. 后续轮次基于用户明确选中的上一版本，不自动基于最后一次生成结果。
4. 已应用版本不能被后续版本覆盖；每次应用都重新检查基线。
5. 跨 Agent 继续时只传递用户可见消息、安全文档投影和已选 artifact，不传供应商隐藏上下文。

## 12. 提案、差异、应用与撤销

### 12.1 提案结构

每个 proposal 至少包含：

| 字段 | 说明 |
|---|---|
| `proposalId` | 全局唯一、不可变 |
| `jobId` | 来源任务 |
| `proposalType` | `full_document` 或 `patch` |
| `baseDocumentId` | 新建时为空，编辑时必填 |
| `baseRevision/baseHash` | 生成时的文档基线 |
| `scope` | 全文、分支或选中节点 |
| `operations` | 有序结构化操作；新建可为空 |
| `resultArtifactId/resultHash` | 应用后的完整候选结果 |
| `impactSummary` | 新增、修改、移动、删除数量与主要路径 |
| `warnings` | 降级、丢失或需人工判断的内容 |
| `expiresAt` | 提案失效时间 |

操作类型固定为 `create_node`、`update_node`、`move_node`、`delete_subtree` 和 `set_document_meta`。首发不接受供应商自定义操作类型。

### 12.2 差异规则

1. 差异基于稳定 UID 与字段级比较，不基于节点文本猜测身份。
2. 移动与改名分别展示，避免把一次移动渲染成删除再新建。
3. 删除必须展示子树规模；删除节点超过 20 个或占当前文档 10% 以上时标记为高影响。
4. 只展示变化的文档级元数据；视图临时状态不进入差异。
5. 任何无法解释为统一操作合同的变化都使提案无效。

### 12.3 本地原子应用

客户端按以下顺序执行：

1. 校验 proposal 未过期，当前 `documentId/revision/hash` 与基线完全一致。
2. 克隆当前规范化文档，在影子副本执行全部 operations。
3. 对结果运行结构、大小、UID、引用、SMM 版本和业务规则校验。
4. 核对结果 hash 与 proposal 的 `resultHash` 一致。
5. 写入恢复日志并原子替换本地工作区，revision 加一。
6. 记录一条组合撤销项，再异步发送应用回执。

任何一步失败都不得改动画布。应用回执失败不回滚已完成的本地应用，但必须本地排队重试，避免用户重复应用。

### 12.4 云端原子应用

1. 验证用户对目标文件拥有编辑权限。
2. 锁定或建立短时协同写屏障，核对 `contentRevision`、`roomEpoch` 和 baseHash。
3. 在服务端影子副本执行完整提案并运行统一 Validator。
4. 在单次事务中写入文档、revision、操作审计和 proposal 状态。
5. 释放屏障，通过协同通道广播权威 revision。

若事务失败，文档和 proposal 状态同时回滚。若协作者已推进 revision，返回 `AI_PROPOSAL_STALE`，不尝试自动合并删除、移动或语义改写。

### 12.5 撤销

- 本地应用：所有 AI 操作合并为一条撤销记录，撤销后 revision 再递增，不倒退计数器。
- 云端应用：生成反向 proposal，但仅当目标字段仍等于 AI 应用后的值时允许执行；否则提示存在后续协作修改。
- 新建文件或下载文件不需要撤销；删除本地工作区应走现有文件删除与恢复机制。

## 13. 任务与会话生命周期

### 13.1 状态机

主路径为：

`queued → preparing → running → validating → ready → applying → applied`

其他终态或分支状态：

- `needs_input`：缺少生成所需信息；补充后进入新的运行轮次。
- `needs_review`：结构与文件安全有效，但内容仍需人工确认；只允许查看/下载明确标识的草稿和问题清单，不能直接应用。
- `completed_file`：artifact 已生成并至少完成下载或另存，不代表修改了原文档。
- `completed_no_change`：有效完成但没有产生差异。
- `stale`：基线已变化，当前提案不可直接应用。
- `cancel_requested → cancelled`：正在终止供应商执行和本地后处理。
- `failed`：不可自动恢复的失败。
- `expired`：artifact/proposal 超过保留期且未被应用。

任务终态不可重新进入运行态；重试必须创建新 jobId 并记录 `retryOfJobId`。

### 13.2 事件流

1. 每个 job 的事件使用单调递增 `sequence`，事件至少包含时间、统一事件类型和安全摘要。
2. 客户端通过 SSE 订阅；使用 `Last-Event-ID` 断线续传。
3. SSE 只承载状态、阶段、进度区间、token/费用摘要和结果引用，不承载整份脑图。
4. 收到乱序或重复事件时按 sequence 去重；终态之后的供应商迟到事件只进诊断日志。
5. 客户端断线不取消任务；用户显式取消、超时或服务端预算触发才终止。

### 13.3 取消、超时与重试

- `queued/preparing` 可立即取消；`running/validating` 进入 `cancel_requested` 并向 Adapter 传播取消。
- 首发默认软超时 10 分钟、硬超时 15 分钟，管理员可在安全范围内配置。
- 超时后不得把临时草稿标记为正式 artifact；若草稿已通过校验，可作为“未完成草稿”单独冻结并明确标识。
- 供应商瞬时错误最多自动重试两次，只重试未产生可见副作用的调用。
- 用户重试、切换 Agent 或更改参数均创建新任务，防止计费和审计混淆。

### 13.4 幂等性

1. 创建任务、保存云端、应用云端提案必须支持 `Idempotency-Key`。
2. 幂等范围为租户、用户、接口和 24 小时窗口。
3. 相同键与相同请求返回原结果；相同键但请求体不同返回 `IDEMPOTENCY_CONFLICT`。
4. artifact 冻结和 proposal 应用在数据库层具有唯一约束，避免 Worker 重投导致重复结果。

## 14. Agent 选择与运营配置

### 14.1 用户侧选择原则

1. 默认选择自研 MindMap Agent。
2. 只展示当前租户已启用、健康且支持当前意图的 Agent。
3. 展示运行时 Agent 名称、模型信息披露、支持能力、预计耗时/费用级别和数据处理提示。
4. 已选择的 Agent 不可被系统静默替换；不可用时由用户决定等待或切换。
5. 文件内只记录公共 provenance，不记录凭据、内部 endpoint 或供应商 sessionId。

### 14.2 管理员配置

管理员可以：

- 启用、停用和灰度 Agent；
- 配置认证方式、模型白名单、租户范围、区域和网络策略；
- 设置单任务 token、费用、时长、节点与并发上限；
- 查看健康状态、失败率、版本和 conformance 结果；
- 固定 SDK/runtime/model 版本并执行升级回滚；
- 配置 artifact、会话、日志和审计保留时间。

凭据只能保存于服务端密钥系统，前端永远不接收可复用供应商密钥。

### 14.3 限额与费用

1. 创建任务前执行用户、租户和 Adapter 三层限流。
2. Agent 可报告 token 或费用时记录实际值；不可报告时记录估算值和估算版本。
3. 达到软预算时向用户提示并允许取消；达到硬预算时停止后续模型调用。
4. 费用不足或额度耗尽不得自动切换到其他计费主体。

## 15. 数据模型

### 15.1 服务端实体

#### `mindmap_ai_agent_connector`

保存 Adapter 配置元数据：`agentKey`、显示名、adapter/sdk/runtime 版本、能力、状态、租户范围、认证引用、网络策略、预算、最近健康检查与 conformance 结果。密钥值不进入业务表。

#### `mindmap_ai_session`

保存平台会话：用户、租户、当前 Agent、标题、状态、最近 artifact、创建/更新时间。供应商 session/thread 标识加密存放在单独字段，并受短保留期控制。

#### `mindmap_ai_job`

保存任务事实：意图、参数、输入类型、scope、source document/revision/hash、Agent 快照、状态、进度、预算、取消原因、错误码、重试关系和时间戳。

#### `mindmap_ai_artifact`

保存不可变文件结果：SMM 版本、对象存储引用、大小、节点数、深度、hash、来源、Validator 版本、保留期限和下载审计。禁止原地覆盖；修改生成新 artifact。

#### `mindmap_ai_proposal`

保存基线、作用域、operations、resultArtifactId、影响摘要、告警、应用状态、目标文件和过期时间。`jobId + proposalVersion` 唯一。

#### `mindmap_ai_job_event`

保存可重放事件：`jobId`、sequence、统一类型、安全 payload、供应商原始事件摘要和时间。大文本、完整 prompt、完整文档不写普通事件表。

### 15.2 本地工作区 Schema v2

在现有本地工作区 v1 基础上增加：

```json
{
  "schemaVersion": 2,
  "documentId": "local_uuid",
  "revision": 7,
  "documentHash": "mmf2:...",
  "values": {
    "root": {},
    "layout": "logicalStructure",
    "theme": {},
    "view": {},
    "documentData": {}
  },
  "lastAppliedProposal": {
    "proposalId": "...",
    "resultHash": "mmf2:..."
  }
}
```

迁移要求：

1. 首次加载 v1 时生成稳定 `documentId`、revision 0 和规范化 hash。
2. 迁移只新增字段，不改变节点 UID 或视觉数据。
3. 写入 v2 失败时继续使用原 v1，不产生半迁移状态。
4. `lastAppliedProposal` 只用于防重复应用，不作为云端审计事实源。

### 15.3 数据保留

- 未应用 artifact/proposal 默认保留 30 天。
- 已应用 artifact 默认保留 90 天，之后仅保留 hash、来源和审计摘要；合规策略可覆盖。
- 供应商 session/thread 标识默认 30 天，用户删除 AI 会话时进入异步销毁流程。
- 临时任务目录在终态后立即清理，最迟不超过 1 小时。
- 安全审计日志按平台统一策略保留，且不得记录完整脑图正文或供应商密钥。

## 16. 接口设计

### 16.1 查询 Agent

`GET /mindmap/ai/agents?intent={intent}&inputType={inputType}`

返回统一 AgentManifest 的用户可见子集、健康状态、能力、限额和数据处理提示。不得返回密钥引用、内部 endpoint 或供应商会话信息。

### 16.2 创建任务

`POST /mindmap/ai/jobs`

```json
{
  "agentKey": "native_mindmap",
  "intent": "expand",
  "prompt": "补充支付失败与超时分支",
  "parameters": {
    "language": "zh-CN",
    "maxDepth": 5
  },
  "source": {
    "type": "local_snapshot",
    "documentId": "local_uuid",
    "revision": 7,
    "documentHash": "mmf2:...",
    "scope": {"type": "branch", "rootUid": "node_123"},
    "document": {}
  },
  "target": "proposal"
}
```

规则：

- `source.type` 支持 `none`、`local_snapshot`、`cloud_document`、`uploaded_artifact`。
- `target` 支持 `file` 或 `proposal`；编辑已有文档只能是 `proposal`。
- 云端来源只提交 mindmapId 和 revision，由服务端按权限读取，不接受客户端伪造正文。
- 请求正文超过限制返回明确错误，不创建任务。

### 16.3 任务与事件

- `GET /mindmap/ai/jobs/{jobId}`：查询状态、进度、用量、结果和错误。
- `GET /mindmap/ai/jobs/{jobId}/events`：SSE 事件流，支持 `Last-Event-ID`。
- `POST /mindmap/ai/jobs/{jobId}/messages`：创建同会话的新一轮任务，不复活原 job。
- `POST /mindmap/ai/jobs/{jobId}/cancel`：幂等取消。

### 16.4 Artifact

- `GET /mindmap/ai/artifacts/{artifactId}/download`：下载 SMM；使用短时签名或鉴权流。
- `POST /mindmap/ai/artifacts/validate`：上传文件后执行格式迁移与安全校验，返回摘要，不直接保存。
- `POST /mindmap/ai/artifacts/{artifactId}/save-cloud`：另存为新云端脑图，必须有幂等键。

下载响应必须包含安全文件名、内容类型、hash 和禁止 MIME sniffing 的响应头。

### 16.5 本地应用回执

- `POST /mindmap/ai/proposals/{proposalId}/prepare-local-apply`：确认提案有效并返回完整、签名的应用包。
- `POST /mindmap/ai/proposals/{proposalId}/ack-local-apply`：记录成功后的 local revision/resultHash。

`prepare` 不修改本地数据，`ack` 失败不应让客户端重复执行已成功的应用。

### 16.6 云端应用

`POST /mindmap/file/{mindmapId}/ai/proposals/{proposalId}/apply`

请求包含 `contentRevision`、`roomEpoch`、`baseHash` 和幂等键。服务端复用现有批量更新与文档 codec，但必须由 AI 应用事务统一处理，不能让浏览器逐条调用普通节点接口。

### 16.7 管理接口

- `GET /mindmap/ai/admin/connectors`
- `POST /mindmap/ai/admin/connectors/{agentKey}/health-check`
- `PATCH /mindmap/ai/admin/connectors/{agentKey}`
- `POST /mindmap/ai/admin/connectors/{agentKey}/conformance`

所有管理操作进入管理员审计日志；密钥更新采用只写不读模型。

### 16.8 统一错误码

| 错误码 | 含义 | 是否可重试 |
|---|---|---|
| `AI_AGENT_UNAVAILABLE` | Adapter 停用或健康异常 | 可切换或稍后重试 |
| `AI_CAPABILITY_UNSUPPORTED` | Agent 不支持当前意图/输入 | 需修改选择 |
| `AI_INPUT_TOO_LARGE` | 输入超过 AI 任务限制 | 需缩小范围 |
| `AI_BUDGET_EXCEEDED` | token、费用或时长超限 | 需调整预算/范围 |
| `AI_OUTPUT_INVALID` | 输出未通过统一校验 | 可新建任务重试 |
| `AI_PROPOSAL_STALE` | 文档基线已变化 | 需基于最新版本重做 |
| `AI_APPLY_CONFLICT` | 云端协同前置条件失败 | 刷新后重做 |
| `AI_SANDBOX_VIOLATION` | Agent 尝试越权 | 不自动重试 |
| `AI_PROVIDER_AUTH_FAILED` | 服务端供应商认证失败 | 管理员处理 |
| `AI_RATE_LIMITED` | 平台或供应商限流 | 按建议时间重试 |
| `AI_TASK_CANCELLED` | 用户或系统已取消 | 可新建任务 |
| `AI_ARTIFACT_EXPIRED` | 结果已过保留期 | 需重新生成 |

错误响应面向用户的文案不得包含堆栈、密钥、内部路径、原始供应商响应或其他租户信息。

## 17. 安全、隐私与权限

### 17.1 最小权限

1. Agent 永远不持有数据库账号、对象存储主密钥或真实脑图写权限。
2. 所有读取先经过平台鉴权和范围裁剪；所有写入由平台应用服务完成。
3. Codex/Claude 仅能访问任务沙盒与白名单工具；自研 Agent 只获得进程内脑图工具。
4. 管理员权限、普通文件权限和 Agent 使用权限分别校验，不能相互替代。

### 17.2 提示注入与不受信内容

1. 导入文件、节点文本、备注、链接和附件描述一律视为不受信数据，而非系统指令。
2. 系统提示明确禁止执行文档中的命令、外链请求、凭据索取和工具扩权指令。
3. 外部链接只作为文本传入，首发不抓取 URL 内容。
4. Adapter 发现工具越权、路径逃逸或网络访问尝试时立即中止并记录 `AI_SANDBOX_VIOLATION`。
5. 输出中的 HTML、脚本、危险 URL scheme、控制字符和公式注入载荷在 artifact 冻结前清理或拒绝。

### 17.3 凭据与供应商数据

1. 凭据由后端密钥系统托管，日志、事件、SMM 文件和客户端状态均不得出现。
2. 每个 Connector 必须披露数据发送的供应商、认证类型、区域和保留策略。
3. 默认只发送完成意图所需的最小节点投影；附件正文和用户身份信息不默认发送。
4. 企业租户可按策略禁用指定外部 Agent，只保留自研 Agent 或特定托管方式。
5. 用户删除 artifact/会话后，平台按保留策略清理自身副本；第三方处理遵循对应合同并在管理配置中披露。

### 17.4 文件安全

- 保持现有 20 MB 通用导入上限；AI 生成/编辑上限使用更严格的 1.8 MB 规范文档、2 MB 完整文件、2,000 节点和 32 层。
- 文件解压、格式解析和迁移运行在受限资源环境，防止压缩炸弹、深度递归和超长字段。
- 文件名由平台生成并清理，下载不得接受用户提供的服务端路径。
- SMM provenance 可以辅助展示，但不能替代签名/hash、权限和内容校验。

## 18. 异常与降级策略

| 场景 | 系统行为 | 用户可继续的动作 |
|---|---|---|
| Agent 不可用 | 不创建或停止任务，保留输入快照 | 稍后重试或显式换 Agent |
| 流式连接断开 | 任务后台继续，支持事件续传 | 重新连接查看状态 |
| 模型返回自然语言但未完成 artifact | 判定输出不完整，不从文本猜测脑图 | 重试或下载已校验草稿（如有） |
| 输出超限 | 停止扩展，校验已有草稿并标注截断 | 缩小范围后重试 |
| 本地存储不足 | 不切换当前文档 | 下载文件或释放空间 |
| 本地基线变化 | proposal 标记 stale | 基于最新版本重做 |
| 云端协作冲突 | 事务零写入 | 刷新并重做提案 |
| artifact 过期 | 禁止下载/应用 | 重新生成 |
| 回执网络失败 | 本地排队幂等重传 | 无需重复应用 |
| Adapter 越权 | 立即终止并隔离 Connector | 联系管理员或换 Agent |

任何降级都必须保留“原文档不受影响”这一底线。系统不得为了提高成功率而绕过 Validator 或扩大沙盒权限。

## 19. 非功能要求

### 19.1 性能

- 创建任务接口 P95 小于 800 ms，不包含模型执行时间。
- 任务状态事件在服务端产生后 P95 2 秒内到达在线客户端。
- 500 节点 proposal 的本地影子应用与校验 P95 小于 2 秒。
- 2,000 节点 SMM 的服务端校验 P95 小于 5 秒。
- 云端原子应用（不含等待协同屏障）P95 小于 3 秒。

### 19.2 可靠性

- 任务、artifact、proposal 和应用事务均支持 Worker 重启恢复。
- 任务事件至少一次投递，客户端必须去重。
- artifact 写入采用先写对象、校验 hash、再提交数据库引用的顺序。
- AI 应用不得破坏非 AI 的导入、导出、编辑、协同和版本恢复功能。
- 生产月度任务编排可用性目标 99.9%，单个供应商不可用不计为其他 Adapter 不可用。

### 19.3 兼容性

- 保持现有 SMM/JSON/XMind/SimpleMind/Markdown 导入能力和 SMM/JSON/PNG/SVG/PDF/Markdown/XMind/TXT 导出能力。
- 历史 SMM v1 和现有本地工作区 v1 可无损迁移；新字段由旧客户端忽略时不得破坏核心树结构。
- 浏览器刷新、标签页崩溃或短时断网后，可以根据 jobId 恢复任务状态。

### 19.4 可访问性与国际化

- 所有状态、错误、差异数量和高影响警告必须有文本表达，不能只依赖颜色。
- 任务进度变化使用适度的无障碍实时播报，避免逐 token 播报。
- 键盘用户可完成选择 Agent、提交、取消、查看差异、下载和应用。
- 系统文案与生成语言分离；首发支持中文和英文界面文案，脑图内容语言由任务参数控制。

### 19.5 可观测性

统一追踪 `requestId → sessionId → jobId → adapterRunId → artifactId/proposalId → applyRevision`。日志采用结构化字段并脱敏；供应商调用耗时、工具错误、校验失败与取消延迟应可分 Agent/版本/租户聚合。

## 20. 指标与埋点

### 20.1 北极星指标

AI 脑图有效完成率：在任务创建后 24 小时内，用户成功下载、打开本地、应用到本地或保存/应用到云端，且未在 10 分钟内回退该结果的任务占比。

### 20.2 核心指标

- artifact 校验通过率、proposal 可应用率、最终应用率；
- 首次有效结果耗时、各状态停留时长、取消时延；
- 本地 stale 率、云端冲突率、应用零写入保证失败数；
- 每个 Agent/模型/版本的成功率、P50/P95 时长、token 与费用；
- 生成后下载/本地打开/云端保存的去向分布；
- 重试率、跨 Agent 切换率、切换后成功率；
- 旧格式迁移失败率和字段丢失告警率。

### 20.3 关键事件

`ai_mindmap_job_created`、`ai_mindmap_job_started`、`ai_mindmap_needs_input`、`ai_mindmap_artifact_ready`、`ai_mindmap_validation_failed`、`ai_mindmap_downloaded`、`ai_mindmap_local_apply_prepared`、`ai_mindmap_local_applied`、`ai_mindmap_cloud_applied`、`ai_mindmap_apply_stale`、`ai_mindmap_cancelled`、`ai_mindmap_agent_switched`。

事件属性禁止包含 prompt 原文和节点正文，使用长度、数量、意图、版本、状态和错误码等统计字段。

## 21. 验收标准

### 21.1 文件生成与互操作

1. 三种首发 Agent 均能从同一输入生成通过统一 Validator 的 SMM v2 文件。
2. 文件下载后断网导入，节点、层级、标签、备注和受支持文档元数据保持一致。
3. 任意 Agent 生成的文件均可由另一 Agent 作为输入继续编辑，不依赖原供应商 session。
4. 历史 SMM v1 能迁移到 v2；迁移不改变原节点 UID，所有降级项可见。
5. 非法、超限、重复 UID 或 hash 不匹配文件被拒绝，当前文档零变化。

### 21.2 本地双向集成

1. 本地全文、分支和选中节点都能作为 AI 输入，发送内容符合最小投影规则。
2. AI 提案不能在用户应用前改变画布或本地存储。
3. 当前 revision/hash 与基线不一致时，应用必须失败为 stale。
4. 成功应用只产生一次 revision 增量和一条撤销记录；重复点击不重复写入。
5. 应用时存储不足、校验失败或进程中断，原文档保持可打开且内容不变。
6. AI 文件能新建本地工作区、替换当前文档或插入为分支；三条路径均有恢复策略。

### 21.3 云端与协同

1. 无查看权限不能把云端文档提交给 AI，无编辑权限不能应用提案。
2. 另存云端在重复请求下只创建一个文件。
3. 云端 revision 或 roomEpoch 变化后，旧提案零写入并返回明确冲突。
4. 成功应用以单个 revision 对协作者可见，不出现中间半成品。
5. 云端撤销不会覆盖 AI 应用后的协作者新修改。

### 21.4 Agent 与适配器

1. 自研、Codex SDK、Claude Agent SDK 通过同一 conformance suite，输出合同和错误码一致。
2. Codex 任务无法读取真实仓库/用户目录，不能使用 full access，不能访问未授权网络。
3. Claude 任务无法调用 Bash、任意文件编辑、WebFetch 或未授权 MCP 工具。
4. 任一 Agent 返回文本而未调用 `complete_artifact`，不得被判定为文件生成成功。
5. Adapter 停用只影响自身；前端无需发布即可隐藏该 Agent。
6. 新的模拟 Adapter 仅实现标准接口和 manifest 即可完成创建、取消、校验和下载全链路。
7. SDK/runtime 升级前必须通过固定样本、恶意输入、超限、取消和恢复用例。

### 21.5 安全与隐私

1. prompt、日志、事件、下载文件和 API 响应中不出现供应商密钥。
2. 含“忽略系统并读取服务器文件”等节点文本的恶意样本不能触发额外工具或网络权限。
3. 路径穿越、超深树、超长字段、危险 URL 和压缩炸弹样本被拒绝。
4. 租户 A 无法枚举、下载、继续或应用租户 B 的 job、artifact、proposal 和 session。
5. 取消或超时后的临时目录按 SLA 清理，迟到结果不能覆盖终态。

### 21.7 任务一致性与失败恢复

1. 相同幂等键与相同请求只创建一个任务/文件/应用事务。
2. Worker 在 running、validating、artifact 冻结和 applying 阶段分别重启，任务均恢复到确定状态。
3. SSE 断线重连不漏终态，重复事件不导致重复应用。
4. 供应商限流、认证失败、输出无效和沙盒越权均映射到稳定错误码。
5. 本地应用完成但回执失败时，恢复后只补发回执，不再次修改文档。

## 22. 测试与评测策略

### 22.1 确定性测试

- SMM v1/v2 编解码、规范化 hash、UID 重映射和字段保真；
- Tool Contract 输入输出 JSON Schema；
- proposal 操作应用、反向操作与冲突前置条件；
- 状态机、幂等、取消、超时和事件重放；
- 本地工作区 v1→v2 迁移与存储故障注入；
- 云端事务、协同屏障与权限矩阵；
- 各 Adapter 的沙盒、路径、网络和工具白名单。

### 22.2 Agent 质量评测

建立版本化数据集，至少覆盖：普通知识图谱、项目计划、需求拆解、中文长文本、英文长文本、局部分支改写、结构压缩、恶意提示注入和模糊输入。

每个样本评估：格式有效性、结构完整性、需求覆盖、重复节点、深度合理性、标签正确性、引用完整性和人工可用性。格式与安全为硬门槛，内容质量采用盲评和规则结合。

### 22.3 Adapter Conformance Suite

所有生产 Adapter 必须通过同一套黑盒合同测试：

1. capability 发现与不支持能力拒绝；
2. 创建、流式事件、需要补充信息、取消、超时与恢复；
3. 工具调用参数校验、未知工具拒绝、重复调用幂等；
4. artifact 冻结、hash、下载和跨 Adapter 复用；
5. 超节点/深度/字段、恶意内容和路径逃逸；
6. 供应商错误映射、用量映射和审计字段完整性；
7. session/thread 隔离、加密存储与过期清理。

## 23. 里程碑与交付顺序

### M0：文件底座

- SMM v2、规范化 hash、legacy migration；
- 统一 Validator、artifact 存储和下载；
- 本地工作区 v2 与导入三种目标模式；
- Tool Contract 与无模型模拟 Adapter。

退出条件：确定性文件与本地原子应用验收全部通过。

### M1：自研 MindMap Agent

- Agno 独立会话与 prompt 版本；
- 新建、扩展、改写、压缩、重组；
- 任务状态、SSE、取消、预算、提案预览和本地应用；

退出条件：质量评测达到门槛，且不依赖 Codex/Claude 即可完成核心闭环。

### M2：Codex 与 Claude Adapter

- `openai-codex` 与 `claude-agent-sdk` 隔离 Worker；
- SDK 会话恢复、结构化结果、取消和用量映射；
- 沙盒、网络、权限与 conformance suite；
- Agent 选择和管理员配置。

退出条件：两种 Adapter 分别通过功能、安全和故障注入验收。

### M3：云端与协同闭环

- 云端来源读取、另存为新文件；
- proposal 服务端原子应用、协同屏障、权威广播与条件撤销；
- 租户灰度、运营指标和应急停用。

退出条件：并发、权限、幂等和回滚门槛全部通过后才可正式发布。

M0～M3 均属于首个正式版本范围，可以按阶段内测，但不得将缺少文件互操作、本地双向集成或三类 Agent 的版本标记为本 PRD 完成。

## 24. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| SDK/runtime 快速变化 | Adapter 行为不稳定 | 固定版本、manifest 留痕、升级前 conformance 与灰度 |
| 模型生成合法但低质量结构 | 用户需要大量返工 | 意图模板、评测集、影响摘要、多轮提案，不自动应用 |
| 本地与云端双写语义混淆 | 重复或丢失数据 | 区分 artifact、local ack、cloud transaction 三类事实 |
| AI 长任务遭刷新/断网 | 用户误以为失败 | 服务端任务、SSE 重放、jobId 恢复 |
| 协作期间提案过期 | 覆盖他人修改 | revision/hash/roomEpoch 三重前置条件，冲突零写入 |
| 外部文件提示注入 | 越权访问或泄漏 | 不受信投影、工具白名单、无外链抓取、强沙盒 |
| 多 Agent 能力漂移 | 同一功能体验不一致 | 平台能力协商、统一合同、固定验收与禁止静默切换 |
| artifact 体积与费用失控 | 性能/成本不可控 | AI 专属上限、分批工具、软硬预算与限流 |
| 旧格式字段丢失 | 用户资产受损 | 迁移报告、未知扩展保留、原文件不覆盖 |

## 25. 发布门槛

以下条件必须全部满足：

1. SMM v2 规范、Tool Contract、Adapter interface 和错误码冻结并版本化。
2. 自研、Codex、Claude 三类 Agent 均通过 conformance、安全和固定质量评测。
3. AI 生成文件可下载、离线导入并由任意另一 Agent 继续编辑。
4. 本地提案应用具备 shadow apply、hash 校验、单步撤销和故障零变化。
5. 云端应用具备权限、revision/hash/roomEpoch 校验、单事务写入和协作冲突零写入。
6. 生产环境禁止 Codex full access；Claude 禁止 Bash、任意文件、WebFetch 和未授权 MCP。
7. 任务取消、超时、Worker 重启、SSE 续传、幂等和临时目录清理均通过故障注入。
8. 监控可按 Agent/SDK/runtime/model 版本定位成功率、延迟、费用与错误。
9. 安全评审、隐私披露、供应商认证方式和租户灰度/回滚方案完成签字。

任何一项未满足，只能作为受限内测，不得全量发布。

## 26. 已确定的产品决策

1. 产品能力以 SMM artifact 和 proposal 为中心，不以某一家模型会话为中心。
2. 自研 MindMap Agent 是默认 Agent；Codex 与 Claude 是同级可选 Adapter，不是兜底链路。
3. 用户选择的 Agent 不静默切换，失败重试创建新任务。
4. AI 永不直接修改画布、localStorage、云端数据库或真实文件系统。
5. 本地集成与云端集成使用不同提交机制，但共享同一文档格式、Validator 和 proposal 语义。
6. 首发不做任意网页抓取、附件理解、多人同时编辑同一 AI 草稿或跨 Agent 隐藏上下文迁移。
7. 官方“Claude Code SDK”已更名为“Claude Agent SDK”；产品文案首次出现保留旧称说明，技术实现统一使用新名称。
8. SDK 具体版本不在 PRD 中长期硬编码；实现阶段写入依赖锁、AgentManifest 与升级矩阵。

## 27. 参考资料与实现依据

### 27.1 当前代码基线

- `ruoyi-fastapi-frontend/src/components/MindMap/Import.vue`
- `ruoyi-fastapi-frontend/src/components/MindMap/Export.vue`
- `ruoyi-fastapi-frontend/src/components/MindMap/config/index.js`
- `ruoyi-fastapi-frontend/src/utils/mindmap-import-validation.js`
- `ruoyi-fastapi-frontend/src/utils/mindmap-local-workspace.js`
- `ruoyi-fastapi-backend/module_mindmap/controller/mindmap_controller.py`
- `ruoyi-fastapi-backend/module_mindmap/service/simple_mind_document_codec.py`
- `ruoyi-fastapi-backend/module_mindmap/entity/vo/mindmap_vo.py`
- `ruoyi-fastapi-backend/module_ai/`
- `ruoyi-fastapi-backend/utils/ai_util.py`
- `ruoyi-fastapi-backend/requirements.txt`

### 27.2 官方 SDK 资料（核对日期：2026-09-10）

- OpenAI Codex SDK：<https://learn.chatgpt.com/docs/codex-sdk>
- OpenAI Codex App Server：<https://developers.openai.com/codex/app-server/>
- Anthropic Claude Agent SDK Overview：<https://code.claude.com/docs/en/agent-sdk/overview>
- Claude Agent SDK Python：<https://code.claude.com/docs/en/agent-sdk/python>
- Claude Agent SDK Structured Outputs：<https://code.claude.com/docs/en/agent-sdk/structured-outputs>
- Claude Agent SDK Permissions：<https://code.claude.com/docs/en/agent-sdk/permissions>
- Claude Agent SDK Secure Deployment：<https://code.claude.com/docs/en/agent-sdk/secure-deployment>
- Claude Agent SDK Session Storage：<https://code.claude.com/docs/en/agent-sdk/session-storage>
- Claude Agent SDK Migration Guide：<https://code.claude.com/docs/en/agent-sdk/migration-guide>

以上资料用于确定 SDK 名称、语言/运行时、会话、权限、沙盒和结构化输出边界；实际开发必须再次核对官方最新版，并把最终版本写入依赖锁与 AgentManifest。
