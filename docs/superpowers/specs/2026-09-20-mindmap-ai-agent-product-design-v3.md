# AI 脑图 Agent V3：SDK、Skills 与插件扩展平台

日期：2026-09-21
文档定位：V3 独立产品设计文档
适用范围：项目自定义 Agent、Codex SDK、Claude SDK 的统一运行时，以及 Skills、插件、MCP 和 Trusted Runtime Plugin 能力。

本文件是对 [V2 基础产品与交互设计](./2026-09-20-mindmap-ai-agent-product-design.md) 的独立扩展设计。V2 负责脑图实时编辑、任务状态、变更组、检查点、恢复、撤销和协作语义；V3 负责 Agent 能力如何被发现、组合、授权、运行、隔离和审计。V3 不改变 V2 的画布结果、操作提交、审批和撤销语义。

## 1. V3 产品目标

V3 要让三个 Agent 使用同一套脑图任务协议，同时允许每个 Agent 通过受控 Skills、MCP 和插件获得不同的专业能力。用户看到的是同一套脑图协作体验，平台负责处理 SDK、模型、工具、扩展和数据边界的差异。

V3 的核心原则：

- Agent Adapter 只连接具体 SDK 或 Agent Harness，不能各自实现任务状态、撤销和恢复。
- Skill 提供工作方法和参考资料，不因为被加载就获得工具权限。
- Tool/MCP 提供可执行能力，必须经过 Agent Profile、文档权限和风险策略过滤。
- Plugin 负责分发和配置；需要服务端代码的能力必须进入 Trusted Runtime Plugin。
- 本轮运行开始后固化能力快照；扩展变化在新的 runEpoch 中生效。
- 扩展不可用时保留已经提交的脑图结果，向用户说明影响并提供可行动的恢复路径。

## 2. 当前三个 Agent 的定位

当前系统有三个 Agent 入口，但它们是三种运行时适配器，不应让用户承担三套不同的脑图交互：

| Agent | 当前 SDK/运行方式 | 已有能力基线 | 产品定位 | 扩展边界 |
| --- | --- | --- | --- | --- |
| 项目自定义 Agent | Agno + 项目自研脑图工具 | 实时流式、结构化输出、脑图工具约束；当前不依赖供应商会话 | 默认的实时脑图编辑 Agent，优先承担低风险 R1 操作 | 共享 Skills、受控 MCP；不能通过 Skill 绕过脑图工具契约 |
| Codex SDK | OpenAI Codex SDK/受限 Worker | 会话恢复、实时流式、工具调用、独立会话快照 | 长任务、复杂整理、需要更强规划和外部工具时使用 | 通过统一 Agent SDK 和受限 MCP Bridge 接入；不能直接覆盖脑图文档 |
| Claude SDK | Claude Agent SDK/受限本地运行 | 会话恢复、实时流式、工具调用、结构化结果 | 多步骤分析、资料理解和复杂重组 | 仅暴露项目允许的脑图 MCP 工具；内置文件、Shell 和网络能力默认关闭 |

三种 Agent 都必须遵守相同的 `AgentRunContext`、脑图工具契约、权限范围、风险审批、事件协议和变更组规则。用户选择 Agent 只改变模型、会话、工具实现和能力标签，不改变画布结果语义、撤销语义或安全边界。

每个 Agent 的清单需要公开声明：`agentKey`、Adapter/SDK 版本、模型、会话、流式、取消、结构化输出、Skills、Plugins、MCP、后台恢复、沙箱、网络、数据区域、认证方式、支持的意图和输入类型。当前自研 Agent 的 `supports_sessions=false` 必须在任务中心显示为“由平台检查点恢复”；Codex 和 Claude 的供应商会话不能替代平台任务检查点。

## 3. 统一 Agent SDK 运行时

三种 Agent 共享一个平台级 SDK，Adapter 只负责连接具体模型或 Agent Harness，不能各自实现一套任务、工具、Skills、撤销和恢复逻辑。核心接口如下：

| SDK 能力 | 责任 | 统一要求 |
| --- | --- | --- |
| `AgentAdapter` | 启动、继续、流式运行、暂停、取消、健康检查、清理供应商会话 | 适配 Native、Codex、Claude，但不能绕过平台任务状态机 |
| `AgentManifest` | 声明 SDK、模型、版本和能力 | 能力不足时返回 `AI_CAPABILITY_UNSUPPORTED`，不能静默降级 |
| `AgentRunContext` | 提供文档、版本、选区、权限、来源、预算和任务 ID | 每个 Agent 使用同一份上下文快照 |
| `ToolRegistry` | 注册受控脑图工具和 MCP 工具 | 工具按任务和 Agent 能力过滤，服务端再次鉴权 |
| `SkillRegistry` | 发现、解析、加载和锁定 Skills | 只提供指令和参考资料，不授予工具权限 |
| `PluginRegistry` | 安装、校验、启用、停用、更新和回滚插件 | 插件状态变化不影响正在运行的任务 |
| `CapabilityPolicy` | 合并用户、文档、Agent、插件和工具权限 | 采用最小权限，任何一层拒绝都不能被 Agent 覆盖 |
| `SessionStore` | 保存供应商会话和平台检查点 | 供应商会话是可选优化，平台检查点是恢复事实来源 |
| `EventBus` | 发布状态、文本、工具、提案、提交和终态事件 | 统一 `sequence`、`runEpoch`、重连和幂等规则 |
| `ApprovalBroker` | 处理 R2/R3 操作、插件安装、凭据和外部副作用审批 | 审批凭证绑定任务、操作摘要、文档修订和过期时间 |

平台执行顺序固定为：**选择 Agent → 读取 Agent Manifest → 解析插件和 Skills → 合并工具与权限 → 固化本轮扩展快照 → 创建检查点 → 启动 Agent Run**。运行中不能悄悄改变工具、Skills 或插件集合；用户选择切换 Agent 或启用扩展时，必须创建新的 `runEpoch`，重新做能力校验并记录差异。

Agent Adapter 不直接写入脑图。所有三种 Agent 都只能调用 `MindmapToolService` 或经过服务端校验的 MCP Bridge，最终由平台的 `commit_operations` 提交语义操作。这样 Native 的直接工具、Codex 的 Worker 工具和 Claude 的 MCP 工具会收敛到相同的文档版本、风险审批和撤销机制。

## 4. 插件、Skills 和工具的职责划分

| 扩展类型 | 内容 | 是否可以增加工具 | 是否可以修改脑图 | 适用场景 |
| --- | --- | --- | --- | --- |
| Skill | `SKILL.md` 指令、参考资料、模板和示例 | 否 | 否，必须调用已有工具 | 测试用例设计方法、需求分析流程、脑图整理规范 |
| MCP Plugin | `plugin.json`、`skills/`、`mcp.json` 和外部 MCP Server | 是，受工具策略控制 | 只能通过受控工具和审批 | Jira、GitHub、测试平台、知识库、数据查询 |
| Trusted Runtime Plugin | 服务端审核的 Adapter、Hook、Provider 或 UI 扩展 | 是 | 由平台接口控制 | 新 Agent SDK、企业内部连接器、审计和计费 |
| Agent Profile | Agent、模型、工具、Skills、预算和安全策略的组合 | 使用已有能力 | 由授权策略决定 | 测试负责人、研究、产品规划等工作模式 |

普通用户可安装的插件只允许携带 Skills 和 MCP 配置，不能直接加载任意 Python/Node 模块到 Web 或 Agent 进程。需要原生运行时代码的插件必须由服务端审核、签名和发布，作为 Trusted Runtime Plugin 安装。这样可以避免“安装一个 SKILL.md 就获得文件、网络或删除脑图权限”。

Skill 只描述“如何完成工作”，Tool/MCP 才提供“能做什么”，Plugin 负责“如何分发和配置”，Agent Adapter 负责“由哪个 SDK 执行”。四者不能混用：Skill 的可见性不等于工具权限，插件启用不等于允许所有工具，Agent 可用不等于可以修改所有文档。

## 5. 可移植插件包格式

优先采用 Agent Plugins 1.0 作为跨 Agent 的最小兼容层：

```text
mindmap-test-plugin/
├── plugin.json                 # 必需：名称、版本、描述、Schema
├── skills/
│   └── test-case-coverage/
│       ├── SKILL.md            # 必需：name、description
│       ├── references/          # 按需加载的资料
│       ├── templates/           # 输出模板
│       └── assets/              # 可选资源
├── mcp.json                    # 可选：stdio 或 streamable-http MCP Server
└── com.ruoyi.mindmap/          # 可选：本产品命名空间下的扩展数据
```

`plugin.json` 至少包含 `$schema`、`name`、`version`、`description`，使用 SemVer。`skills/` 和 `mcp.json` 使用固定位置，不能通过插件内容随意改变发现路径。插件客户端不支持的组件必须忽略，不得阻断同一插件中其他合法 Skills 的加载。

`SKILL.md` 采用 Agent Skills 兼容格式，至少包含 `name` 和 `description`。元数据先进入 Skill 索引；只有触发 Skill 后才加载正文，正文引用的资料、模板和脚本继续按需加载。Skill 正文不得自动注入隐藏系统指令，也不得包含绕过平台权限的操作。

本产品的命名空间扩展只用于记录 Agent 能力映射、脑图工具契约版本和 UI 元数据；不能把 Native、Codex 或 Claude 的私有配置伪装成可移植能力。适配器私有配置分别放在 `extensions` 的反向域名命名空间下，其他 Agent 必须忽略。

## 6. Skills 生命周期和能力解析

Skills 来源按优先级解析：当前工作区/项目、当前脑图、用户目录、组织托管、系统内置、插件内置。相同 `name` 冲突时采用确定性优先级，同时在任务详情显示被覆盖的版本、来源和哈希；用户可以锁定某个版本，不能让更新中的 Skill 覆盖正在执行的任务。

Skills 生命周期为：**发现 → Schema 校验 → 安全扫描 → 依赖检查 → 用户启用 → 运行快照 → 使用 → 版本检查 → 更新/回滚/停用**。外部安装的 Skill 默认不启用；安装时显示来源、版本、权限、依赖、是否包含脚本、是否需要网络和凭据。用户没有确认时，Agent 只能说明缺少能力，不能自行安装或启用。

Skill 支持三种触发方式：用户显式输入 `/skill-name` 或 `@skill-name`、用户从扩展面板选择、Agent 根据 Skill 的 `description` 自动匹配。自动匹配必须通过当前 Agent Profile 的允许列表和文档权限；只匹配到 Skill 不代表可以调用 Skill 依赖的工具。

Agent 可以根据成功任务提出“生成 Skill”建议，但新 Skill 只能进入草稿区，必须经过安全扫描、用户审阅和显式启用才能进入生产 Skill 集合。自动生成 Skill 不得自动修改系统级 Skill、不得读取其他用户会话、不得把密钥或完整脑图内容写入 Skill。

本轮任务固化 `skillId`、版本、内容哈希、来源、所需工具和能力状态。插件或 Skill 在运行中失效时，任务进入 `extension_unavailable` 或 `agent_unavailable`，保留已有结果；不能用更新后的 Skill 继续同一运行世代。

## 7. 插件安装、工具策略和安全隔离

插件来源支持系统内置、组织目录、Git URL、压缩包和受信任注册表。安装流程必须先下载到隔离目录，再完成 Manifest Schema 校验、路径穿越检查、哈希/签名校验、依赖检查、Skills 安全扫描和 MCP 配置检查；校验失败的组件隔离失败，不能阻止其他合法插件继续显示。

插件默认状态为“已安装但未启用”。启用时向用户展示：新增工具、Skills、MCP Server、网络域名、文件目录、环境变量、数据去向、费用和审批级别。MCP Server 的 `stdio` 进程只接收声明的最小环境变量，禁止继承完整用户环境；远程 MCP 使用明确的 URL、认证方式和域名策略。

每个 Agent Profile 使用独立的工具 allowlist/denylist，并为每个工具声明 `read`、`write`、`external_side_effect`、`requires_approval`、`supports_parallel` 和 `data_scope`。只读工具可以并行；涉及共享文档、删除、移动、外部写入的工具默认禁止并行。工具错误、凭据错误、MCP 断线和 Skill 不满足依赖分别映射为 `AI_PLUGIN_INVALID`、`AI_PLUGIN_UNTRUSTED`、`AI_SKILL_UNAVAILABLE`、`AI_MCP_UNAVAILABLE` 或 `AI_CAPABILITY_UNSUPPORTED`。

Trusted Runtime Plugin 的 Hook 只允许订阅 `before_run`、`after_tool`、`after_commit`、`on_error` 等平台事件。Hook 默认只读、受超时和资源预算限制；需要改变脑图时必须重新生成受控操作并经过同一套版本、风险和审批校验，不能在 Hook 中直接写数据库或绕过 `commit_operations`。可移植 Agent Plugin 不携带这类运行时 Hook。

插件、Skill 和 MCP 的安装、启用、停用、更新、回滚、工具调用和凭据变更都写入审计日志。卸载插件前要检查是否有运行中的任务、历史轮次或检查点引用它；有引用时保留不可执行的历史快照，不能让历史任务详情失真。

## 8. 用户侧 Agent 与扩展交互

- 高级设置中的 Agent 选择器展示项目自定义 Agent、Codex SDK、Claude SDK，并显示流式、会话恢复、取消、Skills、MCP、后台运行和网络范围等能力标签。标签来自服务端 AgentManifest。
- 默认选择项目自定义 Agent。用户切换 Agent 时先展示能力差异和数据去向；能力不足时说明缺少或替代的动作，不能静默降级。
- 扩展能力区域展示本轮实际启用的 Skills、MCP Server 和插件，显示名称、来源、版本、内容哈希、工具、网络/文件范围、数据去向和审批级别。
- 用户启用、安装、更新、停用扩展或切换 Agent 后创建新的 `runEpoch`；当前运行继续使用旧能力快照，下一安全边界再提示是否基于新能力继续。
- 缺少 Skill、插件或 MCP 时，面板展示缺失能力、影响范围和“安装/启用”“改用其他 Agent”“继续只读分析”等动作。Agent 不能通过对话暗中安装或启用扩展。



## 9. 与任务运行协议的衔接

V3 沿用 V2 的任务、变更组、检查点、`runEpoch`、版本校验和撤销语义，只增加扩展能力的状态与事件：

| 用户态 | 服务端状态 | 面板动作 |
| --- | --- | --- |
| 扩展已解析 | `extension_resolved` | 查看本轮能力快照 |
| Skill 已加载 | `skill_loaded` | 查看 Skill 来源、版本和工具依赖 |
| MCP 已连接 | `mcp_connected` | 查看连接状态和数据范围 |
| 扩展不可用 | `extension_unavailable` | 重试、启用替代扩展、继续只读或结束 |

扩展事件必须携带 sessionId、documentId、turnId、runEpoch、sequence、扩展 ID、版本、内容哈希、来源、能力范围和错误码。运行中更新、停用或失效的扩展不能改变当前任务的能力快照；切换扩展必须创建新的 runEpoch。

当前三个适配器兼容使用 `AI_AGENT_UNAVAILABLE` 表示 SDK、供应商网络、会话快照或隔离进程异常。V3 保留该错误码作为对外兼容码，同时要求返回 failureDomain、retryable、lastSafeRevision 和 fallbackAllowed。前端根据故障域显示“重试 Agent”“修复扩展”“重新认证”或“切换 Agent”，不能仅根据错误文案静默切换执行者。

统一 AgentManifest 在现有字段上增加 supports_skills、supports_plugins、supports_mcp、skill_spec_versions、plugin_spec_versions、tool_namespaces 和 extension_policy。Manifest 只描述能力，不授予权限；最终可用能力仍由 CapabilityPolicy 按用户、文档、组织和任务范围求交集得到。


## 10. 指标与验收

### 产品指标

- 三个 Agent 在同一任务集上的结果语义一致率、能力清单准确率、扩展快照一致率、插件启用后首个工具调用成功率和扩展故障隔离成功率。
- Skill 自动匹配误触发率、未授权工具调用次数、插件安装失败后的越权调用次数、MCP 断线后的错误写入次数，均应为 0。
- 高风险操作审批拒绝后的越权写入次数、停止后迟到提交次数、任务接管后的重复提交次数，三项必须为 0。

### V3 必须通过的验收情境

1. 三个 Agent 对同一个低风险补充任务使用相同的 AgentRunContext 和 commit_operations 语义，不能产生不同的撤销、版本或权限结果。
2. 插件包含 SKILL.md 和 MCP 配置时，安装后保持未启用；用户启用后先看到来源、工具、网络和数据范围，Skill 元数据先加载，正文按触发加载。
3. 运行中更新或停用扩展时，当前任务继续使用原能力快照；切换扩展后产生新的 runEpoch，旧事件不被新能力重放。
4. Skill 安全扫描发现提示注入、危险脚本或越权依赖时进入 extension_unavailable，已提交脑图结果保持可见。
5. MCP 连接断开、凭据过期或工具不满足 Agent Profile 时，面板显示具体扩展和影响范围，不静默调用未声明的替代工具。
6. 切换项目自定义 Agent、Codex 或 Claude 时，系统展示数据去向和能力差异，重新解析插件、Skills 和工具权限，并记录执行者变化。
7. 脑图附件或 Skill 正文包含越权指令时，只作为待分析内容，不能改变任务范围、审批级别或工具 allowlist。


## 11. 分期决策

**V3-P0：能力可见。** 三种 Agent 统一返回 Manifest，任务详情显示当前 Agent 和本轮能力快照；只接入内置 Skills，不开放任意第三方插件。

**V3-P0.5：受控扩展。** 提供组织托管 Skills、项目审核过的 MCP、扩展不可用处理、安装/启用确认、安全扫描、最小环境和审计日志。

**V3-P1：成熟扩展平台。** 提供 Agent Profile、插件/Skills/MCP 安装启停、版本锁定、回滚、Trusted Runtime Plugin、Hook、任务评测和多 Agent 切换。

**V3-P2：生态能力。** 提供受控组织/社区插件目录、Skill 草稿生成与评审、多文档引用、资料检索和后台并行任务。所有扩展继续沿用 V2 的会话、权限、工具和变更模型。


## 12. 参考依据

本 V3 文档参考以下开源 Agent 的能力组织方式，并将其收敛为本项目的安全契约：

- [V2 基础产品与交互设计](./2026-09-20-mindmap-ai-agent-product-design.md)
- [NousResearch Hermes Agent](https://github.com/NousResearch/hermes-agent)
- [OpenClaw](https://github.com/openclaw/openclaw)
- [OpenClaw Tools](https://github.com/openclaw/openclaw/blob/main/docs/tools/index.md)
- [OpenClaw Skills](https://github.com/openclaw/openclaw/blob/main/docs/tools/skills.md)
- [OpenClaw Plugin Manifest](https://github.com/openclaw/openclaw/blob/main/docs/plugins/manifest.md)
- [Agent Plugins Specification 1.0](https://github.com/agentplugins/agent-plugins-spec/blob/main/spec/1.0.0.md)
- [Agent Skills Specification](https://agentskills.io/specification)
- [OpenAI Skills](https://github.com/openai/skills)
