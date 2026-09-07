# DeepSeek Harness 上手实录：Everything is a Plugin 是新范式还是新命名？


---


9月1日早上照例刷 GitHub 情报的时候，我被一个数字吓了一跳：一个8月13日才建仓的项目，`deepseek-ai/deepseek-harness`，星数 206,587，fork 23,994。

19 天，20 万星。我的第一反应是：刷的吧。

因为我把前一天（8月31日）和当天（9月1日）的 GitHub Trending 日榜、周榜都翻了一遍——日榜 16 个、周榜 20 个仓库，里面压根没有它。一个 20 万星的项目不上趋势榜，这事本身就不对劲。

后来我把时间线对了一下才想明白。这里补一句背景：GitHub Trending 是官方的趋势榜，分日榜、周榜、月榜，排序看的是**这一周期内新涨的星数**，不是仓库总星数——所以一个 20 万星但本周没怎么涨的仓库，会输给总星数几千、但一周翻倍的新仓库。

DSH 的爆发期在 8 月中下旬、建仓后的头两周，本周增速已经回落，自然就掉出榜了——**热度峰值已经过去了，现在进场的人，吃的是第二波**。

但数据是真的。我用 api.github.com 逐项核验过：星数、fork 数、提交记录、发版记录，都是实抓的，不是营销号互相抄的那种"据外媒报道"。这是 DeepSeek 官方的开源项目，不是蹭名字的山寨货。

所以今天这篇文章，记录我把它完整装一遍、跑起来、拆开看了一遍的全过程。先说结论：**东西是真东西，但"Everything is a Plugin"这句口号，一半是新范式，一半是新命名。**往下看就知道我为什么这么拆。

## 一、它到底是什么

DeepSeek Harness（命令行叫 `dsh`）是 DeepSeek 官方开源的 agent harness，定位对标 Claude Code、Codex CLI 这一挂：起一个本地服务，接上模型，让 agent 读文件、跑命令、改代码。

官方 README 说它"构建于一切皆插件的架构之上，由 Cordis 驱动"。Cordis 是个 TypeScript 插件框架，背后有篇论文（《A Programming Paradigm for Spatiotemporal Composability》，arXiv:2608.25512），感兴趣的同学可以自己去翻。

几个我核实过的基本盘：

- 协议 MIT，商用无障碍
- 8月10日在 npm 发第一个版本，21天发了14个版本，最新 latest 是 `0.1.1-rc.2`，alpha 通道已经到 `0.1.2-alpha.3`（8月31日发的）
- **开发者预览阶段，官方 README 用加粗原话警告：未来将出现破坏兼容性的变更**
- 中文是一等公民：官方中英双README、整套中英双语文档，还建了企微群和微信公众号（README 里直接贴二维码）

最后这条对国内开发者挺重要的。DeepSeek 的 API 在 platform.deepseek.com，国内直连、人民币充值，不像某些工具从注册第一步就开始折腾你。

## 二、安装实录：我被 npm 坑了大半个小时

先说坑，这是本文可能对你最有用的部分。

README 给的安装方式极简单：

```sh
npx @deepseek-ai/dsh web
```

一行命令，默认起 Web UI 在 `http://127.0.0.1:3080`。看起来很美。

我实际执行的记录是这样的：

1. **直连 npm：**卡死。等了五分钟，啥也没装出来。
2. **换 npmmirror 镜像：**还是卡死，五分钟超时。
3. **挂代理重试：**元数据请求全部 200、速度也正常，但还是装不完。
4. **翻 npm debug 日志**，找到真相：不是网络问题，是**依赖树太大**。`@deepseek-ai/dsh` 这个包在依赖组装（`placeDep`）阶段爬了二十多分钟没爬完。

为什么依赖树这么大？原因要等第四节拆包时才看得清，这里先剧透结论：完整装下来是 447 个包，其中 197 个是 `@deepseek-ai/` 官方scope下的插件包。npm 的依赖解析在这种"宽而浅"的树上效率很差，pnpm 则快得多。

我最后用 Node 自带的 corepack 拉起 pnpm：

```sh
corepack pnpm add @deepseek-ai/dsh@latest
```

**一两分钟就装完了**（504 个包解析、447 个下载；差异来自部分依赖此前已存在于 pnpm store，无需重复下载）。同一台机器、同一个网络，npm 和 pnpm 的差距是"装不完"和"一两分钟"。

### 装完还差一步：pnpm 11 的构建白名单

启动前还有个坑，pnpm 11 默认禁止依赖跑安装脚本，`node-pty`、`koffi` 这些原生模块没编译。而且这个报错不只是警告——`dsh` 启动时自己会做一次依赖自检，自检失败直接拒绝启动。

我在 `pnpm-workspace.yaml` 里加了这么一段才通：

```yaml
dangerouslyAllowAllBuilds: true
```

（更稳妥的做法是用 `onlyBuiltDependencies` 列白名单，我只装个预览版偷了懒。但有个坑是确定的：package.json 里那个 `pnpm` 字段在 pnpm 11 已经不被读取了——官方警告里明说，我第一次就踩在这上面。中文资料里还没见人写过。）

## 三、跑起来

```sh
corepack pnpm exec dsh web --no-open
```

控制台输出一行：

```text
dsh web: http://127.0.0.1:3080
```

浏览器打开，标题栏就是 DeepSeek Harness。按官方文档的使用流：

1. **设置 → 模型**，填入 DeepSeek API 密钥保存，模型路由立即可用，不用重启
2. **选择工作区**，把启动 `dsh` 时所在的项目目录加进来选中
3. 发任务。Agent 能读写工作区文件、跑命令、维护计划；按权限策略，敏感操作会先弹审批

这里有个细节值得单独说：**PowerShell 是一等公民**。它的工具插件里 `dsh-tool-pwsh`、`dsh-pwsh-local`、`dsh-pwsh-sandbox` 是独立列出来的。用 Windows 写代码的都懂，某些流行 agent 工具在 Windows 上非要你配 bash 环境，那体验一言难尽。DSH 把 PowerShell 和 bash 平行做成了可插拔工具，至少在态度上是照顾 Windows 的。

## 四、拆包："一切皆插件"的成色

这是本文的核心。口号谁都会喊，我拆开 npm 包看了看到底是什么货色。

### 4.1 本体只有 120KB

`@deepseek-ai/dsh` 解压后 **119,971 字节，20 个文件**。一个对标 Claude Code 的东西，本体只有一个引导器。

它的依赖里，bash 工具是 `dsh-tool-bash`，PowerShell 工具是 `dsh-tool-pwsh`，MCP 客户端是 `dsh-mcp-client`，技能系统是 `dsh-skill`，上下文压缩是 `dsh-compaction-*`，token 计量是 `dsh-token-meter`，计划模式是 `dsh-plan-mode`，子代理是 `dsh-tool-subagent`，连 Web 界面都是 `dsh-web-app`——**每一个能力，都是一个独立的 npm 包**。

这正好回答了第二节留下的问题：为什么依赖树有 447 个包？因为"每个能力一个包"的架构，加上官方为每个工具都单独发版，`@deepseek-ai/` scope 下的插件包就有 197 个。npm 面对这种"宽而浅"的树，依赖解析效率很低；pnpm 用硬链接和更聪明的解析器，一两分钟就收工了。

拆依赖树时还有个意外发现：里面躺着 `@anthropic-ai/sdk`、Google GenAI 和 AWS Bedrock 的 SDK。也就是说"模型适配器也是插件"不是架构图上的空话，Claude、Gemini、Bedrock 的路由已经埋进发行包里了——配一个 DeepSeek key 开箱即用，想切别家也留着门。

CLI 自带四个官方预设（配置文件里的原文）：

| 预设 | 官方描述 |
|---|---|
| 极简模式 | 仅提供持久 bash 与 str_replace_editor 的双工具编码 Agent |
| PTC 模式 | 标准模式全能力，通过 Code Mode SDK 让模型用一个 TypeScript 程序组合多步操作 |
| 标准模式 | 功能完整，支持文件编辑、Shell、检索、Skills、计划、目标、子代理和工作流 |
| cordis | 官方名"创造模式"：用于创建自定义 Agent preset，具备标准模式的全部能力，并提供运行时检查、插件实验和 preset 创作指导 |

四个预设里最有意思的是最后一个。cordis 预设的配置注释写得很直白：它存在的意义，就是让一个人能够请 agent 写出另一个 agent——标准模式的工具原样保留，再加一套自我指涉的 Cordis 工具集。

官方也不回避风险，注释里专门有一段安全提醒：这个预设下的 `cordis_mount` 会在活着的运行时里执行模型写的 JavaScript，**"把这个预设下的会话当作 shell 访问来对待"**。敢把"agent 造 agent"做成官方预设，还把信任边界写得这么明白，这点我给好评。

### 4.2 真正有意思的：整棵树可以导出和替换

跑一下：

```sh
dsh --profile web --dump-config
```

它会把当前组装的完整插件树打印出来，节选几行大家感受下：

```yaml
# == @deepseek-ai/dsh-base
- id: llm
  name: '@deepseek-ai/dsh-llm'
- id: session
  name: '@deepseek-ai/dsh-session'
# == @deepseek-ai/dsh-base, patched by @deepseek-ai/dsh-web-app
- id: hmr
  name: '@deepseek-ai/cordis-plugin-hmr'
  disabled: true
```

注意那些注释行：每个条目都标了它来自哪个组合包、被谁 patch 过。运行中的 dsh 是一棵插件树，按"profile → 组合包 → 你的 patch"顺序叠加。装插件的命令是：

```sh
dsh plugin --profile web add <package>
```

它内部转发给 pnpm 装到你自己的 profile 目录里。

架构文档里有一句话我觉得值回票价：**"不存在需要打补丁的特权内核。"**连 agent loop 本身、模型适配器、会话日志都是插件，理论上任何一个都能被你的配置整个换掉。

这是和"在内核边上留个扩展点"完全不同的设计哲学：后者是"宿主固定、内容可换"，前者是"宿主本身也由插件拼成"。4.1 节看到的那棵 447 个包的大树，正是这套哲学的必然结果。

### 4.3 生态已经自己长出来了

再一个佐证：建仓两周内，第三方生态自己冒出来了——`awesome-dsh-plugin` 精选列表 13,907 星，`anywhere-labs/dsh-desktop` 桌面端 22,474 星，还有 Web 聚合端、路由套件各自几千星。我抽查了其中一个仓库的源码，README、CI、隐私声明俱全，不是空壳。

刷星可以刷出 20 万数字，刷不出 20 个带 CI 的下游仓库。**这就是我最终判断它不是刷榜的依据。**

顺带一提，Hacker News 上它反而很冷清，最相关的帖子最高也就个位数的赞。热度集中在 GitHub 和中文圈，英文社区还没跟进——对写技术内容的人来说，这是个时间差机会。

## 五、所以，新范式还是新命名？

我的答案分两半。

**"新命名"的那一半：**插件化架构不是它发明的。Cordis 框架早就存在，VSCode、Eclipse 这类"微内核+插件"的设计在软件工程里是教科书内容。把一个 TS 插件框架用在 agent harness 上，工程上漂亮，但理念上没有石破天惊。

**"新范式"的那一半：**把"LLM agent 的每一项能力"做成**独立分发、可整树替换、有官方背书的 npm 包**，这个组合确实没人做过。对比一下就清楚了：

- Claude Code 的插件和 Skills 本质上是**目录规范**——你往约定位置放文件，宿主程序加载。扩展的是内容，不是宿主本身。
- DSH 的插件是**进程内 Cordis 插件**——bash 工具、模型路由、上下文压缩策略，全都可以被拔下来换掉。扩展的是宿主本身的每一个器官。

打个比方：一个是给房子添家具，一个是房子本身由标准化模块拼的，你嫌哪个房间不顺眼可以整个拆了重拼。后者的工程天花板明显更高——代价是门槛也高，写个 DSH 插件你得先懂 Cordis。

再加一个变量：**DeepSeek 官方在做这件事，MIT 协议**。有背书的开放权重模型 + 有背书的开放 harness，这个打法对生态的杀伤力，参考 ollama 那几年就知道了。

## 六、风险和购买建议（免费的建议）

现在就该装的：

- 想研究 agent 架构、想给 agent 写插件的——这是目前最好的活教材，`--dump-config` 一导，整棵树摊开给你看
- 想省 token 钱的——DeepSeek API 定价摆在那，自己算账

建议再等等的：

- 想拿来当日常主力工具的——它在开发者预览期，**官方明说会有破坏性变更**，今天写的配置下周可能作废
- 网络不好且不想折腾 pnpm 的——npm 直装的实际体验我在第二节写得很清楚了

最后泼一盆冷水：20 万星里有多少会转化为长期贡献者，要看半年后。agent harness 这个赛道，DeepSeek 之外，Claude 插件生态、Apache maka（Apache 孵化器 podling，尚未成为顶级项目）、Cursor 开放插件规范全都压上来了，2026 年下半年会有一场淘汰赛。DSH 手里的牌是架构激进 + 官方背书 + 中文生态，短板是 alpha 稳定性和英文社区声量。

装一遍，拆一遍，你自己会有判断。

---

*本文数据（星数、fork、发版时间线、包体积）均为 2026-09-01 当日从 api.github.com 与 npm registry 实抓，安装与启动过程为本机实录。如果对你有帮助，点个赞或者收藏，后续我会跟一篇 DSH 插件开发实录。*
