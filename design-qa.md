# AI 脑图设计 QA

日期：2026-09-15

## 对照证据

- 参考状态：XMind AI 新对话首页，1512×739，见 `.doc/designs/xmind-ai-audit-2026-09-14/01-ai-home.png`。
- 实现状态：本地 AI 新对话首页，见 `.doc/designs/xmind-ai-audit-2026-09-14/10-local-xmind-style-home.png`；同宽裁剪版本为 `10-local-xmind-style-home-1512x739.png`。
- 过程状态：`12-local-realtime-generation.png`。
- 应用状态：`14-local-cloud-applied.png` 和 `15-local-editor-after-apply.png`。
- 新建脑图结果状态：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-06-result-actions-polished.png`。
- 协作冲突覆盖确认：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-10-force-overwrite-confirm-final.png`。
- 覆盖完成状态：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-11-force-overwrite-applied.png`。
- Native Agent 工作台与左侧交互记录：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-12-native-start.png`。
- Native 首节点等待反馈：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-17-native-understanding.png` 和 `ai-mindmap-audit-18-native-structuring.png`。
- Native 实时草稿与最终结果：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-19-native-live-draft.png` 和 `ai-mindmap-audit-20-native-ready.png`。
- Native 连续任务保温结果：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-21-native-second-task.png`。
- 云端提案确认即覆盖结果态：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-23-direct-overwrite.png`。
- 输出语言与目标布局设置：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-26-output-language-layout.jpg`。
- English 鱼骨图最终结果：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-28-english-fishbone-fit.jpg`。
- Claude 连接就绪卡：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-30-agent-readiness.png`。
- Claude、Codex 与 MindMap Agent 同时可选：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-31-both-sdk-agents-ready.png`。
- 过期健康状态降级与首次连接说明：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-33-stale-health-visible.png`。
- 当前 XMind AI 工作区：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-34-xmind-current-workspace.png`。
- 本地应用后差异展开旧状态：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-35-local-applied-diff-expanded.png`。
- 本地应用后差异折叠新状态：`/Users/liushuisong/.codex/visualizations/2026/09/09/01a085d5-4676-7743-b463-5d85a8f194e4/ai-mindmap-audit-36-local-applied-diff-collapsed.png`。

## 视觉检查

- 通过：左侧工作台宽度、浅灰背景、顶部新对话、四张模板卡、底部输入器与右侧脑图的主布局和参考产品一致。
- 通过：AI 强调色、圆角、弱边框、留白、卡片密度和状态层级形成统一视觉系统。
- 通过：结果态没有创建第二个编辑器；右侧始终是唯一实时脑图舞台。
- 通过：窄屏、减弱动效、滚动容器和长会话折叠规则已覆盖。

## 交互检查

- P0 已修复：应用事务回滚后访问过期 ORM 数据导致服务端 500。
- P1 已修复：AI 抽屉层级低于编辑器工具栏，顶部操作发生点击穿透。
- P1 已修复：应用操作和差异确认在视觉上分离，用户可能跳过审阅。
- P1 已修复：生成过程不可见；现在会话事件和脑图变化版本实时更新。
- P1 已修复：任务、来源或讨论模式变化会静默替换用户已选 Agent；现在保留选择、明确提示不可用原因，并在不兼容时阻止提交。
- P1 已修复：新建脑图结果的“打开/另存”动作被原生 `template` 隐藏；现在结果可直接下载、打开为本地脑图或保存为云端脑图。
- P1 已修复：协作版本变化后只能刷新并重新生成提案；现在差异确认本身就是整图覆盖授权，第一次请求直接以最新正文为撤销基线覆盖，不再先失败一次或重复确认，并直接重载为可编辑的权威画布。
- P1 已修复：浏览器遗留的普通应用冲突记录会拦截新版覆盖请求；现在用户再次确认覆盖后，同一冻结基线的确定性版本冲突记录会原子升级为覆盖请求，结果未知、已确认或完整性失败的记录仍保持失败关闭。
- P1 已修复：覆盖已在服务端提交，但前端恢复层仍保护旧 revision、长期显示“权威画布尚未同步”；现在覆盖意图贯穿持久恢复记录和编辑器，自动作废旧写入并完成协作重连。
- P1 已修复：Native Agent 对 `@root` 报参数错后重复调用，且服务恢复时再次创建已存在草稿；现在提供跨轮次引用解析、恢复态工具集、可操作脱敏错误和有限重试熔断。
- P1 已修复：本机模型首轮推理期间只有静态占位，用户容易误判为卡死并重复提交；现在显示阶段、已等待秒数与首次加载预期，首个节点出现后自动切换为实时脑图。
- P1 已修复：每个 Native 任务都可能重新加载 Ollama 模型；现在默认保温 30 分钟并尊重管理员自定义值，连续 4 节点任务首个可见 Agent 事件约 4 秒、总耗时约 15 秒。
- P1 已修复：输出语言写死为中文、目标布局无法选择且三类 Agent 不保证执行；现在用户可配置语言与六类布局，参数可恢复/重试，三类 Agent 共享契约，整图 Artifact 冻结前确定性校正布局，局部编辑与自动标记保持原布局。
- P1 已修复：Agent 虽可选择，但历史健康检查被无限期展示为“连接正常”，首次连接阶段又只有发送按钮旋转；现在健康结果有 15 分钟有效期，过期后明确提示运行前检查，提交等待持续显示阶段和秒数。
- P1 已修复：提案应用或撤销后仍长期展开历史差异并保留覆盖确认，挤压回执和继续对话；现在终态默认收起差异、移除已失效确认，可按需展开审计内容，继续调整输入器回到主操作路径。
- P2 已修复：SDK、认证和使用边界挤在 66px 内部滚动区；现在连接就绪度始终可见，详细治理信息按需展开。
- P2 已修复：旧弹窗信息密度过高；设置收纳为高级区，常用输入器固定在底部。
- P2 已修复：Agent 过程过长；默认保留首条用户要求与最近 12 条事件，可展开全部。

## 验证

- 前端脑图测试：1117/1117 通过。
- 前端生产构建：通过。
- 后端云端应用目标测试：37/37 通过。
- 后端 AI 与 Agent 完整测试：676/676 通过。
- Native Adapter 定向测试：213/213 通过，Ruff 通过。
- 后端 Ruff：通过。
- 本地真实生成：79 节点，结构校验通过。
- Native 1.12.0 真实重试：相同“API 发布检查”请求生成 4 节点 Artifact，单次新增 3 个一级节点，无工具失败且不修改当前脑图。
- Native 首节点反馈真实验收：1 秒显示理解阶段，16 秒显示本机模型阶段，约 32 秒出现 5 节点实时草稿，最终扩展为 9 节点并通过校验。
- Native 保温连续验收：第二个 4 节点任务约 4 秒出现 Agent/工具事件、约 15 秒进入 `ready`。
- 直接覆盖结果态验收：79 节点云端 Proposal 显示明确覆盖授权和“覆盖当前脑图”主按钮，确认闸门有效；本轮未执行最终写入。
- 输出参数与 Agent 契约定向回归：305/305 通过，Ruff 通过；非默认 English + 鱼骨图真实任务生成 17 个英文节点并完成实时预览，未写入当前脑图。
- 后端 AI 参数、任务、提案与 Agent 相关回归：473/473 通过。
- 本地真实应用：`#130` 已覆盖到 revision 105、79 节点；AI 任务显示已应用，编辑器完成权威版本重载、协作在线并提供撤销。

final result: passed
