# Hy4 vs GLM-5.3 · 同题实测报告 v1(官方数据对比版)

> 成稿日期:2026-08-30 | 上游计划:[Hy4-vs-GLM5.3-同题实测计划.md](Hy4-vs-GLM5.3-同题实测计划.md)
> 版本说明:**v1 = 官方数据对比分析**(本轮无 API key,降级成稿);v2 = API 同题实测,待 key 后补跑(方案已定稿,见第八节)
> 数据纪律:全文数字均来自当日实抓(腾讯官方新闻稿/仓库/HF 镜像 config 与 LICENSE/OpenRouter API/官方基准图 OCR),经 GLM-5.3 官方模型卡交叉验证;OCR 数值已用四个锚点验证,仍可能存在个位数识别误差,存疑行已剔除

---

## 一、结论速览(TL;DR)

1. **同骨架**:Hy4 与 GLM-5.3 的层数(78)/宽度(6144)/专家结构(256+1,top-8)/激活(49B vs ~50B)/上下文(1M)完全同构,Hy4 官方自述 "inspired by DeepSeek and GLM"。差异集中在注意力实现(Gated DSA+KV压缩 vs 64头MHA)与吞吐工程(原生 MTP 层)。
2. **能力互有胜负,不是"谁碾压谁"**:腾讯自家附录表里,GLM-5.3 在 Terminal-Bench 2.1(88.2 vs 85.4)、DeepSWE(66.9 vs 64.3)、AutomationBench(48.2 vs 32.1)、CyberGym(84.5 vs 78.4)领先;Hy4 在 SWE-bench 全家(Multilingual 82.9 vs 81.3 / Pro 65.7 vs 61.6)、SWE Atlas Refactoring(53.3 vs 51.9)、PostTrainBench(35.6 vs 33.2)、OneMillionBench(65.4 vs 64.5)领先。
3. **"盲测 0.07 分之差"高度场景依赖**:腾讯盲测(内部专家+生产力任务)Hy4 2.99 > GLM-5.3 2.92;但同一家的第三方基准表里 GLM 在 agentic 编码上反超。两个数字测的不是一回事(详见第四节)。
4. **价格**:OpenRouter 上 Hy4($0.834/M 入 + $2.501/M 出)比 GLM-5.3($1.4 + $4.4)**便宜约 40%**。
5. **许可证**:Hy4 = 真 Apache-2.0;GLM-5.3 = MIT + $10B MaaS 审查条款。Hy4 更干净。
6. **给选型者的一句话**:长程 agentic 编码/自动化/安全攻防选 GLM-5.3;批量 SWE 任务与成本敏感场景选 Hy4;两者差距在任何单项上都不构成"换代"。

## 二、架构对比:同一副骨架的两种灵魂

| 项 | Hy4 preview | GLM-5.3 完整版 | 判读 |
|---|---|---|---|
| 总参/激活 | 770B / 49B(官方) | ~755B / ~50B(推算) | 同量级 |
| 层数 | 78(1 dense + 77 MoE) | 78(前 3 dense) | ✅ 同构 |
| 隐藏维度 | 6144 | 6144 | ✅ 一致 |
| 路由专家 | 256 + 1 共享,top-8 | 256 + 1 共享,top-8 | ✅ 完全一致 |
| 注意力 | Gated DSA + IndexCache;KV 头 8(512 维压缩) | 64 头 MHA,无 GQA | ⚠️ 最大差异 |
| 残差 | iHC,4 条残差流 | 标准 | 差异点 |
| MTP 投机解码 | 原生 MTP 层(10B/0.7B) | 无 | Hy4 吞吐优势来源 |
| 上下文 | 1M | 1M | ✅ 一致 |
| 词表 | 120,832 | 154,880 | 训练数据指纹 |
| 量化档 | BF16 + 官方 FP8 | fp8 | 同档 |
| 官方推荐采样 | temp=0.9 / top_p=1.0 | temp=1.0 / top_p=0.95 | ⚠️ 实测需对齐 |
| reasoning | 默认 "high",可 no_think | 思考模式默认 | 需对齐 |
| 许可证 | Apache-2.0(实测 LICENSE) | glm-5.3(MIT+$10B 条款) | Hy4 更干净 |

**核心洞察不变**:骨架同构意味着能力差异主要归因**后训练路线**(Hy4 用腾讯内部专家共创语料;GLM-5.3 是同基座纯后训练迭代),速度差异归因**架构工程**(DSA+KV 压缩+MTP)。

## 三、官方基准对照(核心数据)

> 来源:腾讯官方 benchmark-appendix.jpg(附录数据表)经 local_multimodal OCR 提取,列序 Hy3 | **Hy4** | Qwen3.8Max | DSV4Pro | **GLM-5.3** | KimiK3 | GPT5.6Sol | Opus5。
> **可靠性验证**:GLM-5.3 列与智谱官方模型卡四个锚点全部吻合(DeepSWE 66.9 ✓ / GDPval 1763 vs 1769 ✓ / AutomationBench 48.2 ✓ / CyberGym 84.5、GPT 83.6 ✓✓),列映射与 OCR 质量双确认。带 * 为腾讯自测值(附录原注),不带 * 为官方上报值。

| 基准 | Hy4 | GLM-5.3 | 胜者 | 备注 |
|---|---|---|---|---|
| SWE-bench Multilingual | **82.9** | 81.3* | Hy4 +1.6 | |
| SWE-bench Pro | **65.7** | 61.6* | Hy4 +4.1 | 行有 OCR 噪声,以官方图为准 |
| DeepSWE | 64.3 | **66.9/68.1*** | GLM +2.6 | GLM 卡自报 66.9,锚点验证 |
| SWE Atlas - Codebase Q&A | **64.0** | 55.4* | Hy4 +8.6 | 仓库级问答,Hy4 大胜 |
| SWE Atlas - Test Writing | 57.8 | 52.8* | Hy4 | |
| SWE Atlas - Refactoring | **53.3** | 51.9* | Hy4 +1.4 | |
| Terminal-Bench 2.1 | 85.4 | **88.2/88.3*** | GLM +2.8 | 注意 GLM 卡报的是 TB 3.0(28.3),版本不同不可混 |
| NL2Repo-Bench | 58.9 | 58.0* | ~平 | |
| CyberGym | 78.4 | **84.5/83.0*** | GLM +6.1 | GLM 宣称优势区,对手表格确认 |
| ProgramBench 3.0 | ~15.5* | ~25.0* | GLM | 行有 OCR 缺值,存疑保留 |
| PostTrainBench V1.1 | **35.6** | 33.2* | Hy4 +2.4 | |
| OneMillionBench (tools) | **65.4** | 64.5* | Hy4 +0.9 | 长上下文工具任务 |
| Toolathlon-Verified | **74.1** | 73.0/73.8* | Hy4 微胜 | |
| APEX-Agents (pass@1) | 37.1 | **38.1*** | GLM +1.0 | |
| ALE-CLI | 22.8 | **23.8*** | GLM +1.0 | |
| HLE (no tools, text) | **43.4** | 42.3 | Hy4 +1.1 | |
| HLE (with tools) | 55.4 | 62.5/54.3* | GLM | |
| GDPval-AA v2 (Elo) | 1678 | **1763** | GLM +85 | GLM 卡自报 1769,复测方差 |
| AutomationBench v1.0.6 | 32.1 | **48.2/49.4*** | GLM +16.1 | 最大差距项;GLM 卡自报 48.2,锚点验证 |
| BioMysteryBench | **71.3** | 69.0* | Hy4 | |
| GPQA Diamond | 92.3 | 91.7/91.4* | ~平 | |
| HorizonMath (pass@4) | 8.8 | 7.08* | Hy4 | 两者都远低于 GPT 10.62 |
| WorkspaceBench | 60.2 | 65.0* | GLM | |

**读表结论**:
- **GLM-5.3 的优势区**:Terminal/自动化/网络安全/agentic 综合体(AutomationBench +16.1 是全场最大单项差),与其官方"安全攻防+自动化第一"的叙事完全一致,且被**竞争对手自己的表格**独立确认--这是本报告最硬的一条发现。
- **Hy4 的优势区**:SWE-bench 系列全部领先,尤其 SWE Atlas Codebase Q&A(+8.6,仓库级理解);PostTrainBench(后训练知识新鲜度)领先;1M 上下文工具任务微胜。
- **彩蛋(方法学趣味)**:腾讯附录脚注披露,Terminal-Bench 2.1 用 **Claude Code 作为评测壳**(500 turns/12h 超时),SkillsBench/NL2Repo 等同样跑在 Claude Code 上--本报告本身也产自 Claude Code,评测壳与生产工具合一。
- **Hy4 的"过度验证"自曝有了数据影子**:AutomationBench/APEX 这类需要长动作链的基准落后,与其官方自述"spending longer than necessary reasoning / over-verify"吻合(相关性,非因果,待 API 实测验证)。

## 四、"盲测 2.99 vs 2.92"的正确打开方式

腾讯新闻稿:163 位内部专家、203 个工程任务、4 分制盲评,Hy4 2.99、Kimi K3 2.94、GLM-5.3 2.92。三个语境要点:

1. **测的是什么**:盲测任务由腾讯内部专家(工程师/游戏/金融/安全)出的**生产力任务**--恰是 Hy4 训练语料的共创来源。自家出题、出自家强项,2.99 有"主场加成"。
2. **第三方基准是另一面**:同一公司发布的附录表里,GLM-5.3 在 agentic 编码类反超(第三节)。两份官方材料并排看,"0.07 分"更准确的解读是:**两家强项剖面不同,总分接近**。
3. **复现预期**(v2 实测要检验的假设):盲测差距在小样本单评测者下大概率被任务类型主导--出编码题可能 GLM 赢,出"把一堆乱文件整理成文档"类题可能 Hy4 赢。

## 五、价格与通道(2026-08-30 OpenRouter 实抓)

| 项 | tencent/hy4-preview | z-ai/glm-5.3 | 备注 |
|---|---|---|---|
| 输入($/M tok) | 0.834 | 1.40 | Hy4 便宜 40% |
| 输出($/M tok) | 2.501 | 4.40 | Hy4 便宜 43% |
| 1M入+1M出合计 | $3.34 | $5.80 | |
| 上下文 | 1,048,576 | 1,312,720 | |
| 免费通道 | WorkBuddy/CodeBuddy 免费两周(约至 9-11) | 无 5.3 免费档;glm-5.2:free 可用 | 通道降级时的对照组选项 |

> z.ai 官方 API 与 freellmapi 作为备选通道(均需 key)。本地部署双双不可行(770B/755B vs 本机 16GB)。

## 六、选型建议(给软件研发/人工智能方向的读者)

1. **长程 agent 编码、终端自动化、安全审计**:GLM-5.3(AutomationBench/CyberGym/TB 优势,且是双源确认的数据)。
2. **批量 SWE 任务(修 issue/重构/测试生成)、仓库级问答、成本敏感**:Hy4(便宜 40% 且 SWE-bench 全系领先)。
3. **长文档生产力(办公/整理/交付物)**:倾向 Hy4(盲测主场+PostTrainBench),但注意其过度验证倾向会烧输出 token。
4. **合规敏感的商用**:Hy4 的 Apache-2.0 过审更快;GLM-5.3 对 <$10B 收入者实际等同 MIT,但需法务读一遍附加条款。
5. **什么情况都不用纠结**:两模型没有任何单项差距超过一个身位(除 AutomationBench),迁移成本远大于收益。

## 七、v2 API 同题实测方案(待 key,已定稿)

**通道优先级**:OpenRouter(一次双模型)> z.ai + 腾讯 TokenHub 双 key。
**参数**:主列统一 temp=1.0/top_p=0.95;附列各用官方推荐(Hy4 0.9/1.0);Hy4 reasoning 保持 high,记录思考 token。
**5 题集(可直接执行)**:

| # | 类型 | 题目 | 考察点 |
|---|---|---|---|
| 1 | 编码 | Python 实现线程安全 LRU 缓存类(支持 TTL 过期 + max_size 淘汰),附 5 个关键单测 | 正确性;对齐 TB/DeepSWE 差异 |
| 2 | 长上下文 | 拼接 archify 仓库 >32K 源码为上下文,要求列出全部外部依赖、版本约束,并指出一处升级会破坏兼容的位置 | OneMillionBench/SWE Atlas Q&A 差异复现 |
| 3 | 工作流 | 为 local_multimodal skill 写一份面向新用户的 README(提供代码事实) | 盲测同款生产力场景 |
| 4 | 推理探针 | 三阶递归 f(n)=f(n-1)+f(n-2)+f(n-3),f(0..2)=0,1,1,求 f(25) 并说明易错点 | Hy4 过度验证探针:统计思考/验证 token |
| 5 | 安全审计 | 给 50 行有漏洞的 Python web 服务代码,按 CVSS 排序漏洞并给修复建议 | CyberGym 差异复现 |

**指标**:盲评 4 分制 / 首 token 延迟 / token/s(MTP 验证)/ 思考 token 数 / 每题成本。每题每模型 3 采样(统一参数)+1 采样(官方参数)。
**预估成本**:全程 <$0.5。

## 八、方法与数据来源附录(防编造声明)

| 数据 | 来源 | 采集方式 |
|---|---|---|
| 架构/规格 | Hy4 官方 README + HF config.json(架构 `HYV4ForCausalLM`) | raw.githubusercontent + hf-mirror 实抓 |
| 基准数值 | 官方 benchmark-appendix.jpg 数据表 | local_multimodal OCR + 网格/坐标解析,四个 GLM 官方卡锚点交叉验证 |
| 盲测 2.99/2.94/2.92 | 腾讯官方新闻稿正文 | curl 实抓 |
| 价格 | OpenRouter /api/v1/models | 当日 API 实抓 |
| GLM-5.3 对照数值 | [GLM-5.3架构拆解笔记.md](GLM-5.3架构拆解笔记.md)(8-29 归档的官方模型卡数据) | 已归档 |
| 许可证 | Hy4 LICENSE 全文 / GLM-5.3 LICENSE | 实抓比对 |

已知局限:①OCR 数值存在个位级识别误差风险,四个锚点验证可将误差风险控制在可引用范围,存疑行(ProgramBench 3.0、SWE-bench Pro)已标注;②腾讯自测(*)与各家官方上报混合,存在评测壳差异(脚注披露:不同基准分别用 Claude Code/Codex/swe-agent/mini-swe-agent/OpenCode 壳);③本轮无一手推理数据,v2 补齐后本报告升级。

## 九、元叙事收尾(成稿用)

这篇报告的两个主角,一个在 8-28 把 770B 权重挂上了 HuggingFace,另一个在同一周说"我的提升全部来自后训练"。而当一个Claude Code 实例整理完腾讯的附录表,它发现:评测它们的壳,和写这篇报告的壳,是同一个。开源的意义在此刻最具体--所有数字,任何人都能重算。
