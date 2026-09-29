# 脑图 Agent 本地桥接（默认扫描，Claude / Codex / Kimi 执行单独启用）

此独立 Python 伴随程序默认只把 **用户电脑上的已知 CLI 安装信息** 上报到脑图平台。普通 `run` 不读取脑图、不运行模型；仅在管理员单独启用对应 Agent、用户在本机通过 `--execute` 显式授权后，才接受本人平台任务并使用本机登录和额度。始终不上传 CLI 登录凭据、不接收任意命令。扫描、Claude / Codex 入口不开放本地 HTTP 端口；Kimi 执行使用每轮私有回环 MCP，见下文。远端 FastAPI 的“扫描运行主机”与这里的“扫描我的电脑”是两套不同的扫描。

当前支持 Python 3.10+、macOS / Linux。Windows 进程树隔离、桌面安装器和自动启动尚未实现。本机执行已接入有身份记录的启动前遗留回收，无法核实的记录保留并阻止新执行连接，见下文。“扫描发现”不等于“已登录”或“允许执行”；所有设备执行入口默认关闭，已有服务器端 Adapter 不受影响。

开发说明：Claude 执行已接入独立 WebSocket、Redis 跨 worker 分发、真实任务调度、CLI 入口与网页设备选择器。驱动通过真实 SDK、临时模拟 CLI、WebSocket 和平台工具测试，网页通过隔离组件和请求契约测试；未使用真正的供应商模型进行完整部署验收。运行边界见 [运行时说明](../docs/mindmap-agent-runtime.md#设备任务调度与出站执行接线默认关闭)。

Codex 已接入 app-server stdio、设备任务调度与网页选择；默认关闭，另需管理员开关与本机预算限制确认。支持一条设备连接明确授权 Claude / Codex 两种 Agent，由每轮网页选择决定执行哪一个，不同时启动、不静默回退。驱动边界与无模型验证见 [Codex 驱动说明](../docs/mindmap-agent-runtime.md#codex-可信本地驱动默认关闭)。

Kimi **2.1.1 受限驱动已接入 CLI、设备协议与网页选择器，默认关闭**。通过 ACP stdio 接收公开文字，通过只绑定 `127.0.0.1` 随机端口的每轮私有 MCP 接入原工具通道，不继承本机 Shell/文件/MCP/Skills。真实已安装 CLI 配合回环模拟模型验证了编辑、讨论、越界工具拒绝，以及设备路由上的实时预览、停止和断线；没有使用真实账号或付费模型。它没有金额预算限制，必须由管理员和本机用户分别明确启用；网页选择器及设备卡片持续说明限制。详见 [Kimi 驱动边界](../docs/mindmap-agent-runtime.md#kimi-21-设备驱动已接线默认关闭)。

## 管理员启用

1. 先确认已执行 `20260910_mindmap_ai_agent.sql` 对应数据库版本，再执行合并迁移：MySQL 使用 `ruoyi-fastapi-backend/migrations/20260926_mindmap_agent_runtime.sql`，PostgreSQL 使用同目录的 `20260926_mindmap_agent_runtime_postgresql.sql`，二选一。合并迁移一次建立设备表并补齐平台 Kimi 和三个设备 Connector；原拆分迁移已执行部分或全部时也可重跑，不覆盖管理员已有设置。平台 Kimi 保留原默认 `enabled=1`，三个设备 Connector 均默认停用；环境开关与本机执行授权仍需另行启用。本次开发没有在目标数据库执行迁移。
2. 配置 `MINDMAP_AI_DEVICE_BRIDGE_ENABLED=true` 并重启 FastAPI。默认值是 `false`，关闭时设备列表不访问新表。
3. 反向代理必须支持 API 路径下的 WebSocket Upgrade，且保留 Authorization 请求头。对公网部署配置 HTTPS / WSS、连接数量限制和合适的代理超时。不要记录 Authorization 或配对请求正文。
4. 用户需要已有 `mindmap:ai:use` 权限才能管理自己的设备。扫描通道逐帧检查设备凭据、有效期及账号启用状态；它不携带用户登录 Cookie / JWT，不授予文档或 Agent 执行权限。

不要为了启用桥接关闭现有传输加密。伴随程序会读取平台公开的加密配置，按路径使用现有 RSA-OAEP + AES-GCM 信封；加密失败不退回明文重试。传输信封不能替代 TLS。

### 额外启用 Claude 执行（开发接线，默认关闭）

1. 完成上面的合并迁移即可，无需再执行单独的 Claude SQL；迁移创建的 `device_claude` Connector **默认停用**，不会覆盖已有管理员配置。
2. 管理员审核并启用该 Connector，保留现有灰度、网络、模型、预算和并发策略；同时设置 `MINDMAP_AI_DEVICE_EXECUTION_ENABLED=true`。该开关与发现开关缺一不可。现有应用 Redis 必须正常工作。
3. 在自己的电脑安装 `./mindmap-agent-bridge[claude]` 可选依赖，完成 Claude CLI 安装/登录后，显式运行 `mindmap-agent-bridge run --execute claude`。普通 `run` 和配置文件都不能代替这个本机授权。
4. 在网页聊天输入区选择“Claude · 我的电脑”，再选择执行电脑，或在“管理 Agents → 我的电脑”点击“使用 Claude”。已认证的任务 API 使用 `agentKey: "device_claude"` 和本人的 `deviceId`；普通平台 Agent 不能携带 `deviceId`。任务详情回传所绑定的设备 ID。必须看到设备执行通道已连接；仅出现 Agent 名称或扫描到 CLI，不代表已经可执行。

执行使用本机模型账户。管理员的模型名、时间上限和金额预算经闭合白名单传给 CLI 的 `model` / `max_budget_usd`，金额是 SDK 的执行预算约束，不是独立财务对账或收费保证。平台凭据和环境变量不下发。运行期间按 Ctrl+C 会尝试终止本轮 CLI；不能确认整组进程退出时保留错误，不能当作正常取消。

### 额外启用 Codex 执行（开发接线，默认关闭）

1. 完成上面的合并迁移即可，无需再执行单独的 Codex SQL。新建 `device_codex` 默认停用，不覆盖管理员已有配置；在设备发现、执行开关之外，审核后启用该 Connector，并设置 `MINDMAP_AI_DEVICE_CODEX_ENABLED=true`。本次开发未执行迁移或更改运行环境。
2. 安装 `'./mindmap-agent-bridge[codex]'`，只执行随包固定的 Codex 0.147.0，不执行 PATH 上扫描到的其他版本。当前只接受平台明确指定的 `gpt-5.6-terra`，未经验证的模型直接拒绝，不自动替换模型。
3. 完成本机 Codex 文件登录，或由用户在本机终端提供 `OPENAI_API_KEY`。不会读取自定义插件/工具配置；钥匙串独有认证、自定义提供商与企业非空托管配置暂不支持。凭据不上传，认证是否被供应商接受只能在实际任务中确认。
4. 理解并接受下方预算限制后，显式运行 `mindmap-agent-bridge run --execute codex --accept-estimated-budget`；在聊天中选择“Codex · 我的电脑”及执行电脑。

**Codex 预算按已回报用量估算，不是硬费用上限，也不是订阅账单。当前请求可能在用量通知到达前已经超额。** 不接受该限制时，不应启用 Codex 设备执行。CLI 必须显式带上确认参数，配置文件、远端消息和网页扫描不能替代此授权；网页选择器与设备卡片也持续显示此限制。

若要在网页切换两种本机 Agent，安装并同时授权：

```sh
pip install './mindmap-agent-bridge[claude,codex]'
mindmap-agent-bridge run --execute claude --execute codex --accept-estimated-budget
```

一台电脑仍只有一个活动执行槽。网页在当前轮运行期间切换 Agent 或设备，先确认并停止原任务，成功后才更改下一轮选择；已有脑图增量不会因切换被自动撤销。仅开启 Claude 时，网页不能把它当作 Codex 连接使用。

### 额外启用 Kimi 执行（开发接线，默认关闭）

1. 完成上面的合并迁移即可，无需再执行单独的设备 Kimi SQL。迁移新增的 `device_kimi` 默认停用，不覆盖已有配置；在设备发现与执行开关之外，管理员审核后启用该 Connector，并设置 `MINDMAP_AI_DEVICE_KIMI_ENABLED=true`。本次开发未执行迁移或启用部署。
2. 在电脑安装并登录 **Kimi Code CLI 2.1.1**，不是旧版 Python `kimi-cli`；确保本机能找到 `kimi` 及所需 Node。安装 `'./mindmap-agent-bridge[kimi]'`。平台模型必须为 `kimi-for-coding`，其他版本/模型会被拒绝，不静默回退。
3. 理解并接受 **Kimi 无金额上限、无可信金额用量检查，仅限制任务时间及工具次数** 后，运行 `mindmap-agent-bridge run --execute kimi --accept-unmetered-budget`。配置文件、网页扫描及服务端响应不能代替该本机同意。
4. 网页选择“Kimi · 我的电脑”与对应执行电脑。普通扫描连接、已安装 CLI 或其他 Agent 的执行连接均不能代替 Kimi 执行连接。已完成的增量保留；主动停止等待进程退出回执，断线未收到回执则保留“未确认停止”，不自动重跑。

每轮使用私有配置及单份本机认证副本，不上传登录凭据、不写回原 OAuth 文件。只允许审核的官方 Kimi coding 服务地址。实际供应商登录刷新、账户额度与部署后端到端仍需独立验收；这不是 OS 沙箱，崩溃恢复也只清理能证明归属的进程，不保证清理任意脱离进程组的程序。

理解上述各自预算限制后，同一电脑可显式授权三种 Agent，仍然每次只执行网页选择的一个：

```sh
pip install './mindmap-agent-bridge[claude,codex,kimi]'
mindmap-agent-bridge run --execute claude --execute codex --execute kimi --accept-estimated-budget --accept-unmetered-budget
```

## 用户使用

推荐在独立 Python 虚拟环境中安装。在项目根目录执行：

```sh
python3 -m venv .venv-agent-bridge
.venv-agent-bridge/bin/python -m pip install ./mindmap-agent-bridge
```

网页打开“管理 Agents → 我的电脑”，输入设备名称，点击“连接新设备”。在电脑终端执行：

```sh
.venv-agent-bridge/bin/mindmap-agent-bridge pair --server https://你的平台/API前缀
.venv-agent-bridge/bin/mindmap-agent-bridge run
```

`--server` 必须是对外可达的 **API 根地址**，包含部署所需的 API 前缀，不是脑图页面地址。只对 `localhost` / 回环 IP 允许开发用 HTTP，例如 `http://127.0.0.1:8000`；不支持跳转到另一个服务地址。

配对码只在终端的隐藏输入提示中粘贴，不作为命令参数、环境变量、URL 或 AI 提示词传递。配对成功后，`run` 保持出站连接并执行一次扫描；网页“扫描此电脑”可刷新新安装的 CLI。停止终端或按 Ctrl+C 后设备离线，不会卸载 CLI。

其他命令：

```sh
.venv-agent-bridge/bin/mindmap-agent-bridge scan
.venv-agent-bridge/bin/mindmap-agent-bridge status
```

`scan` 仅在本机输出已知 CLI 的公开版本及探测能力；`status` 只显示本地配置情况，并不证明设备仍获服务端授权。两者均不显示密钥。

### 配对/运行前的安装诊断

安装所选 Agent 的可选依赖后，可以在未配对、未登录时执行：

```sh
.venv-agent-bridge/bin/mindmap-agent-bridge doctor
.venv-agent-bridge/bin/mindmap-agent-bridge doctor --agent claude --agent codex
```

默认检查 Claude、Codex、Kimi；`--agent` 可重复，只检查用户指定项。复用实际执行驱动的依赖/版本与可执行文件选择规则：Claude 检查固定 SDK 与本机 CLI，Codex 检查固定随包 CLI（不是 `scan` 发现的 PATH 版本），Kimi 检查执行依赖及 2.1.1。每个已找到的程序只运行有 6 秒超时/64 KiB 输出限制的 `--version`，使用临时私有 HOME/XDG 目录，不继承认证环境变量，不读取配对配置、暂存登录、执行恢复或建立平台连接。输出只包含有限版本与固定修复提示，不输出绝对路径或原始错误；原配置与安装不会被修改。

所有所选项的 `installationStatus` 均为 `passed` 时退出码为 0，否则为 1。**通过只代表基础安装检查，不证明协议握手、登录、模型或平台授权可用。** 因此输出始终为 `authenticationStatus: not_checked` 和 `executionAvailable: false`；`doctor` 不能代替 `run --execute`、管理员启用或预算确认。`installCommand` 需要在项目根目录、用户选定的虚拟环境中手动执行，不会自动安装或升级。版本探测依然运行用户已信任的本机程序，不是 OS 沙箱。

## 凭据与恢复

- 配对码有效期 5 分钟；设备授权最长 90 天；每个账号最多 8 个有效设备/待配对记录。无需提交 Claude、Codex、Kimi 的 API Key 或登录令牌。
- 默认配置：`~/.config/mindmap-agent-bridge/device.json`。设备密钥是本机生成的随机值，在首次请求前持久化到当前用户所有、仅用户可读写的 `0600` 文件。服务端只存 SHA-256 摘要。
- 配对响应丢失时，在 5 分钟窗口内重试同一 `pair` 命令；使用原密钥，不重新输入配对码。只有同一设备、同一密钥可重复确认。
- 超时无法重试时，先在网页撤销待配对设备，再生成新配对码；明确选择一个新的配置文件，例如 `mindmap-agent-bridge --config /你的私有目录/new-device.json pair --server …`。之后 `run` / `status` 也应使用同一个 `--config`。已有配置不会被静默覆盖。
- 更换电脑、卸载或泄露配置时，先在网页撤销授权。服务端立即将设备标为撤销，伴随程序在下一帧认证时断开。随后停止本机进程，并手工移除明确的旧配置文件；仅关闭终端不等于撤销授权。
- 不要把配置文件提交到 Git、同步到公共目录或发送给客服/AI。配对后本地文件会移除临时配对秘密。

### 本机执行崩溃恢复

Claude、Codex、Kimi 每轮执行使用 `~/.local/state/mindmap-agent-bridge/runs/<随机ID>` 下的私有目录（`0700`），所有权记录为 `0600`。记录只含 Agent 类型、桥接与子进程的 PID/创建时间，不含提示词、用户脑图、命令参数或凭据；**运行目录内仍可能有本轮认证副本和 CLI 运行数据，不要同步、上传或公开整个目录。** 正常停止后清理本轮目录。

- 新的 `run --execute …` 在建立扫描/执行连接之前检查上次的运行记录。启动器先登记自身 PID 并落盘，再执行实际 Agent；登记失败或桥接已经退出则不执行 Agent。
- 活跃桥接的锁和进程身份都会被检查，不干扰另一条正常运行的桥接。对确认属于已退出桥接的 Agent，先 TERM、必要时 KILL，确认进程组退出后才清理私有目录。
- PID 复用、记录损坏、权限不安全、符号链接、终止失败，或启动时组长已消失但仍有无法证明归属的子进程，都会保留记录并阻止新的执行连接。终端仅报告恢复计数/需处理状态，不打印目录内容或秘密。
- 遇到未确认记录，应先由本机用户/管理员核对相应私有运行记录与实际进程状态。不要直接删除整个 runs 根目录，也不要仅凭旧 PID 手动终止进程。确认该轮所有进程停止后，才能处理该轮准确的目录并重新运行。
- 恢复不会重新发送提示词、重跑旧任务、恢复供应商会话或将服务端旧任务改成成功/已确认停止。仍需在网页检查旧任务和保存回执，再明确发起下一轮。

此机制只覆盖采用新记录格式的本机执行。旧版 `/tmp/mindmap-*` 无记录目录、FastAPI 平台主机进程和主动脱离进程组的任意程序不做自动清理；普通 `run`/`scan` 仍是发现模式，不触发执行恢复。桥接尚未重启时不提供后台守护清理保证。

## 协议与安全边界

```text
已登录网页 → 创建 5 分钟配对码 → 本地终端配对
本地伴随程序 → 带设备 Authorization 头的出站 WSS
  ← welcome / state（仅扫描序号，不含命令）
  → heartbeat / scan_result（版本、固定能力、安装状态）
网页按账号读取设备状态 → 扫描 / 撤销
```

扫描协议版本 1 只有 `discover` 能力，双端始终声明 `executionAvailable=false`。它严格拒绝额外字段、未知 Agent、任意命令及虚构的 ready 状态。设备扫描不会改变 Connector、当前 Agent、聊天记录或画布草稿。执行使用另一条 `/execute/{deviceId}` 出站通道，不放宽原扫描协议；用户设备列表仅在实时执行连接存在时附带 `executionAvailable` / `executionBusy` / `executionAgents`。

单 Claude 执行保留版本 1 握手。Codex / Claude+Codex 使用版本 2，显式列出 `agentKeys`，并确认 `codexBudgetPolicy: reported_usage_estimate`。包含 Kimi 时使用版本 3，额外确认 `kimiBudgetPolicy: timeout_and_tool_limit`；没有选择 Codex 时其预算字段为 null。服务端原样确认，本机拒绝字段缺失、改写或旧版本承载 Kimi；每轮工具/事件协议仍为版本 1。服务端严格匹配启用项、本机同意项与任务 Agent，不接受任意程序。执行通道检查到任一已声明 Agent 的服务端执行开关关闭时，会关闭这条连接，需要用户检查任务状态后手动重新连接。

扫描只解析 Claude、Codex、Kimi 的 `PATH`、`~/.local/bin`、`~/.npm-global/bin`、`/opt/homebrew/bin`、`/usr/local/bin`。在空临时目录中，以参数数组调用其 `--version` / `--help`（Claude 使用 `-p --help` 获取 print 模式能力），不使用 shell；每次探测最长 6 秒、输出最多 64 KiB，清理独立进程组。环境仅保留 HOME/PATH/语言/临时目录相关项。

**扫描仍然会执行已安装的程序，不是操作系统沙箱。** 这些程序能访问本机当前用户允许访问的资源，因此只应安装和扫描用户自己信任的 CLI。版本帮助文本不原样上传；只提取限定版本号、预定义能力，不上传可执行文件绝对路径或配置文件。

同一设备只允许一个在线扫描连接；重复启动 `run` 或 `run --execute` 不会替换原连接、取消原任务。在线租约冲突通过独立的 HTTP 409 握手响应表示，扫描通道最多等待 25 秒，仍被占用则退出；认证失败不进入这一重试。切换执行启用项时先停止原桥接再启动；原连接已断开或超过 20 秒在线窗口后，才允许新连接接管，短暂断网或服务崩溃的孤立租约可在等待期间过期。重新建立连接使用新的服务端连接标记，旧连接无法回写或把新连接误标离线。重复扫描合并为一个待完成序号，旧结果不能覆盖新结果。心跳间隔 5 秒；每帧最多 16 KiB、10 秒最多 12 帧，HTTP 配对请求在解密/JSON 解析前也有体积限制。

执行通道每设备只允许一个连接、每连接只执行一轮，任务结束并得到停止确认后才开启下一条空闲连接。任务中断不自动重连重跑；重新认领崩溃 worker 的旧任务也不自动启动第二次 CLI。Redis 队列限制条数、字节数和存活时间，不存密钥。工具、Todo、草稿增量仍由平台原有工具网关和事件存储产生，设备不能上传一个脑图冒充完成结果。撤销设备会拒绝后续读取/编辑；即使本机已自行停止，平台收不到停止回执也会诚实显示“尚未确认停止”。

预算耗尽、认证失败或超时等受控单轮失败，只有在本机已确认进程停止、服务端已确认本轮终态并完成结束握手后，桥接才回到空闲，等待用户明确发起的新任务；不会重试失败的旧任务。断线、协议错误、未收到有效终态回执或清理失败仍退出执行连接，需要用户检查后重新连接。

## 验证（不使用付费模型或应用数据库）

Claude 驱动开发测试还需要可选依赖 `./mindmap-agent-bridge[claude]`（固定已验证 SDK 版本和进程检查库）。下列命令复用的 backend 测试环境已包含这些依赖；普通设备发现不需要安装该可选项。跨 worker 测试额外需要本机 `redis-server`：测试自行启动仅监听私有 Unix Socket 的临时 Redis，不使用应用 Redis。

Codex 驱动开发测试使用 `./mindmap-agent-bridge[codex]`，锁定随包 `openai-codex-cli-bin==0.147.0`，不执行 PATH 上的其他 Codex 版本。可显式运行 `MINDMAP_CODEX_PREFLIGHT=1 PYTHONPATH=../mindmap-agent-bridge .venv/bin/python -m pytest ../mindmap-agent-bridge/tests/test_codex_driver.py -q`：真实 CLI 只检查初始化、配置、Skills、本地虚构 Key 登录和临时线程，不发送 `turn/start`，不读取用户真实登录。其余模型执行场景均由模拟 app-server 验证，不能代表真实账号已登录或模型可用。

Kimi 驱动测试需要 `./mindmap-agent-bridge[kimi]` 可选依赖。`tests/test_kimi_driver.py` 的协议/网关/配置测试默认运行；真实 CLI 用例须同时设置 `MINDMAP_KIMI_TEST_NODE`（本地 Node 22.19+ 绝对路径）与 `MINDMAP_KIMI_TEST_BUNDLE`（已安装 `@moonshot-ai/kimi-code@2.1.1` 的 `dist/main.mjs` 绝对路径）才运行。测试使用新建私有 HOME 和虚构 Key，将提供商替换为测试自己绑定的回环 HTTP 服务；生产驱动不提供这一覆盖参数。测试会运行真实 CLI 的模型协议，但所有模型响应由本地测试服务生成，不读取用户登录、不产生供应商模型请求。核验版本前不暂存凭据。

Kimi 实际 CLI 验证有 8 个场景：驱动的编辑、讨论、越权 Shell、越权文件读取、取消；服务端真实设备路由的完整创建、中途停止、执行连接断开。完整创建保留 Todo、工具详情与 2 次实时预览；中途终止在已有根节点预览后触发，确认进程/私有目录清理且不自动重跑。断线未收到停止回执时保留未确认状态。版本 3 管理员开关和预算同意另有实际路由拒绝测试。

2026-09-26 联合复验全部伴随程序与后端设备目录、分发、执行、配对及传输加密：345 通过、8 跳过。8 个跳过项为未启用的其他 CLI opt-in 预检及临时 SQLite 集成用例，不代表这些场景已验证。当前部署、用户真实登录与付费模型仍未验收。

后续崩溃恢复补充：新增 21 项隔离测试，覆盖自建桥接进程被 SIGKILL、进程身份/记录写入/锁/目录边界、升级终止和启动前阻断。联合回归更新为 366 通过、8 跳过，真实 Kimi CLI 的预览、停止与断线场景仍通过。没有对用户现有进程或目录运行恢复；测试根目录逐用例隔离。

跨协议接续补充：新增 Claude/Codex/Kimi 两两切换的 6 个方向，验证已有部分修改与 Todo 保留、旧驱动退出清理、新驱动读取平台上下文、旧连接失效及未选驱动不执行。使用实际驱动、工具网关、WebSocket 和隔离 Redis，但 CLI 协议对端/模型与 SQL 检查点为模拟；不等同于真实账号或数据库提交验收。包含接续/重试/停止状态的扩大回归为 446 通过、30 跳过；本次没有启用真实 CLI 或数据库 opt-in，用例范围与上方历史运行不同。前端一次确认后的退出及画布同步等待详见 [运行时记录](../docs/mindmap-agent-runtime.md#一次确认后的停止与切换2026-09-26)。

SQL 联合验收补充：`test_mindmap_device_handoff_sql.py` 将这六个方向接入真实任务调度、设备配对鉴权和临时 SQLite，不再模拟 DAO、直写提交或退出证据；另验证事务失败回滚、接续权限及逐轮撤销。四个明确隔离的测试文件共 55 项通过、0 跳过。CLI/模型仍为离线协议模拟，不代表真实账号或部署数据库验收。运行命令及替身边界见 [设备接续与 SQL 持久化验收](../docs/mindmap-agent-runtime.md#设备接续与-sql-持久化的联合验收2026-09-26)。

公开回复接续补充（2026-09-27）：同一授权内容分支换 Agent 后，平台会提供有长度上限的旧 Agent 公开正文和 Todo，原始工具结果、隐藏推理和供应商会话不随之转交；旧回复只是陈述，不代表修改已保存。六方向离线协议/真实 SQL 联合测试已增加编号建议传递断言，隔离 SQL 回归共 56 项通过。桥接端同步修正中文紧邻密钥样式的流式脱敏边界。详见 [编辑公开回复的跨 Agent 接续](../docs/mindmap-agent-runtime.md#编辑公开回复的跨-agent-接续2026-09-27)。

在项目的 backend 目录，复用已有测试环境：

```sh
PYTHONPATH=../mindmap-agent-bridge .venv/bin/python -m pytest ../mindmap-agent-bridge/tests -q
.venv/bin/python -m pytest tests/test_mindmap_agent_devices.py tests/test_mindmap_device_transport_crypto.py -q
.venv/bin/python -m pytest tests/test_mindmap_device_run.py -q
.venv/bin/python -m pytest tests/test_mindmap_device_dispatch.py -q
MINDMAP_DB_INTEGRATION=1 .venv/bin/python -m pytest tests/test_mindmap_agent_devices.py -q
```

真实 Kimi CLI + 本地模拟模型的复验（将两个路径替换为已经安装且信任的本机程序，不会自动下载）：

```sh
MINDMAP_KIMI_TEST_NODE=/绝对路径/node \
MINDMAP_KIMI_TEST_BUNDLE=/绝对路径/@moonshot-ai/kimi-code/dist/main.mjs \
PYTHONPATH=../mindmap-agent-bridge .venv/bin/python -m pytest \
  ../mindmap-agent-bridge/tests/test_kimi_driver.py tests/test_mindmap_device_dispatch.py -k kimi -q
```

上方 `MINDMAP_DB_INTEGRATION=1` 命令只为该测试文件启用 **临时内存 SQLite**：测试创建自己的用户/设备表，验证配对、撤销、重连和实际 FastAPI WebSocket 路由；不连接已配置的应用数据库。不要把这个环境开关无范围地用于其他测试。MySQL / PostgreSQL 的并发锁语义仍需在独立测试库中验收。
