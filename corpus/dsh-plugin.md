# DSH 插件开发实录：我让 agent 现场给我写了个"AI味检测器"


---


上一篇拆完 DeepSeek Harness(下称 DSH)的"一切皆插件"，留了个尾巴：真给它写一个插件，门槛到底多高？这次我把答案跑出来了。先交代背景：插件有两条路——会话内的动态 Cordis 插件(现场写、热加载、重启就没)和落盘的自定义 preset(改配置文件、重启还在)。官方对这两条路各配了一份 skill 文档，一个 420 行，一个 165 行，都在 cordis 预设的 skills 目录里，装完就能看。

为了省事，我全程用的是 `dsh --profile headless "任务"` 这个无界面模式——一行命令，agent 跑完任务打印结果退出。这个模式有个好处：所有输出天然就是终端留痕，写文章直接抄。

赶时间的话，一句话版本：两条路都跑通了，踩了 7 个坑，2.2 元学费换来 1 个 patch、1 个插件、1 套核验方法。细节都在下面。

然后，开工不到十分钟，我就撞了第一堵墙。

## 一、第一堵墙：headless 里根本没有插件开发工具

这事官方文档没明说，我是跑挂了才知道的。

动态插件的开发工具(`cordis_define`、`cordis_run` 这些)不是一个独立命令，而是 agent 会话里的工具，由 `dsh-tool-cordis` 这个插件行提供。而这个行挂在 cordis 预设里——headless 模式压根不挂任何预设。

我是用 `--dump-config` 对比发现的：把 headless 和 web 两个 profile 的组合树各自导出来，web 里赫然有 `dsh-cordis-host-runner`、`dsh-agent-presets`、`dsh-tool-cordis` 三行，headless 里一行都没有。也就是说，你照着任何教程在 headless 里让 agent "用 cordis_define 创建插件"，它只会一脸懵——它手里没这个工具。

解决办法不是换回 Web UI，而是给 headless 动个小手术。DSH 的 profile 是分层组合的：bundle 层打底，你的 `cordis.patch.yml` 盖上面，`--patch` 参数还能再加临时层。格式照抄 dsh-headless 包自带的 patch 样例，照猫画虎写了三行：

```yaml
- insert:
    - id: cordis-host-runner
      name: '@deepseek-ai/dsh-cordis-host-runner'
    - id: agent-presets
      name: '@deepseek-ai/dsh-agent-presets'
      config:
        default: standard
    - id: tool-cordis
      name: '@deepseek-ai/dsh-tool-cordis'
```

注意那个 `default: standard`——我第一版没写，boot 直接报错 `$.default missing required value`。这个必填项是 web profile 的组合树里查出来的，报错信息只说缺，不说该填什么，得自己翻。

跑一下 `--dump-config | grep cordis`(Windows 上 grep 得在 Git Bash/WSL 里跑，PowerShell 用户换 `Select-String cordis`)，三行都挂上了，手术完成。顺带说一句，这个手术能成立有个前提：`dsh-tool-cordis` 这个包零 dependencies、仅有 peer 依赖，peer 包全部躺在共享的 `~/.dsh/profiles/node_modules` 里。这个前提我也是查了 package.json 才敢动手的——插件化架构的好处在这兑现了：工具是插件，插件是包，包都在本地，插上就能用。

这里帮后来者对一下字段，免得照抄时怀疑自己抄错：dump 输出里看到的是包名(name，`@deepseek-ai/...` 开头那种)，patch 里写的 id(`cordis-host-runner` 这种)是你在组合树里给这一行起的标识符，name 才是指向包的指针——两个都写，一行才算定义完整。

## 二、第二个发现：坑、账与诚实

万事俱备，给 agent 下任务：写一个 `article_checkup` 工具，输入一篇文章，输出体检报告——总字数、阅读时长、超长句列表，外加 AI 腔用语检测(词表我都拟好了：首先/其次/总而言之/综上所述/值得注意的是……对，就是你想的那种)。

第一次跑，EXIT 0，漂亮。打开日志一看，好家伙：agent 写了个叫 `pulse_check` 的脉冲插件——接收一个 message，原样回给你，外加插件存活时长。这不是 hello world 嘛。我让它写体检工具，它给我交了个"证明插件能跑"的最小实现？

骂早了。后来我解包会话记录核数据，把任务原文提出来对了一眼——我那段几百字的需求，agent 一个字都没收到。Git Bash 里长中文文本走命令行传参，会在某个字节处静默截断——它实际收到的任务只有开头一句"安装并激活一个动态 Cordis 插件，然后当场验证它"。就这 20 个字，pulse_check 不叫糊弄，叫合理交付。

第二次跑，我把"不许用最小实现交差"写进任务，又失败了。agent 的回复很有意思，原样翻译过来大概是："你说的那个插件我已经不记得了——动态插件定义只存在于进程内存中，进程重启就没了(文档原话：definitions do not survive a process restart)。而且你这次任务里只保留了'别糊弄'这句提醒，正式需求是什么，我这边没有记录。我不想凭空编一个需求出来，那比最小实现更糟。你把需求再说一遍？"

后来解包才知道，这次的任务原文同样被截断，以"……最小实现交差："的冒号结尾，冒号后面的正文全丢了。agent 说的每一个字都是实话：它真不记得，也真没收到。

一是 headless 每次命令都是全新进程，上下文不延续，所以**动态插件开发必须单会话一气呵成**——需求、定义、激活、自测，全部塞进一次任务里。二是这 agent 的"诚实"是真好用：不知道就说不知道，绝不编。这个特质后面还救了我一次，在第四节的验证环节，着急的话可以先跳过去看。

第三次学乖了，不再跟命令行传参较劲：需求写进一个 md 文件，让 agent 自己读。但这里我又欠了一笔：因为前两次的截断，我这次发给它的任务只有 170 字——工具名、参数、一句"功能就是中文文章体检"，拟好的词表和测试文章忘了塞回去。agent 拿到的规格就这么点，于是它从零发明了整个体检标准，连 AI 腔词表都是自己拟的。

这次它真写了 article_checkup——从 pkg-1 改到 pkg-7，前 6 版全被报错打回：缺 run、缺 parameters、schema 不对、缺 `additionalProperties`……第 7 版才通过。它的总结里有一条最值钱：它通过一次次报错，逆向校准出了 `harness.defineTool` 的精确契约——`parameters` 是个字段映射而不是 JSON Schema 的 `{type:'object'}`,`output.schema` 必须显式写 `additionalProperties: false` 而且不支持 `required` 字段。这些细节，420 行的官方 skill 里没写全。

代价是烧钱。这几个回合下来，净输入就有 46 万 token、输出 9.7 万——而这还只是新 token：每开一次 headless，系统提示词、skill 目录、插件树全要重进一遍上下文，缓存重读同样计入消耗。整个项目的账单最终是 271 次 API 调用、1169 万 token、2.2 元，大半就烧在 A 路径这几轮试错上。教训有两条：任务文本一次写全，别指望多轮调教；长文本别走命令行传参，写进文件——这是本文用真金白银换来的、官方文档不会告诉你的那条。

## 三、插件长什么样

agent 最终写出来的插件，核心结构就这么多(节选，完整代码我放在文末)：

```js
return {
  name: 'article-checkup',
  apply(ctx) {
    const tool = harness.defineTool({
      name: 'article_checkup',
      description: '对一篇中文文章进行体检:统计汉字/总字数、检查常见风格问题与超长句,返回结构化体检报告。',
      parameters: {
        text: { type: 'string', required: true, description: '要体检的中文文章全文。' }
      },
      output: {
        schema: { type: 'object', additionalProperties: false },
        render: renderResult
      },
      async execute(args) {
        // 统计、检测、评分逻辑
        return { ok: true, summary: {...}, issues: [...], advice: '...' };
      }
    });
    return harness.registerTool(ctx, tool);
  }
};
```

纯 JavaScript，不用编译，不用 JSX,`execute` 里想干啥干啥。有个设计值得说：工具定义里 `execute` 管计算，`render` 管展示——模型看到的返回值和 UI 上看到的卡片是分开的。这个分离在 Claude Code 的 tool 定义里没有对应物，写惯了 OpenAI function calling 的人需要适应一下。顺带点一个命名细节：插件名 `article-checkup` 用短横线、工具名 `article_checkup` 用下划线，两个命名空间各走各的，照抄时最容易混的就是这里。

另外交代一个"货不对板"的实情。第二节说过，第三次任务因为截断缩水成 170 字，拟好的"首先/其次/总而言之"词表压根没送达，agent 只好自己拟——它拟的是"坚决/重要指示/不单坘申明制度"三个，坘，生僻字，它连这个都编得出来。连超长句阈值也是它定的 120 字。严格说这两张词表不是同一路货：我拟的是 AI 语篇起承转合词，它拟的是官腔套话——但这个工具要抓的本来就是套话、空话、模板化表达，广义上都归"AI 腔"，我认这个账。

所以标题里那个"AI 味检测器"，实物比设计缩了水，而账要算在我头上：规格没送到，人家只能自由发挥。

还有个好消息：纯 Host 插件不需要审批。官方文档说 Client 端(浏览器侧)的插件包要用户在 Web UI 里勾选授权(`awaiting-approval` 状态)，但我的插件只跑在 Host 侧，没有浏览器代码，激活直接就过了。这也是我全程 headless 能跑通的原因——如果写的是 UI 插件，绕不开 Web UI 那一下勾选。

至于插件去哪了——重启进程，没了。我专门起了个新会话验证，agent 查了半天，报告说 `plugins: []`，插件确实随进程消失了。官方管这个叫 process-local，定位就是"探针"和"试验"，不是分发形态。要持久化，走第二条路。

## 四、第二条路：自定义 preset，三十分钟的事

动态插件会消失，想让 agent 长期带上"写作模式"怎么办？答案是 preset——上一篇文章讲过，DSH 没有独立的配置语言，一个 agent 的全部能力就是它的 `cordis.yml` 里那几行插件行的组合。所以"定制一个 agent"="复制一份 preset，改几行"。

流程简单到不好意思多写：

1. 把官方 standard 预设的目录复制到 `~/.dsh/.agent-presets/writer/`(standard 是全功能预设，copy 它最稳——官方 skill 原话："从零写的组合通常会忘了 group realm 或 consumer row，复制的起点天然可加载")
2. 改 `preset.yml`：名字"写作模式"，一句话描述
3. 改 `agent.cordis.yml` 的 persona 行，加几行：写作前先体检、贴国内开发者文风、禁用 AI 腔用语、关键论断必须带数字——就这四条

然后是验证。这里差点又栽在同一个坑上：我一开始照旧用命令行传参发任务，agent 收到的又是半截文本——"两件事，按顺序完成："冒号后面全没了。它没有瞎猜，直接停下来问我两件事是什么。这就是第二节说的那个"诚实"——它要是编了两个任务做掉，我大概要到验收才发现，那才是真翻车。我这才彻底死心，把任务写进 md 文件让 agent 自己读——从此再没截断过。

验证用的标准姿势来自那份 165 行的官方 skill(`~/.dsh/profiles/node_modules/@deepseek-ai/dsh/config/agent-presets/cordis/skills/editing-cordis-compositions/`):让 agent 挂一个临时插件，注入 `agentPresets` 服务，调 `standingKeyFor('writer')`——它会真实挂载整棵插件子树走一遍，四类常见错误全会在这步现形:包找不到、配置不合法、行没激活、服务泄漏到全局。我的验证会话返回 `MOUNT_OK standingKey={"agentPreset":"writer"}`,一次过。roster 也能看到它:trust 标为 `user`,区别于系统自带的 `system`,路径指向我放的位置。

会话最后我让它以"写作模式"的身份写一段 150 字的 preset 介绍——看输出，四条人设要求全踩住了，没有 AI 腔，没超长句。persona 生效，这条路走通了。

这一趟的成本：预设文件是我自己写的，agent 只做验证，两次会话合计输出 8.9k token，几毛钱。比动态插件的反复试错便宜一个量级。

## 五、所以，插件开发的真实门槛在哪

两条路跑完，给个不吹不黑的评估。

**比 Claude Code 写 skill 难吗？**难，但难的地方不一样。写 Claude Code 的 skill，你是在给一个固定宿主"投喂"内容——目录放对、格式写对就能跑，不会的就是不会。写 DSH 插件，你是在改宿主本身，天花板高得多(agent loop、模型路由、上下文压缩全都能换)，但代价是你得懂 Cordis 的世界：`inject` 声明依赖、realm 隔离、Host/Client 两个平面、不可变 Package 版本管理——这些概念 420 行 skill 里全有，但没人替你消化。

**几个具体的坑，提前说：**

- headless 用户先补 cordis 工具链，不然第一步就卡死(本文第一节)
- 动态插件单会话一气呵成，需求写全，别多轮调教(第二节，真金白银的教训)
- 长中文任务别走命令行传参，Git Bash 下会静默截断——写进 md 文件让 agent 自己读(第二节，本文最大的坑，我连栽三次)
- `harness.defineTool` 的 schema 有自己的方言，报错信息比文档可靠，让 agent 自己踩着报错校准——我这轮它迭代了 7 版才收敛(第三节)
- 任务文本要锁死细节参数(词表、阈值这类)，没送到的规格 agent 会自己发明(第三节的实情)
- 纯 Host 插件免审批，带 UI 的绕不开 Web UI 勾选
- preset 从 copy 开始，别手搓(第四节)

**什么人现在就该上手：**想给 agent 写工具链的、在企业内部搞 agent 平台的、想研究插件化 harness 架构的——就我目前见过的项目里，这是这方面最好的活教材，`--dump-config` 一导，整棵树摊开给你看，每个包的源码就在 node_modules 里躺着。

**什么人再等等：**只想白嫖一个稳定 CLI 工具的。它还在 rc 阶段，官方加粗警告过会有破坏性变更，今天写的 patch 明天可能就得改。

回到上一篇标题那个问题："Everything is a Plugin"到底是新范式还是新命名？上一篇我说一半一半。这一篇跑完，我的看法往"新范式"挪了一格——因为这次我真把一个能力插进去了，而且整个过程：改配置能插、写代码能插、连"给 agent 开发插件的工具"本身都是插件(我那三行 patch 插的就是它)。这种自指的完整性，我目前还没见到第二家。

代价也写在明面上了：8 次 headless 运行(外加一次会话内派生的 research 子代理)、271 次 API 请求、共 1169 万 token——账单拆开看，92.8% 是缓存命中：每开一次新进程，系统提示词、skill 目录、插件树就原样再读一遍，这部分按缓存价计入消耗，是 headless 模式成本的大头。实付 2.2 元，买的全是教训，值。

2.2 元买不来一个能用的 AI 味检测器，但买得来上面这七个坑。下一个想试的，拿去。

---

## 数据核验说明

本文定位是实录，所以数据核验过程也如实交代。全部素材来自 2026-09-02 当日的实跑：8 次 headless 运行(日志 8 份，`dsh_run_*.log`)+ 1 个会话内派生的 research 子代理 = 9 份 `session.jsonl` 原始会话记录；环境 Win11 + DSH 0.1.1-rc.2 + deepseek-v4-flash(思考关闭)。

文中数字有两个来源，口径不同，别混着对：

- **平台账单口径**(总量):271 次 API 调用、11,690,833 token，实付 2.2 元。三方拆分：命中缓存 10,844,288 / 未命中输入 714,214 / 输出 132,331，缓存占 92.8%。
- **会话记录解包口径**(净量)：逐份解包 9 个 session.jsonl 统计得净输入 543,426 / 输出 106,001，插件迭代 pkg-1 至 pkg-7 共 7 版。这个口径不含子代理等未落盘请求，所以比账单的"未命中输入 + 输出"小——差值(约 17 万输入 + 2.6 万输出)就是没落盘的部分。
- 第二节的"净输入 46 万 / 输出 9.7 万"是 A 路径 7 个会话的解包子集，不含 B 路径两次验证会话。

完整插件代码和手术 patch 见文末附录。

## 附录 A：手术 patch 完整内容

```yaml
- insert:
    - id: cordis-host-runner
      name: '@deepseek-ai/dsh-cordis-host-runner'
    - id: agent-presets
      name: '@deepseek-ai/dsh-agent-presets'
      config:
        default: standard
    - id: tool-cordis
      name: '@deepseek-ai/dsh-tool-cordis'
```

用法：存成 `patch-cordis.yml`，临时挂载跑 `dsh --profile headless --patch patch-cordis.yml "任务"`；要持久化就把 insert 段直接抄进 `~/.dsh/profiles/headless/cordis.patch.yml`，每次 boot 自动生效。持久化之后验证就别再带 `--patch` 了——insert 是追加语义，同一层理论上会叠两遍，这个坑我没实测，也没必要试——直接跑 `dsh --profile headless --dump-config | grep cordis`，看到三行就成。

## 附录 B:article_checkup 插件完整代码

```js
return {
  name: 'article-checkup',
  apply(ctx) {
    function isHan(ch) { return ch >= '一' && ch <= '鿿'; }
    function isPunct(ch) {
      return `,.;:!?。，．；：！？、《》“”‘’（）〔〕—…`.indexOf(ch) !== -1;
    }

    const cliche = ['坚决', '重要指示', '不单坘申明制度'];

    function renderResult(args, result) {
      if (!result || result.ok === false) {
        return [{ type: 'text', text: (result && result.message) ? result.message : '体检失败' }];
      }
      const issues = (result.issues || []).map(function (i) {
        return ' [' + i.level + '] ' + i.type + ': ' + i.detail;
      }).join('\n');
      const text = '评分: ' + result.summary.score
        + ' 可读性: ' + result.summary.readability
        + ' 汉字: ' + result.summary.hanChars
        + ' 句子: ' + result.summary.sentences
        + (issues ? '\n问题:\n' + issues : '\n无明显问题')
        + '\n' + result.advice;
      return [{ type: 'text', text: text }];
    }

    const tool = harness.defineTool({
      name: 'article_checkup',
      description: '对一篇中文文章进行体检:统计汉字/总字数、标点、句子数、段落数,检查常见风格问题与超长句,算出基础可读性指标和评分,返回结构化体检报告。',
      parameters: {
        text: { type: 'string', required: true, description: '要体检的中文文章全文。' }
      },
      output: {
        schema: { type: 'object', additionalProperties: false },
        render: renderResult
      },
      async execute(args) {
        const text = (args && typeof args.text === 'string') ? args.text : '';
        if (!text.trim()) return { ok: false, message: 'text 不能为空' };

        const hanChars = text.split('').filter(isHan);
        const totalChars = text.replace(/\s/g, '').length;
        const punctCount = text.split('').filter(isPunct).length;
        const sentences = text.split(/[。！？…]+/).filter(function (s) { return s.trim().length > 0; }).length;
        const paragraphs = text.split(/\n{1,}/).filter(function (p) { return p.trim().length > 0; }).length;

        const issues = [];
        for (const w of cliche) {
          if (text.indexOf(w) !== -1) {
            issues.push({ type: '风格', level: '提示', detail: '含套话/空话表达"' + w + '",建议置换为具体内容。' });
          }
        }
        const longSent = text.split(/[。！？…]/).filter(function (s) {
          return s.split('').filter(isHan).length > 120;
        });
        if (longSent.length) {
          issues.push({ type: '句式', level: '提示', detail: '含 ' + longSent.length + ' 个超过 120 字的超长句,建议拆分。' });
        }

        const avgSentenceLen = sentences > 0 ? hanChars.length / sentences : 0;
        let readability = '通畅';
        if (avgSentenceLen === 0) readability = '无法评估';
        else if (avgSentenceLen > 60) readability = '偏难';
        else if (avgSentenceLen > 35) readability = '中等';
        const score = Math.max(0, Math.min(100, Math.round(100 - issues.length * 4 - Math.max(0, (avgSentenceLen - 25)) * 0.8)));

        return {
          ok: true,
          summary: {
            hanChars: hanChars.length,
            totalChars: totalChars,
            punctuation: punctCount,
            sentences: sentences,
            paragraphs: paragraphs,
            avgSentenceLen: +avgSentenceLen.toFixed(1),
            readability: readability,
            score: score
          },
          issues: issues,
          advice: issues.length
            ? '发现 ' + issues.length + ' 项问题,建议进行后续人工审改。'
            : '未发现明显问题,文章基本顺畅。'
        };
      }
    });

    return harness.registerTool(ctx, tool);
  }
};
```

> 注：这版代码是 agent 在 A6 会话现场写的最终版(pkg-7)，从会话存档(article-checkup-code.md)原样抄录。词表和超长句阈值是 agent 自己拟的，原因见第二节和第三节末尾——第三次任务因截断缩水成 170 字，规格没送达。词表第三个词"不单坘申明制度"不是笔误，坘(dǐ)，生僻字，agent 自拟词表时连这个都编得出来。谁也别替我"改错"。
