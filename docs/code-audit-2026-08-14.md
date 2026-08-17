# RuoYi-Vue3-FastAPI 全仓库代码问题审计

> 审计日期：2026-08-14
> 范围：后端、前端、测试工程、部署配置及当前未提交改动
> 方法：仓库级静态检索、关键调用链复核、Python 字节码编译、Ruff、前端生产构建

## 1. 结论摘要

当前代码不建议直接部署到公网生产环境。最优先需要处理的是已经提交到仓库的认证密钥、文件上传路径穿越和资源下载越界；其次是飞书 OAuth 登录缺少 `state` 校验、可公开访问的主动内容文件以及前端无法从仓库状态稳定构建。

本次确认 11 项问题：P0 级 2 项、P1 级 5 项、P2 级 4 项。本文只记录能够从现有代码和调用链确认的问题，不把普通格式告警逐条当作缺陷。

## 2. 问题清单

### AUDIT-001 [P0] 认证密钥和第三方应用密钥已进入版本库

**证据**

- `ruoyi-fastapi-backend/config/env.py:33` 提供固定 JWT HMAC 密钥。
- `ruoyi-fastapi-backend/config/env.py:77-79` 提供固定飞书 App ID、App Secret 和回调地址。
- `.env.dev`、`.env.prod` 等环境文件也被 Git 跟踪，并包含相同 JWT 密钥、数据库口令和飞书密钥。

**影响**

任何能读取仓库的人都可以使用 JWT 密钥伪造任意用户令牌；飞书密钥泄露后可被用于冒充应用调用开放平台。仅从当前文件删除密钥还不够，因为旧值仍存在于 Git 历史中。

**建议**

1. 立即轮换 JWT、飞书和生产数据库凭据。
2. 配置模型不再提供可工作的密钥默认值；生产启动时缺失密钥应直接失败。
3. 只提交 `.env.example`，真实环境文件进入 `.gitignore`，生产使用 Secret Manager 或部署平台密钥注入。
4. 清理 Git 历史中的真实密钥，并检查访问日志确认是否已被滥用。

**验收**：仓库及历史扫描不再发现有效密钥；旧 JWT 与飞书密钥均失效；缺少生产密钥时服务无法启动。

### AUDIT-002 [P0] 上传文件名可造成目录穿越和任意文件写入（已修复）

**修复记录（2026-08-14）**：上传文件改为服务端 UUID 命名，客户端文件名仅保留去除路径后的末级名称；目标目录和文件在写入前均解析真实路径并验证位于上传根目录内。已增加恶意文件名回归测试。

**证据**

- `ruoyi-fastapi-backend/module_admin/service/common_service.py:41-43` 将客户端提供的 `file.filename` 主体直接拼入目标路径。
- `ruoyi-fastapi-backend/utils/upload_util.py:39-48` 只检查最后一个扩展名，没有去除 `/`、`\\` 或 `..` 路径片段。
- 上传接口只要通过登录校验即可调用：`module_admin/controller/common_controller.py:14-24`。

例如攻击者可构造包含 `../../` 的文件名；`os.path.join` 和 `aiofiles.open` 会按该路径写入，而不是强制留在上传目录。若运行账户对目标文件可写，可能覆盖应用文件或部署配置。

**建议**

忽略客户端文件名生成服务端 UUID 文件名；需要展示原名时只作为数据库元数据保存。写入前使用 `Path.resolve()`，并通过 `relative_to(upload_root.resolve())` 强制验证最终路径位于上传根目录。为 POSIX 和 Windows 分隔符、绝对路径、双重扩展名补充测试。

**验收**：路径穿越文件名返回 4xx；磁盘上只产生位于上传根目录内、由服务端生成名称的文件。

### AUDIT-003 [P1] 资源下载只验证末级文件名，可越界读取服务器文件（已修复）

**修复记录（2026-08-14）**：资源必须使用精确 `/profile/` 前缀，服务端对完整相对路径执行规范化，并在读取前验证解析结果位于上传根目录内。已增加父目录逃逸和合法资源读取测试。

**证据**

- `ruoyi-fastapi-backend/module_admin/service/common_service.py:91` 对完整 `resource` 字符串执行简单 `replace` 后直接作为文件路径。
- `ruoyi-fastapi-backend/module_admin/service/common_service.py:92-99` 只检查最后一个文件名，父目录中的 `../` 不参与校验。

攻击者可以让末级文件名满足时间戳、机器码和三位随机数格式，同时在父目录中加入遍历片段。只要目标文件名碰巧满足该格式，就能读取上传目录之外的文件。

**建议**

只接受数据库中的资源 ID，服务端查询真实路径；至少应解析并规范化路径，再验证它严格位于 `UPLOAD_PATH` 下。不要用字符串替换实现路径映射。

**验收**：包含编码或未编码 `..`、绝对路径、重复 `/profile` 前缀的请求全部被拒绝。

### AUDIT-004 [P1] HTML/SVG 文件可上传到同源静态目录，形成持久化主动内容风险

**证据**

- `ruoyi-fastapi-backend/config/env.py:108-138` 允许 `svg`、`html` 和 `htm`。
- `ruoyi-fastapi-backend/sub_applications/staticfiles.py:11` 将上传目录直接挂载为同源静态资源。
- 上传校验仅依赖扩展名，不校验 MIME、文件签名或内容。

攻击者上传 HTML 或含脚本/外链的 SVG 后，可以诱导同源用户访问该资源。即使浏览器对部分 SVG 展示施加限制，直接访问 HTML 仍会运行在应用源下，可能读取非 HttpOnly 数据或执行已登录用户操作。

**建议**

禁止 HTML/HTM/SVG 等主动内容，或放到独立无凭据域名并强制 `Content-Disposition: attachment`、`X-Content-Type-Options: nosniff`。同时核对实际 MIME 和文件签名。

**验收**：主动内容不能以内联形式从应用源打开；伪造扩展名上传失败。

### AUDIT-005 [P1] 飞书 OAuth `state` 是常量且回调未校验

**证据**

- `ruoyi-fastapi-backend/module_admin/controller/login_controller.py:93-98` 固定发送 `state=STATE`。
- `FeishuLoginCode` 虽定义了 `state`，但 `feishu_login` 在 `login_controller.py:106-112` 只传递 `body.code`。
- `authenticate_feishu` 在 `module_admin/service/login_service.py:151-205` 不验证任何浏览器会话随机值。

这使授权响应无法绑定到发起登录的浏览器会话，存在登录 CSRF/会话混淆风险。

**建议**

授权前生成高熵一次性 `state`，存入 HttpOnly、SameSite Cookie 或 Redis 会话，并设置短 TTL；回调必须常量时间比较、验证后立即删除。也应考虑 PKCE。

**验收**：缺失、错误、过期或重复使用的 `state` 均无法换取系统令牌。

### AUDIT-006 [P1] 注册成功提示拼接用户输入并启用 HTML 解析

**证据**

`ruoyi-fastapi-frontend/src/views/register.vue:129-133` 将注册用户名直接拼入 HTML 字符串，同时启用 `dangerouslyUseHTMLString`。现有前端用户名规则没有在此输出点进行 HTML 转义。

若用户名包含标签或事件属性，注册成功后即可在当前页面执行脚本。后端约束即使目前能阻止部分字符，也不应成为前端危险渲染的唯一防线。

**建议**

关闭 `dangerouslyUseHTMLString`，用纯文本消息或 VNode 渲染用户名。相同模式也应审查 `src/views/system/user/index.vue:801-806` 的服务端 `response.msg`。

**验收**：包含 `<`, `>`, 引号的显示名只以文本展示；增加 DOM/XSS 回归测试。

### AUDIT-007 [P1] 前端生产构建无法从已提交仓库状态复现

**证据**

- 执行 `npm run build:prod` 失败，Rollup 无法解析 `simple-mind-map-plugin-themes`。
- `package.json:44` 声明了该依赖，但 `package-lock.json` 未被 Git 跟踪，仓库也没有任何其他前端锁文件。
- 当前本地 `node_modules` 与依赖声明不一致。

缺少锁文件会导致不同机器安装不同的传递依赖版本，也让 CI 无法使用 `npm ci` 建立确定性基线。

**建议**

选择 npm/pnpm/yarn 中唯一一种包管理器，重新生成并提交锁文件；清空安装目录后用冻结锁文件安装并构建。CI 必须执行该流程。

**验收**：全新目录中 `npm ci && npm run build:prod`（或等价命令）稳定通过。

### AUDIT-008 [P2] 在线用户查询使用 Redis `KEYS`，会阻塞实例

**证据**

`ruoyi-fastapi-backend/module_admin/service/online_service.py:28-34` 使用 `KEYS access_token*`，然后逐个串行 `GET` 和 JWT 解码。

`KEYS` 会遍历整个 Redis keyspace，并在执行期间阻塞其他请求；在线会话增长后，后台查看在线用户本身可能拖慢登录与鉴权。

**建议**

使用维护的在线会话集合/有序集合，或至少使用 `SCAN` 分页及 pipeline 批量读取。接口还应分页并处理过期或损坏令牌，而不是让单条坏数据中断整页。

**验收**：大 keyspace 压测下不出现 Redis 长阻塞；单条无效会话不会导致接口 500。

### AUDIT-009 [P2] 生产数据库 SQL 日志默认开启

**证据**

- `ruoyi-fastapi-backend/config/env.py:50` 默认 `db_echo=True`。
- 已提交的 `.env.prod`、Docker MySQL/PostgreSQL 环境文件也设置 `DB_ECHO=true`。
- `config/database.py:18-25` 将该值直接传给 SQLAlchemy 引擎。

生产环境会持续输出 SQL 与绑定信息，既增加日志 I/O，也可能暴露用户标识、查询条件或其他业务数据。

**建议**

生产默认关闭 SQL echo；需要诊断时使用短时、分级、脱敏的结构化日志。

**验收**：生产配置中 `DB_ECHO=false`，常规请求日志不包含 SQL 参数。

### AUDIT-010 [P2] 自动化质量门禁缺失，现有静态检查已失败

**证据**

- 前端 `package.json` 只有开发和构建命令，没有 lint、类型检查或单元测试脚本。
- 后端运行 Ruff 得到 41 项告警，包括重复导入、未使用导入、缺少类型标注和 async 函数中的阻塞式实现。
- 后端 `compileall` 成功，但只能证明语法可加载，不能证明业务行为正确。
- `ruoyi-fastapi-test` 主要是依赖真实服务和浏览器的端到端测试，没有覆盖上述安全边界的单元/集成测试。

**建议**

CI 至少加入后端 Ruff、关键 service 单测、前端 lint/类型检查/构建；安全回归测试应覆盖上传、下载、OAuth state、JWT 配置和 XSS 输出点。

**验收**：合并请求在任一质量门禁失败时不可合并，且新增安全回归用例稳定通过。

### AUDIT-011 [P2] 当前思维导图重构设计与现有引擎契约不一致（已修复）

**修复记录（2026-08-14）**：设计已补充 `ResizeObserver` 和 `mindMap.resize()` 契约，修正 `node_active(node, activeNodeList)` 事件签名，明确 `localConfig.sidebarMode` 为唯一状态源，并移除对不存在组件的复用要求。引擎全局默认根节点字号恢复为 16px。

**证据**

- `docs/superpowers/specs/2026-06-18-mindmap-editor-redesign.md:171-174` 只描述容器宽度动画，没有要求容器变更后调用 `mindMap.resize()`；现有 `Edit.vue:402-403` 仅响应窗口 resize。
- 设计文档 `:182` 把 `node_active` 写成单参数；引擎实际在 `Render.js:465` 发送 `(node, activeNodeList)`。
- 设计声称复用 `VersionHistory.vue`、`CollaboratorManager.vue`、`ShareDialog.vue`，但仓库不存在这些组件。
- `src/libs/simple-mind-map/src/theme/default.js:78` 的未提交改动把全局默认根节点字号从 16 改为 20，影响所有默认主题消费者，不只是新页面。

**建议**

先修订设计契约：容器使用 `ResizeObserver`、按真实事件签名实现、补全或移除不存在的功能，并把页面视觉覆盖放入页面级 `themeConfig`，不要直接改变引擎全局默认值。

**验收**：侧栏动画后画布尺寸和命中区域正确；取消选中能关闭自动面板；全新构建不存在缺失组件；其他脑图页面视觉不回归。

## 3. 修复顺序

### 第一阶段：立即止血

1. 轮换并移除全部真实密钥。
2. 暂停或限制通用上传、资源下载入口。
3. 修复上传和下载路径边界，禁止主动内容。
4. 为飞书 OAuth 加入一次性 `state`。

### 第二阶段：恢复可靠交付

1. 提交唯一前端锁文件并修复生产构建。
2. 建立后端 Ruff、前端构建和安全回归测试门禁。
3. 修复所有危险 HTML 输出点。

### 第三阶段：性能与架构治理

1. 将 Redis `KEYS` 改为集合索引或 SCAN/pipeline。
2. 关闭生产 SQL echo，统一环境配置策略。
3. 修订思维导图设计后再开始大规模 UI 重构。

## 4. 本次验证结果

| 检查 | 结果 |
|---|---|
| `python -m compileall` | 通过 |
| `ruff check` | 失败，41 项 |
| `npm run build:prod` | 失败，缺少 `simple-mind-map-plugin-themes` |
| Git 工作区 | 原有 4 项未提交变更；本审计新增本文档 |

## 5. 审计边界

本次没有连接真实 MySQL、PostgreSQL、Redis、飞书或浏览器环境，因此没有执行会写入外部系统的端到端测试；依赖漏洞数据库也未联网查询。数据库事务并发、真实权限数据、部署网关头处理和第三方依赖 CVE 仍属于残余风险，后续应在隔离测试环境继续验证。
