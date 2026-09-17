# AI 脑图 Agent Adapter 接入指南

AI 脑图平台通过 Python entry point 发现由服务端管理员安装的扩展。租户和普通用户不能上传或执行 Adapter 代码；前端只消费服务端返回的 manifest，因此新增 Agent 不需要修改编辑器。

内置实现包含三种等价接入：产品自研 `MindMap Agent`（Agno 模型基础设施）、官方 `openai-codex` Python SDK，以及 Claude Code SDK 的现名称 `claude-agent-sdk`。三者都只能通过同一套内存脑图工具生成候选结果，不能直接写数据库或覆盖用户脑图。

## 扩展点

扩展包在 `pyproject.toml` 声明：

```toml
[project.entry-points."ruoyi.mindmap_agent_adapters"]
my_agent = "my_agent.adapter:MyMindmapAdapter"
```

`MyMindmapAdapter` 必须继承 `module_mindmap.ai.adapters.base.AgentAdapter`，实现 `get_manifest()`、`run()` 和取消语义。注册时平台会检查：

- `agentKey`、Adapter/SDK/runtime 版本和能力清单；
- `resultTypes` 结果能力；旧 Adapter 未声明时仅视为 `artifact`，声明 `discuss` 时必须同时声明 `message`；
- SMM v2、MindMap Tool Contract 1.0、结构化输出和统一错误合同；
- 最大节点/深度不能超过平台上限；
- 创建、会话、用量、取消及关闭生命周期方法完整；
- 相同 `agentKey` 不得覆盖内置或其他 Adapter。

Adapter 只能通过传入的 `MindmapToolService` 操作单任务内存草稿。它不能直接持有数据库、对象存储或脑图写权限；文件冻结、结构校验、hash、差异、应用和撤销均由平台完成。

讨论模式使用 `intent="discuss"`、`target="message"`。Adapter 必须返回闭合的 `message_completed` 结构，并且整个调用期间不得执行任何脑图工具；平台会再次校验纯文本类型、字符/字节上限和控制字符，再把正文写入独立 Response 存储。文字答复不会创建 Artifact、Proposal，也不会进入应用或撤销流程。完整的 Python/TypeScript 合同与第三方接入示例见 `mindmap-agent-kit/AGENT_CONTRACT.md`。

内置 Agent 通过 `build_agent_discussion_prompt()` 使用同一份紧凑讨论上下文。平台按先序保留完整节点层级和标题、备注、链接、用例标签等语义字段，移除 UID、样式和编辑器内部数据；`depth=0` 表示根主题，`depth=1` 表示一级分支。空的 `visibleHistory` 只代表没有前序对话，不代表脑图为空。第三方 Adapter 建议复用 `build_agent_discussion_prompt()`；需要自行组织提示词时，可单独调用 `compact_agent_discussion_source()`，同时必须保留不可信内容边界和提示注入防护。

原生 Ollama 模型会把 `num_ctx` 设置为至少 16384，并单独限制 `num_predict`，避免把上下文窗口与输出上限混为一谈。管理员配置的更大 `num_ctx` 会被保留。

如果 Agent 在平台进程之外运行，使用仓库根目录的 `mindmap-agent-kit/`。该工具包提供 SMM v2 Schema、Python/TypeScript 构建器、只读校验 CLI、stdio MCP Server、固定一致性夹具及 Agent 指令样例。外部产物固定标记为 `external_unverified`，导入平台后仍需由服务端重新校验。

## 最小实现

```python
from module_mindmap.ai.adapters.base import (
    AgentAdapter,
    AgentManifest,
    AgentRunContext,
    AgentRunResult,
)


class MyMindmapAdapter(AgentAdapter):
    def get_manifest(self) -> AgentManifest:
        return AgentManifest(
            agent_key="my_agent",
            display_name="My Agent",
            adapter_version="1.0.0",
            sdk_name="my-agent-sdk",
            sdk_version="1.2.0",
            runtime_version="1.2.0",
            intents=("create",),
            input_types=("none",),
            supports_sessions=False,
            supports_streaming=True,
            supports_usage=True,
            supports_cancellation=True,
            status="enabled",
            default_model_ref="my-agent-default-model",
        )

    async def run(self, context: AgentRunContext, emit) -> AgentRunResult:
        root = context.tool_service.start_document("新脑图")
        context.tool_service.add_nodes([
            {"parentUid": root["rootUid"], "text": "第一个节点"},
        ])
        artifact, summary, operations = context.tool_service.complete_artifact(
            title="新脑图",
            agent_key="my_agent",
            adapter_version="1.0.0",
            prompt_version="my-prompt-1",
            artifact_id=context.job_id,
        )
        return AgentRunResult("新脑图", artifact, summary, operations)

    async def cancel(self, job_id: str) -> bool:
        return True
```

部署扩展后，在“脑图 → AI Agent 管理”页面或通过 `POST /mindmap/ai/admin/connectors/{agentKey}/conformance` 运行确定性合同样例，再执行健康检查并设置灰度比例。凭据配置只接受 `env://` 或 `secret://` 服务端引用，任何接口响应都不会回显引用或明文密钥。

健康检查结果默认有效 15 分钟，可通过 `MINDMAP_AI_CONNECTOR_HEALTH_TTL_SECONDS` 调整（60～86400 秒）。能力清单只读取并披露状态，不主动访问供应商；已过期的健康状态会显示为待检查，任务创建时在写入任务前重新探测并刷新结果，避免把历史检查误报为当前可用。

Connector 还可以配置模型白名单、单任务美元预算、超时、节点/层级上限、并发上限和 `1d`～`365d` 结果保留期。平台在创建任务时校验白名单与请求上限，并把最终策略固化到任务记录；Adapter 应从 `context.metadata["modelRef"]` 读取模型，从 `context.metadata["maxBudgetUsd"]` 读取预算。已经排队的任务不会因管理员随后修改 Connector 而改变执行边界。平台会强制执行超时和结果结构上限；只有 Adapter/SDK 回报用量时才能执行美元成本的后验校验，因此支持硬预算的 SDK 还应在供应商调用前设置自身预算参数。

## Claude 与 Amazon Bedrock 凭据

Claude Connector 的 `credentialRef` 始终只保存服务端环境变量名，不保存、返回或记录变量值。Anthropic API/OAuth 可使用 `env://ANTHROPIC_API_KEY`、`env://ANTHROPIC_AUTH_TOKEN` 或 `env://CLAUDE_CODE_OAUTH_TOKEN`。

Amazon Bedrock 使用凭据族解析。管理员选择下列任一只写引用后，平台只把该认证方式所需的固定白名单变量复制到单次 SDK 子进程，并自动设置 `CLAUDE_CODE_USE_BEDROCK=1`：

- 静态或临时密钥：引用 `env://AWS_ACCESS_KEY_ID`、`env://AWS_SECRET_ACCESS_KEY` 或 `env://AWS_SESSION_TOKEN`。部署环境必须同时提供 `AWS_ACCESS_KEY_ID` 与 `AWS_SECRET_ACCESS_KEY`；临时凭据再提供 `AWS_SESSION_TOKEN`。
- 命名 profile：引用 `env://AWS_PROFILE`。可同时配置 `AWS_REGION`/`AWS_DEFAULT_REGION`、`AWS_CONFIG_FILE` 与 `AWS_SHARED_CREDENTIALS_FILE`；文件路径必须是绝对路径。
- Web Identity：引用 `env://AWS_ROLE_ARN` 或 `env://AWS_WEB_IDENTITY_TOKEN_FILE`，且两者必须同时存在；`AWS_ROLE_SESSION_NAME` 可选。
- Bedrock API key：引用 `env://AWS_BEARER_TOKEN_BEDROCK`。
- EC2/ECS 工作负载角色：引用 `env://CLAUDE_CODE_USE_BEDROCK`，其值必须为 `1` 或 `true`。平台可传递标准的相对容器凭据 URI，但不会允许任意 AWS endpoint 或凭据命令变量。

可选的白名单路由参数包括区域、AWS CA 文件、`ANTHROPIC_BEDROCK_BASE_URL` 和小模型区域覆盖。变量值会在进入 SDK 前校验；不完整的静态密钥/Web Identity、相对文件路径、非法 region/profile、混合 Anthropic 与 Bedrock 认证都会以统一认证错误失败，错误和 Agent 事件都不会包含凭据值。Bedrock 健康检查直接执行最小 Provider 探测，不依赖 Claude `/login` 状态。

本机开发环境也可由 `~/.claude/settings.json`（或 `$CLAUDE_CONFIG_DIR/settings.json`）的 `env` 块提供同一组白名单 Bedrock 参数。平台不会加载 settings 中的 hooks、plugins、skills、agents 或任意其他环境变量。取消任务会设置单任务取消信号并取消 SDK 查询，尚未进入内存事务的工具不得继续修改草稿。

参考：[Claude Code on Amazon Bedrock](https://code.claude.com/docs/en/amazon-bedrock) 和 [AWS SDK 环境变量优先级](https://docs.aws.amazon.com/sdkref/latest/guide/environment-variables.html)。
