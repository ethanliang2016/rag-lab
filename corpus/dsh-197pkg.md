# @deepseek-ai 包汇总与架构解读

> 提取日期：2026-09-01 | 生成方式：DSH Web UI 内由 agent 完成任务「总结这个目录下 node_modules/@deepseek-ai 里有哪些包，按功能分类」（实际消耗 0.47 元）
> 来源目录：`C:\Users\lenovo\AppData\Local\Temp\dsh-pnpm\node_modules`
> 提取方式：读取 pnpm 虚拟存储 `.pnpm\@deepseek-ai+*` 下各包自身 `package.json` 的 name/version/description（包自身为真实目录，依赖为 junction，据此区分）

> ✅ **独立核验(2026-09-01,Claude Code 逐包比对)**:从文档清单中抽取 40 个"高风险"包名(含截断目录中不可直接 grep 的长名,如 dsh-session-title-first-prompt-llm、dsh-tool-ralph),逐一读取 .pnpm 内各包真实 package.json 比对——**40/40 全部存在,零幻觉**;总数 197 独立复核一致;抽查 10 个功能描述与官方 description 原文逐句对应。判定:可信引用级。
> 核验方法备注:pnpm 虚拟存储目录名会被截断并附哈希(如 `dsh-agent-inst_1f9b...`),朴素 glob/grep 会大量 miss,必须进入目录读 package.json 的 name 字段为准。

## 1. 目录结构事实

- 顶层 `node_modules\@deepseek-ai` 下**只有一个链接**：`dsh`（CLI 入口）。
- 真正的包全部位于 pnpm 虚拟存储 `node_modules\.pnpm\@deepseek-ai+*`（目录名带截断与内容哈希）。
- **共 197 个唯一包**，绝大多数版本为 `0.1.1-rc.2`，属 **DeepSeek Harness** 项目（monorepo 发布物）。
- 少量第三方/自研基础件：`cordis@4.0.2`、`cordis-plugin-*`（5 个）、`cosmokit@1.8.3`、`schemastery@3.18.2`、`node-addon-landlock-run@0.1.1`。

## 2. 包清单（按功能分类）

### 2.1 核心框架与基础工具（22 个）

| 包 | 作用 |
|---|---|
| `cordis` 4.0.2 | 插件化元框架，整个 Harness 的运行时底座 |
| `cordis-plugin-group` | 嵌套插件组 |
| `cordis-plugin-hmr` | 插件热更新 |
| `cordis-plugin-include` | 配置 include |
| `cordis-plugin-loader` | 插件加载器 |
| `cordis-plugin-timer` | 定时器服务 |
| `cosmokit` | 通用工具集 |
| `schemastery` | 类型驱动的 schema 校验器 |
| `dsh-brand` | Branded\<B\> 名义类型原语 |
| `dsh-timeout` | 零依赖超时/截止时间原语 |
| `dsh-atomic-write` | 零依赖原子文件替换（临时文件 + 重命名） |
| `dsh-native-command` | 零依赖无 shell execFile 运行器 |
| `dsh-output-retention` | 有界保留原语（保留/省略提示） |
| `dsh-scope` | 作用域上下文注册与过滤分发 |
| `dsh-invariants` | 包级运行时不变量注册服务 |
| `dsh-shell-env` | 工具无关的 DSH_* 环境变量注册表 |
| `dsh-launch-environment` | 不可变启动环境（记录各值的来源层） |
| `dsh-cmdline` | 启动器到应用插件的不可变命令行交接 |
| `dsh-home-paths` | 共享文件系统路径助手 |
| `dsh-time-context` | 每步当前时间/耗时上下文 |
| `dsh-tmux-context` | 每步 tmux 面板/窗口位置上下文 |
| `dsh-anonymous-user-id` | 匿名用户身份（遥测/反馈关联） |

### 2.2 CLI 与启动装配（5 个）

| 包 | 作用 |
|---|---|
| `dsh` | dsh CLI：profile 启动、插件管理、浏览器 UI 别名 |
| `dsh-app-boot` | 应用 bin 的共享启动胶水（.env、Loader 守卫、配置解析） |
| `dsh-base` | 共享 dsh 核心 profile 包（首个补丁层） |
| `dsh-headless` | 无 Host/HTTP/浏览器的直接 Agent/Session 一次性运行器 |
| `dsh-persona` | 组合式部署 persona 配置段 |

### 2.3 抽象能力缝（ctx.* seam）及实现（约 100 个）

> 设计模式：每个能力缝定义抽象接口 + 事件词汇，再配「本地实现」与「沙箱加强实现」。

#### 文件系统
- `dsh-fs`：抽象文件系统缝（文本 IO + 版本守卫原子变更 + fs/* 策略事件）
- `dsh-fs-local`：本地文件系统实现
- `dsh-fs-sandbox`：沙箱强制实现（按调用级沙箱模式围栏写/编辑）
- `dsh-fs-observation-policy`：文件上下文策略（observed-state、读前编辑、版本守卫）

#### Shell / PowerShell
- `dsh-shell`：抽象 bash 执行器缝
- `dsh-bash-local`：本地子进程实现
- `dsh-bash-sandbox`：沙箱消费实现（每条命令经 ctx.sandbox 限制）
- `dsh-pwsh-local`：本地 PowerShell 实现
- `dsh-pwsh-sandbox`：沙箱消费的 PowerShell 实现

#### 沙箱
- `dsh-sandbox`：抽象进程沙箱缝（同世界限制词汇 + SandboxProvider 契约）
- `dsh-sandbox-local`：本地后端（bwrap / landlock-run / macOS Seatbelt / Windows ACL，探测后 fail-closed）
- `dsh-sandbox-policy`：按调用解析沙箱模式与当前模型上下文
- `dsh-sandbox-windows-acl`：Windows ACL 受限令牌写限制后端
- `node-addon-landlock-run`：Linux Landlock 自限制后 exec 启动器（预编译二进制 + JS 缝）

#### 子进程 / 终端
- `dsh-subprocess`：抽象子进程缝（进程组、有界 spill 输出、升级终止）
- `dsh-subprocess-local`：本地实现
- `dsh-terminal`：持久 PTY 会话缝（owner 作用域 id、后端注册表、交互收发、信号、清理）
- `dsh-terminal-bash`：基于 subprocess 终端原语的持久 shell PTY 后端

#### 任务 / 存储 / 溢出
- `dsh-jobs`：后台任务注册表（共享 id、owner 隔离、轮询、取消、完成监听）
- `dsh-jobs-local`：进程内实现
- `dsh-storage`：存储中心（命名后端注册 + data-form 设施）
- `dsh-storage-domain`：域数据形式（schema 校验、事件发射 KV 域）
- `dsh-storage-json`：JSON 文件 KV 后端
- `dsh-spill`：溢出存储缝（超大工具文本落盘并返回定位符）
- `dsh-spill-local`：本地文件实现（私有 session 级文件）
- `dsh-spill-policy`：工具结果溢出策略（保留预览 + spill 文件路径）
- `dsh-attachment`：持久不可变附件存储缝
- `dsh-attachment-local`：DSH_HOME 内容寻址附件存储

#### 设置 / 凭据 / 授权
- `dsh-settings`：抽象用户设置缝
- `dsh-settings-file`：settings.yaml 文件后端
- `dsh-credentials`：抽象凭据缝（设置引用密钥、provider 持有值）
- `dsh-credentials-local`：文件凭据 provider（$DSH_HOME/.env）
- `dsh-authorization`：授权缝（与人类对话获取凭据的插件化流程）
- `dsh-user-approval`：用户批准缝（一次性权限决策，fail-closed）
- `dsh-permission-presets`：用户权限预设（沙箱模式 + 审批策略打包）
- `dsh-user-questions`：代理运行中向人类提问的抽象缝

#### 会话体系（15 个）
- `dsh-session`：事件溯源会话存储
- `dsh-session-persistence` / `dsh-session-persistence-jsonl`：抽象持久化缝 + JSONL 后端
- `dsh-session-query` / `dsh-session-query-sqlite`：会话查询服务 + SQLite FTS5 后端
- `dsh-session-projection` / `dsh-session-projection-cache`：投影类型表/提供者契约 + 持久投影缓存
- `dsh-session-reference`：跨会话快照引用与持久不可信模型上下文
- `dsh-session-stats`：会话统计投影（消息数、墙钟时间）
- `dsh-session-telemetry` / `dsh-session-telemetry-otel`：遥测缝 + OpenTelemetry 后端
- `dsh-session-title` / `dsh-session-title-llm` / `dsh-session-title-first-prompt-llm`：标题服务 + LLM 生成
- `dsh-session-checkpoint-policy`：模型请求/工具副作用前语义持久检查点
- `dsh-session-log-export`：Web 会话日志导出命令

#### LLM
- `dsh-llm`：provider 无关 LLM 服务接口
- `dsh-llm-deepseek`：DeepSeek chat-completions 适配器
- `dsh-llm-pi-ai`：pi-ai 后端适配器（设计验证孪生）
- `dsh-llm-retry`：provider 路由的 LLM 重试策略

#### Web 能力
- `dsh-web`：抽象 Web 访问缝（搜索/抓取 provider 注册表、请求/结果词汇、WebError 分类）
- `dsh-web-search-deepseek`：DeepSeek 原生 web_search 搜索 provider

#### 工作流 / 子代理 / 代理
- `dsh-workflow`：工作流能力缝（ctx.workflowEngine 服务、run 词汇、workflow/* 事件）
- `dsh-workflow-worker-thread`：worker 线程工作流引擎（承载模型编写脚本，agent() 桥回 ctx.subagents）
- `dsh-subagent`：抽象子代理缝（命名 provider 注册表）
- `dsh-subagent-spawn-in-process`：进程内全新子代理后端
- `dsh-subagent-fork-in-process`：进程内 fork 子代理后端（继承父日志前缀）
- `dsh-subagent-in-process-driver`：共享进程内运行驱动
- `dsh-agent`：代理接口、注册表、发起作用域、事件词汇
- `dsh-agent-loop`：具体代理循环插件
- `dsh-agent-presets`：按 preset cordis.yml 组装每会话代理
- `dsh-agent-default-model`：默认模型选择
- `dsh-agent-instructions`：AGENTS.md/CLAUDE.md 指令文件加载器
- `dsh-agent-tool-presentation`：工具呈现选择器（Code Mode / 原生 / 两者）

#### 代码执行 / 其他能力
- `dsh-code-runtime`：抽象代码执行缝（ctx.codeRuntime）
- `dsh-code-runtime-worker-thread`：worker 线程实现
- `dsh-mcp-client`：MCP 客户端桥（连接 MCP 服务器并注册工具到 ctx.tools）
- `dsh-file-reference` / `dsh-file-reference-local`：@file 引用发现契约 + 本地模糊索引实现
- `dsh-typert-loader` / `dsh-typert-protocol` / `dsh-typert-registry`：Typert 加载器 / Remote 协议元数据 / 运行时注册表
- `dsh-system-prompt`：系统提示词组装注册表
- `dsh-plan-mode`：日志式每代理计划模式（斜杠命令 + 用户审阅退出）
- `dsh-goal`：事件溯源同会话目标状态与生命周期服务
- `dsh-goal-round-driver`：竞态围栏目标轮驱动
- `dsh-schedule`：agent 作用域持久提醒（after/at/fixed-rate）
- `dsh-compaction` / `dsh-compaction-basic` / `dsh-compaction-tool-result-pruner`：压缩缝 + token 计量策略 + 工具结果修剪
- `dsh-token-meter`：回放感知 token 计量服务
- `dsh-message-feedback`：消息评分/备注 sidecar
- `dsh-repeat-tool-reminder`：重复工具调用守卫
- `dsh-tool-call-timeout-policy`：工具调用超时策略
- `dsh-workspace`：工作区实体注册表
- `dsh-commands`：插件拥有的命令注册表 + `dsh-command-compact/feedback/goal` 斜杠命令
- `dsh-skill` / `dsh-skill-badge` / `dsh-skill-filesystem`：技能 provider 注册表 + 内置技能
- `dsh-cordis-client-runner` / `dsh-cordis-host-runner` / `dsh-tool-cordis`：动态双半插件包（浏览器/宿主）与自省工具集
- `dsh-api-gateway` / `dsh-api-remotes`：Typert Remote Host 分发 + 远程 BFF 装配

### 2.4 模型工具层 dsh-tool-*（21 个）

| 包 | 作用 |
|---|---|
| `dsh-tools` | 工具注册表与执行管线 |
| `dsh-tool-bash` / `dsh-tool-bash-persistent` | bash 工具 + 持久 PTY 版 |
| `dsh-tool-pwsh` / `dsh-tool-pwsh-persistent` | PowerShell 工具 + 持久 PTY 版 |
| `dsh-tool-fs` | 读写编辑工具（基于 ctx.fs） |
| `dsh-tool-fs-search` | glob/grep 发现工具（内置 ripgrep） |
| `dsh-tool-str-replace-editor` | 视图/创建/字面替换/行插入工具 |
| `dsh-tool-web` | web_search / web_fetch |
| `dsh-tool-goal` | 目标工具（执行时权限校验） |
| `dsh-tool-jobs` | job_output / job_list / job_kill |
| `dsh-tool-todo` | todo_write |
| `dsh-tool-skill` | 技能加载 |
| `dsh-tool-ask-user` | ask_user_question |
| `dsh-tool-subagent` / `dsh-tool-subagent-control` / `dsh-tool-subagent-report` | 子代理委托 / 全局命名控制 / 子作用域报告 |
| `dsh-tool-ralph` | 全新代理 Ralph 循环 |
| `dsh-tool-workflow` | 工作流编排脚本工具 |
| `dsh-tool-cordis` | cordis 运行时自省与动态插件挂载 |

### 2.5 Host 服务端（8 个）

| 包 | 作用 |
|---|---|
| `dsh-host-apiproxy` | API 网关（ApiProxy 契约 + fetch 载体 + 网关插件） |
| `dsh-api-gateway` | Typert Remote Host 分发与 Client API 端点 |
| `dsh-api-remotes` | 远程 BFF 装配与 Host Agent/Session 查找策略 |
| `dsh-host-webserver` | HTTP/upgrade 路由注册 + index 变换 + 静态回退 |
| `dsh-host-frontend-static` | SPA dist 服务器（遍历拒绝、404 处理） |
| `dsh-host-plugin-inventory` | Cordis Loader 插件状态只读投影 |
| `dsh-host-directory-picker` (+auto/browse/native) | 目录选择缝 + 自适应/浏览/原生 OS 后端 |

### 2.6 Web 前端（41 个）

**外壳与基础设施（8 个）**
- `dsh-web-app`：浏览器面 bundle（web 补丁层 + 运行时胶水：dist 分发、web 面提示、bash 运行变量、URL 行）
- `dsh-web-frontend`：Vite 构建入口（apps/cli 的 dsh web 服务的 dist）
- `dsh-client-connection`：HTTP-up/WebSocket-down 双流连接层
- `dsh-client-hmr`：开发期热重载驱动（SSE → 失效/预取 → fiber 交换）
- `dsh-client-locale`：中英文 locale 插件
- `dsh-client-modules`：客户端模块系统（node 侧拼装 __DSH_BOOT__ 入口图；浏览器侧懒 CJS 模块表）
- `dsh-client-runtime`：SlotRegistry、SessionRuntime（作用域树 + 对象层）

**界面插件 dsh-client-ui-*（33 个）**
- 会话域：`conversation`（骨架/有序聊天流/composer）、`trajectory`（事件台账 + 时间概览）、`deliverables`（产物文件尾部）、`message-feedback`（消息反馈控件）、`input-trigger`（'/' '@' 触发管线）、`user-questions`（提问 UI）、`model-selection`（/model 选择）
- 布局与主题：`layout`（三栏 AppFrame + 拖拽）、`sidebar`（会话树/搜索/分组）、`theme`（亮/暗/系统主题 + --dsw-* token）
- 设置域：`settings`（设置域基座）、`settings-general`（General 区 + 新手引导）、`settings-models`、`settings-plugins`、`settings-plugin-inventory`（Loader 清单只读页）
- 目标/计划/工作流：`goal`（GoalBar）、`plan`（计划模式 composer 控制）、`workflow-run`（持久工作流运行节点）
- 工具与技能：`tool`（调用树渲染）、`cordis`（动态插件定义卡片）、`skill`（技能引用）
- 会话管理：`subagent`（子代理目录/续接路由）、`agent-preset`（代理预设表面）、`reference`（@file/@session 引用源）、`attachment`（附件展示）、`brand-official`（官方品牌占位）
- 工作区与目录：`workspace`（工作区选择器）、`directory-picker-browse`、`directory-picker-native`
- 命令与权限：`commands`（'/' 命令面）、`permission-presets`（权限预设）、`jobs`（后台任务列表）

## 3. 架构解读（核心）

1. **「核心框架 + 能力缝」分层**：以 cordis 插件框架为底座，每个外部能力（fs、shell、sandbox、subprocess、terminal、jobs、storage、spill、settings、credentials、session、llm、web、workflow、subagent…）都先定义**抽象缝**（`ctx.*` 服务 + 事件词汇 + provider 契约），再提供**本地实现**和**沙箱加强实现**两类后端。这使运行时可通过配置切换实现、按策略强制安全边界。

2. **沙箱优先的安全模型**：shell/fs/pwsh 均有 sandbox 版本实现（Windows ACL 受限令牌、Linux Landlock/bwrap、macOS Seatbelt），配合 `dsh-sandbox-policy` 按调用解析模式，外加 `dsh-user-approval` 的 fail-closed 审批与 `dsh-permission-presets` 用户可调预设。

3. **事件溯源 + 投影的会话架构**：会话以事件日志为唯一事实源（`dsh-session`），持久化（JSONL）、查询（SQLite FTS5）、投影及缓存、遥测（OTel）、标题、统计全部作为会话的派生视图，支持回放与检查点。

4. **模型工具与运行时解耦**：`dsh-tools` 是统一注册表/执行管线，`dsh-tool-*` 只做模型面适配，全部能力经 `ctx.*` 缝下沉——同一套工具可运行于本地、沙箱、无头、Web 等不同部署形态。

5. **双半（dual-half）动态插件**：`dsh-cordis-host-runner` / `dsh-cordis-client-runner` 支撑模型运行时动态定义插件包，宿主与浏览器各持一半，配合 `dsh-tool-cordis` 自省与热更新。

6. **宿主-客户端远程协议**：`dsh-api-gateway` + `dsh-api-remotes` + `dsh-client-connection` 构成 Typert Remote 通道，Host 侧（`dsh-host-*`）提供服务（静态分发、WebSocket、目录选择、插件清单），浏览器侧通过 `dsh-client-modules` 装配入口。

7. **统一交付物**：`dsh-base` 把核心装配成 profile 补丁层，`dsh-web-app`/`dsh-headless`/`dsh` 分别是 Web 面、无头面、CLI 面的同一核心的三类外壳。
