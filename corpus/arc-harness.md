# 换个 harness,从 62.7% 到 99.9%:我拆开 ARC-AGI-3 的脚手架,还录下了它的"失忆"现场


---

> 本文是「agent 安全与评测」系列第 3 篇 · [上篇:DseWiki 逃逸 agents 数据实拉](TODO-发布后回填站内链接) · 下篇:待定

9 月 3 日,ARC Prize 公布了一组成绩,当天就把"harness(评测脚手架)"这个词顶上了风口:同一个模型(GPT-6 Astra),同一套游戏、同一套动作、同一套计分,仅仅换了个 harness,ARC-AGI-3 的成绩从 **62.7% 跳到 99.9%,成本反而从 $26K 降到 $19K**。

37 个百分点。一个模型的迭代挤破头也就涨几个点,这里换个"外围设备"就白拿 37 个。前一天,FrontierHarness 的评测刚给出"同一任务 harness 间 17 倍成本差";ARC 这边又补上一刀——连着两天,"harness 是超参"这件事被官宣了两次。

但我在动手复现之前,先把这个 benchmark 的源码拆了一遍,然后在 Windows 本机上跑了两组完整实验。结论先说:

1. **官方那组"62.7% vs 99.9%"的对照,其实不是一场公平的对照**——高分的那种 harness,目前只有 OpenAI 自己的 API 能跑;
2. **我录到了低分 harness 的"失忆现场"**——它每时每刻都在砍模型的记忆,砍完模型自己说"我一直在原地转圈";
3. 顺手,还有一条**免注册跑通整个评测的野路子**,中文读者 10 分钟可以复现。

下面挨个讲。

## 一、先弄清楚:两种 harness 到底差在哪

ARC-AGI-3 是个游戏化评测:agent 要在 25 个小游戏里摸索规则、通关拿分,每关有动作数预算。所谓 harness,就是包在模型外面的那一层循环——把屏幕内容喂给模型、拿回动作、执行、再把新画面喂回去。模型不动,harness 动。

官方仓库(arcprize/arc-agi-3-benchmarking)定义了两种:

**Standard(即 manual_rolling)**:provider 中立的纯文本历史。每一步,模型收到的上下文就是"之前所有轮次的文本记录"。跨步怎么携带知识?靠 system prompt 里的一句话——"把你想保留下来的上下文写进你的回复里"。也就是说,**所谓的"笔记",就是模型自己的回复全文**,没有任何独立的记忆区。

**Provider Adapter(即 continuous_conversation)**:使用服务商原生的会话状态。推理过程中产生的隐式思考,以加密形式存在服务端,跨请求携带,配上服务端的上下文压缩(compaction)。

一句话概括两者的机制差距:**一个靠模型自觉写笔记、装不下了就从最老的开始撕,一个靠服务商原生帮它记**。前者丢三落四是结构性的,后者几乎不丢。官方 README 还特意强调:"Both harnesses use the same games, actions, limits, and scoring."——同游戏、同动作、同上限、同计分,唯一变量是 harness。

听起来很严谨。问题出在我去核验源码的时候。

## 二、发现一:99.9% 的那条通道,只有 OpenAI 能进

翻 `model_config.py` 和 `runtime_registry.py`,几处硬编码把 Provider Adapter 的门关得很死:

1. `continuous_conversation` 状态强制要求请求里带 `store=false` + `include: ["reasoning.encrypted_content"]`,推理上下文和摘要都要设成 `auto`——这套参数是 OpenAI Responses API 的私有方言;
2. `SERVER_STATE_RUNTIME_PAIRS = {("openai-python", "responses")}`——服务端会话状态(previous_response_id + compaction)**只存在于这一个 runtime 组合**;
3. 全仓唯一的 Provider Adapter 样例配置叫 `openai-gpt-5-6-sol-max-provider-adapter`,openai responses + effort max,名字已经把话说明白了;
4. Anthropic 侧的配置走的是 `anthropic-python + messages + manual_rolling`——也就是 Standard。

所以"62.7% vs 99.9%"的真实结构是:**所有人都能跑的 Standard,对比只有 OpenAI 端点能跑的 Provider Adapter**。官方叙事里"provider 中立 vs provider 原生"的技术对照,底下还压着一层 API 能力锁定——leaderboard 上,非 OpenAI 模型天生少一件武器。这不是阴谋,`reasoning.encrypted_content` 确实是 OpenAI 的能力,但一个标榜中立的评测把最高分钉死在单一厂商的私有特性上,这件事本身就值得警惕。

这也直接决定了我的实验设计:Provider Adapter 复现不了,那我就在 Standard 内部做文章——量化"记忆被砍"这件事到底有多惨。

## 三、实测:我用月费通道跑了个"失忆梯度"

### 3.1 环境:几个坑,和一条免注册通道

- 模型:doubao-seed-2-1-turbo,经方舟的 Anthropic 兼容端点接入。请求里写的 claude-sonnet-4-6,会被通道静默映射成 doubao——响应体的 model 字段里看得见,所以本文数据一律标 doubao。它不是这次的主角,就是个老实人。
- 游戏:cd82,25 个公开游戏里基线最短的一个(o3 全程基线 171 步通 6 关;六关各有动作预算,合计 855 步,其中第 1 关最宽松,单关 275 步)
- 唯一变量:`MAX_CONTEXT_LENGTH`,一组 175k(标准),一组 30k(极端压缩,模拟"更早丢状态")

搭环境时踩的第一个坑就能拦住一半人:`.env.example` 里的占位符 `your_arc_api_key_here` 会被当真 key 发出去,401。实际上这个评测**根本不用注册**:

```sh
curl https://three.arcprize.org/api/games/anonkey
# 返回 {"api_key":"..."},填进 .env 的 ARC_API_KEY 即可
```

匿名 key 解锁全部 25 个公开游戏。两个细节:key 会过期,401 了就重取一个;认证走的是 `X-API-Key` header,不是 Bearer。另外 Windows 用户还有一个坑——harness 把每步记录写盘时默认 GBK 编码,模型回复里出现 ✓ 这类字符就直接崩,启动命令前缀一个 `PYTHONUTF8=1` 可以免疫(这个坑崩掉了我 187 步的第一次长跑,后文会讲)。

### 3.2 Run 1:175k 上下文,187 步,失忆 178 次

先说成绩:**0/6 关**。doubao-seed 跑到 187 步(已经超过 o3 通关全程的 171 步),第 1 关还没过(该关预算 275 步)。这不意外——cd82 的规则需要摸索,基线模型和 o3 之间有差距。我关心的从来不是通关数,是 trim 计数器。

`Proactive context trim`,是 Standard harness 在上下文逼近上限时的自保动作:从最老的对话轮开始,整轮整轮地砍。日志里它的出现频率是这样的:

```text
14:06:27 | Proactive context trim: ~198069 tokens (limit 175000), 8 messages remaining.
14:06:27 | Proactive context trim: ~184892 tokens (limit 175000), 6 messages remaining.
14:06:27 | Proactive context trim: ~143016 tokens (limit 175000), 4 messages remaining.
```

同一秒,连砍三次。上一行还剩 8 条消息,下一行 4 条——模型在前几十步里积累的规则认知("按这个键有声音""这个格子会变色"),就随着这几行日志化为乌有。全程 187 步里触发了 **178 次 trim**,95% 的步骤都在砍记忆,上下文常年贴着 175k 的天花板,消息数被反复压回 12 条左右(平时是攒到十几条砍一轮;上面那种一秒连砍到 4 条的,是极端现场)。

这次 run 最终死于前述的 GBK 编码 bug(写盘崩溃,不是模型或网络的问题),187 步、input 15.5M tokens 的数据已经完整落盘。

### 3.3 Run 2:30k 上下文,把失忆推向极端

把上限压到 30k 再跑一次:**103 步,0/6 关,trim 103 次——100% 的步骤都在砍**,而且砍完只剩 2~4 条消息。模型第 9 步就开始说人话了:

```text
Assistant response: I've been going in circles. Let me try a completely different approach.
```

"我一直在原地转圈。"——它没说错,因为它的记忆每一步都被清到只剩当前画面。两组数据并排放:

| 指标 | Run 1(175k ctx) | Run 2(30k ctx) | o3 基线(官方) |
|---|---|---|---|
| levels completed | 0/6 | 0/6 | 6/6(171 步) |
| 步数 | 187(死于编码 bug) | 103(死于 ARC API 400) | 171 |
| input tokens | 15,548,813 | 1,780,314 | — |
| output tokens | 216,370 | 203,499 | — |
| 每步均 output | ~1.16k | **~1.97k** | — |
| trim 次数(占比) | 178(95%) | **103(100%)** | — |
| trim 后剩余消息 | ~12 条 | **2~4 条** | — |

(两组 run 均为中途死于非预算原因——Run 1 是本地写盘 bug,Run 2 是 ARC 服务端连续两次 400——所以步数和 token 总量不可直接对比;但 levels=0 的结局与 trim 计数不受影响。)

最有意思的行是"每步均 output":**上下文越小,模型每步被迫输出的 token 反而越多(1.16k → 1.97k,几乎翻倍)**。机制很直白——记忆被清空后,它每一步都得从零重新推理"这是什么游戏、我试过什么",把同样的思考重新写一遍。失忆不是省钱,是逼着模型一遍遍交重复的作业费。

这里得先交代:**我没有复现出"通关差距"**。两组都是 0/6,因为模型能力本身(doubao-seed vs GPT-6 Astra)是个巨大的混淆变量,我的实验只能验证"失忆机制与失忆梯度"——上下文越小,trim 越早越狠,模型越早陷入无头苍蝇循环——验证不了"失忆 → 少拿 37 分"这条因果链的最后一环。小样本(1 游戏 × 2 配置 × 1 模型),只能当方向性信号看。

## 四、把三块拼图合起来

现在回到开头那组官方数字,我拆完之后的完整读法是这样的:

**第一层,机制**。Standard harness 的"笔记"是一句 system prompt 的自觉,溢出时从最老开始整轮撕;Provider Adapter 的记忆是服务端加密状态加原生压缩。62.7% 到 99.9% 的 37 个点,埋在"模型每轮都在被清空记忆"和"模型几乎不丢任何状态"的结构差里。我的 Run 1/Run 2 是这个机制的第一手注脚:175k 也好 30k 也好,trim 都是常态而非意外——175k 只是让模型在两次失忆之间多活了一会儿。

**第二层,权力**。那条不丢记忆的通道,依赖 OpenAI Responses API 的私有特性(加密推理状态 + 服务端 compaction),源码里写死了只有 `openai-python + responses` 这一个组合能跑。于是在 ARC-AGI-3 的赛场上,非 OpenAI 模型不是"考得差",是**压根没有跑那条通道的选项**。当你下次看 leaderboard,看到某 OpenAI 模型一骑绝尘时,值得多想一秒:那里面有多少分属于模型,多少分属于脚手架,还有多少分,属于只有一家能提供的脚手架。

**第三层,方法论**。这件事对所有自己做 agent 系统的人都有直接含义:你的 agent 跑分不行、或者跑分贵,先别急着换模型——context 管理策略(manual rolling 还是服务端状态、trim 从哪里砍、笔记怎么存)是一等变量,官方自己已经用 37 个点和 $7K 的成本差给你做了 A/B 测试。动手优化之前,可以先打开 agent.py 里的 `_trim_to_fit_context` 数一数:同样的日志,在你的系统里,一小时会打几次?

对了,还有个更实在的账:Provider Adapter 不但分高,还便宜——$19K vs $26K。省下的 $7K 买的是什么?是服务端状态保留替代了模型一遍遍的重复推理输出。这跟我 Run 2 里"失忆越狠、单步输出越多"的观察正好对得上。

最后交代一下成本与复现:方舟 coding plan 是包月制,我这 290 步、1700 多万 input token 的双 run 没有增量美元成本,所以和官方 $26K/$19K 不构成对照。想自己复现的,套路都在第三节:匿名 key 一条 curl、`.env` 三个变量、`PYTHONUTF8=1` 一个前缀,照着走就能进游戏。跑的时候记得盯着日志里的 `Proactive context trim`——看一个 agent 三秒钟丢掉自己刚学会的规则,比任何论文都更能让你理解什么叫"harness 是超参"。

---

**数据与出处**

- 官方成绩与成本(62.7% / 99.9% / $26K / $19K):ARC Prize 博客,2026-09-03,arcprize.org/blog/astra
- 源码核验:arcprize/arc-agi-3-benchmarking(model_config.py / runtime_registry.py / agent.py)
- 自测数据:本文表格,双 run 完整日志与每步 recordings 存本机;scorecard:Run 1 arcprize.org/scorecards/29c3e4d3-c70f-4d62-b663-ff945bb88024,Run 2 arcprize.org/scorecards/0f109026-1ca6-49a0-a112-1b730539d041
- 自测模型为 doubao-seed-2-1-turbo(方舟通道),与官方使用的 GPT-6 Astra 不构成对比;自测部分为方向性信号,请勿与官方数字混同
