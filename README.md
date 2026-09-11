# rag-lab

> RAG 链路实测的配套实验仓库(CSDN「RAG 链路实测」专栏)。一个仓库,四个实验:每篇文章对应一组可复现实验,数据、脚本、结果全量入库或一条命令拉取。

| # | 文章 | 实验 | 状态 |
|---|---|---|---|
| 1 | [RAG 分块策略实测](https://blog.csdn.net/weixin_39885962/article/details/164459646) | 10 篇中文技术文 × 100 题 × 9 组分块配置 | v1.1 已发布 |
| 2 | [RAG 重排序实测](https://blog.csdn.net/weixin_39885962/article/details/164712425) | DuReader-retrieval 93,885 段落 × 500 真实查询 × 召回/重排对照 | v1 已发布(2026-09-09) |
| 3 | [RAG 生成层实测](https://blog.csdn.net/weixin_39885962/article/details/164747501) | CMRC2018 dev 3,219 题 × 三档上下文 × Qwen2.5-7B 生成 | v1 已发布(2026-09-09 16:20;6,208 次生成,AutoDL RTX 4090D 跑批) |
| 4 | [RAG 评测可信性实测](https://blog.csdn.net/weixin_39885962/article/details/164858910) | 6,208 次生成 × 四组 LLM 裁判(提示词三档 / 双模型规模 / 人工锚点),13,708 条打分 | v1 已发布(2026-09-10;13,708 条裁判输出,AutoDL RTX 4090D 跑批) |
| 5 | RAG 查询路由实测 | DuReader 93,885 段落 KMeans 聚 4 域 × 五组路由(不路由/BM25/嵌入Top-1/嵌入Top-2/LLM),455 条可计分 query | v1 成稿(2026-09-11,待发布;本机 CPU 跑批) |

## 实验一:分块策略实测

用 10 篇中文技术长文做语料,100 道题做测试集,对比 3 种分块策略 × 3 种粒度共 9 组配置的检索命中率。

- **语料**:10 篇中文技术长文(DeepSeek Harness 实测 ×4 / ARC-AGI-3 harness / DseWiki 数据实拉 / SkillSpector 扫描 / GLM 对比 ×2 / Code Review 规范重写;已发布 7 篇、未发稿 3 篇),约 7.5 万字
- **测试集**:100 题,分 A 档(主题级)/ B 档(细节级),ground truth 标到文章级
- **固定量**:bge-small-zh-v1.5 嵌入 / Chroma 向量库 / top-k=5 / overlap=50 字符
- **变量**:分块策略(固定窗口 / LangChain 递归切分 / Markdown 结构感知)× chunk 大小(256 / 512 / 1024 字符)

```bash
pip install -r requirements.txt
python src/run_eval.py                        # 跑全部 9 组配置(CPU 每组 10~15 秒)
python src/run_eval.py --config configs/recursive-512.json   # 单组
python src/truncation_ablation.py            # 截断伪影对照(文章 2.5 节坑 1 的验证)
```

`corpus/` 与 `questions.jsonl` 已随仓库预置,clone 后可直接跑评测。`ingest.py` 是语料再生成脚本——其 MANIFEST 指向本机仓库外的源文件路径,对 clone 者预期 `[miss]`,无需运行。

## 实验二:重排序实测(DuReader-retrieval)

百度/BAAI 中文段落检索基准上的「双编码召回 → CrossEncoder 重排」对照实验。

- **数据**:DuReader-retrieval dev split(HuggingFace `zyznull/dureader-retrieval-ranking`),dev 候选池去重段落 **93,885 篇**(正例∪BM25 难负例),2000 条真实搜索 query 固定种子(42)抽 500 条,人工金标注
- **固定量**:召回 bge-small-zh-v1.5(与实验一同款),嵌入矩阵落盘 npz + numpy 精确余弦——9.4 万段落嵌入只算一次,重排实验换排序层不碰索引;实测 Windows + chromadb 1.5.9 的 PersistentClient 在进程退出后 HNSW 段不落盘、向量本体丢失,故改用精确检索(对 9.4 万×512 维规模秒级,且无 ANN 近似噪声)
- **变量**:重排(无 vs bge-reranker-base)× 候选深度 N(10/20/50)
- **观察**:Hit@1/5/10、MRR@10;失效归因(召回缺失 vs 排序错误);双 512 token 窗截断统计;CrossEncoder 分数当固定阈值过滤的实证;每查询延迟与模型体积成本口径

```bash
python src/download_data.py       # 从 hf-mirror 拉取 dev split(35MB,免鉴权)
python src/prepare_dataset.py     # 段落池 + 500 查询抽样(种子 42)
python src/build_index.py         # 嵌入 93,885 段落 → npz 向量矩阵(CPU 约 80 分钟)
python src/run_rerank.py          # 主评测:精确召回 → 重排 → 指标/归因/截断/延迟
python src/run_rerank.py --limit 50   # 冒烟
python src/run_rerank.py --resume     # 断点续跑:从 results/rerank_checkpoint.jsonl 跳过已算 query
```

`data/` 不入 git(DuReader 数据仅限研究用途,重分发口径存疑),clone 者跑 `download_data.py` 自取,口径与官方发布一致。模型自动从 hf-mirror 下载(国内直连)。

## 实验三:生成层实测(CMRC2018 端到端闭环)

把 RAG 链路末环走完:CMRC2018 中文抽取式阅读理解提供**字符级 offset 金标注**,答案就是原文连续片段,可用确定性 EM/F1 打分,规避 LLM-as-judge 的二次噪声。

- **数据**:HF `hfl/cmrc2018` validation split 3,219 条;每题含 `context/question/answers{text,answer_start}`;答案块是否命中由字符 offset 区间判定,不靠相似度近似
- **语料**:dev 全部 context 按实验一固定窗口 200 字符 / overlap 50 切块 → bge-small-zh-v1.5 向量落盘 `data/cmrc/cmrc_blocks.npz`
- **固定量**:生成模型 `Qwen/Qwen2.5-7B-Instruct`、temperature=0(贪婪)、单上下文 ≤ 8,000 字符、查询带 bge 检索前缀
- **变量**:上下文三档构造
  - **Oracle·位置效应**:答案块放开头/中间/末尾(其余为本文档真块按原文序填充),doc_chunks≥3 子集是干净的位置效应主表
  - **Oracle·噪声注入**:答案块固定置首,掺 0/1/3/5 个高相似干扰块(bge top-20 非本文档块)
  - **RAG 全链路**:bge 检索 top-10 直接拼上下文,记录 gold 是否命中
- **主表**:固定种子(42)抽 800 题,三档合计约 6,000 次生成(全量 3,219 题可用 `--full`)

```bash
# 1. 数据准备(AutoDL 或本地都可跑,CPU 即可)
python src/prepare_cmrc.py --limit-docs 40    # 本地冒烟
python src/prepare_cmrc.py                    # 全量 800 题抽样 + bge 索引

# 2. 生成跑批(需 GPU;本地无卡可用 --engine transformers --cpu 小样本冒烟,极慢)
pip install vllm                              # AutoDL 上单独装,镜像 PyTorch 2.x 已带 torch
export HF_ENDPOINT=https://hf-mirror.com
python src/run_generate.py --mode all         # 三档全跑(vLLM 自动)
python src/run_generate.py --mode all --resume # 断点续跑

# 3. 打分汇总
python src/score_em_f1.py                     # 输出 results/cmrc_gen_metrics.json + 打印分层表
```

`data/cmrc/` 不入 git(CMRC 数据可从 hf-mirror 直拉)。vLLM 在 Windows 本地通常无法安装,`--engine transformers --cpu` 仅用于小样本冒烟验证代码链路;正式跑批请用 AutoDL 等 Linux GPU 实例。

### 实测结果(2026-09-09 AutoDL)

跑批实录:AutoDL RTX 4090D 24G,固定种子 42 抽 800 题,三档合计 **6,208 次生成**,耗时约 **53 分钟**。当时 AutoDL 最新 PyTorch 镜像(torch 2.13.0)与 pip 默认 vllm(0.28.0)存在 `import` 冲突(`AssertionError: duplicate template name`,`auto` 引擎自动回退),实际以 transformers 引擎跑完;速度约 0.5 s/次,`--resume` 可中途续跑,对结果无影响。

**位置效应**(doc_chunks≥3 均衡主表,每组 608 题):

| 位置 | n | EM | F1 |
|---|---|---|---|
| top | 608 | 5.6% | 51.5% |
| mid | 608 | 5.3% | 49.8% |
| bottom | 608 | 5.6% | 48.8% |

EM 三档几乎持平,F1 自头至尾单调下降 2.7pp。位置影响弱:对"是否找对答案"基本无差别,只对"复述完整度"有轻微代价。

**噪声干扰**(干扰块数 0/1/3/5,每组 800 题):

| 干扰块 | n | EM | F1 |
|---|---|---|---|
| 0 | 800 | 10.9% | 58.2% |
| 1 | 800 | 7.6% | 53.9% |
| 3 | 800 | 6.0% | 51.9% |
| 5 | 800 | 4.1% | 49.4% |

单调无反转:平均每多 1 个高相似干扰块 EM 跌约 1.4pp、F1 跌约 1.8pp。干扰数量是本实验最稳定的生成损伤因子。

**端到端 RAG**(bge top-10,800 题):

| 分组 | n | EM | F1 |
|---|---|---|---|
| 命中金块 | 681(85%) | 3.8% | 48.5% |
| 未命中 | 119(15%) | 0.0% | 21.3% |
| 全部 | 800 | 3.3% | 44.5% |

检索命中率 85%,但未命中组的端到端 EM 直接归零、F1 腰斩(21.3%)——检索层约 15% 的 miss 是生成层无法补救的硬损耗,与实验二结论互相印证。

## 实验四:评测可信性实测(LLM-as-judge)

实验三用确定性 EM/F1 衡量回答质量,但工程上更常用 LLM 当裁判。本实验把「裁判本身可不可信」当实验对象:同一批生成结果,换提示词、换模型规模、对照人工锚点。

- **数据**:实验三 6,208 次生成结果(3,219 题固定种子抽 800 题的完整三档),按 `(qid, gen_variant)` 与生成结果逐条对齐成裁判评估集
- **变量**:
  - **提示词三档**:bare(直接判) / rubric(给评分标准) / cot(先推理再判),各 1,600 条(oracle_noise 子集)
  - **裁判模型**:Qwen2.5-7B-Instruct(主) / Qwen2.5-14B-Instruct-AWQ(对照),同 rubric 档 2,400 条共有样本
  - **人工锚点**:wrong / abstain / partial / high_f1_low_em / perfect 五类各 60 条,共 300 条
- **口径**:裁判输出「0~5 分 + 对/错判定」,`score>=4` 记「对」,再与 EM 口径对照(混淆矩阵 / 一致率 / kappa / F1 分档相关性)

```bash
python src/align_judge_set.py      # 裁判评估集:与实验三结果逐条对齐
python src/run_judge.py            # 四组裁判跑批(需 GPU;AutoDL vLLM/transformers)
python src/score_judge.py          # 指标汇总 → results/judge_metrics.json
python src/analyze_judge_cases.py  # 自洽性/一致性/分档分析 + 裁定表/小结 → results/judge_cases.md
                                   # 同时生成离线复核工作表 → results/judge_review_checklist.md
```

`data/cmrc/judge_set.jsonl` 不入 git(含 CMRC 原文与金标),跑 `align_judge_set.py` 自取,口径与实验三一致。

### 实测结果(2026-09-10)

四组裁判共 **13,708 条**打分,零解析失败(`parse_fail=0`)。

**① 提示词决定分数尺度,而非判定方向**(oracle_noise 子集,n=1,600):

| 提示词 | 均分 | 与 EM 一致率 | 自洽矛盾率 |
|---|---|---|---|
| bare | 4.257 | 89.9% | **4.88%** |
| cot | 4.223 | 93.7% | 0.69% |
| rubric | 4.018 | 94.5% | **0.25%** |

最反直觉的一点:bare 均分**最高**,一致率却**最低**。对 bare 判定「对」但分数 <4 的 78 条做配对,换成 rubric 后 **78/78 判定一致**、均分从 **2.77 → 4.00**(全部 score=4,零方差)——判定方向没变,分数量尺被 rubric 顶到了满分。

**② 裁判对真实质量下降几乎不响应**(noise0 vs noise5,同题配对 n=800):

| 指标 | noise0 | noise5 | Δ |
|---|---|---|---|
| 裁判判对率 | 94.63% | 94.50% | **−0.13pp** |
| 字级 F1 | 58.22% | 49.44% | **−8.78pp** |
| EM | 10.87% | 4.13% | **−6.75pp** |

F1 掉 8.8pp、EM 掉 6.8pp,裁判判对率只动 0.13pp,翻转 27 vs 26(近乎对称)。判对率在 94.6% 附近**饱和、失去分辨率**。

**③ 双裁判一致性**(7B vs 14B,同 rubric 档,共有样本 n=2,400):

| 指标 | 值 |
|---|---|
| 原始一致率 Po | 92.92% |
| Cohen's kappa | 0.6217 |
| PABAK | 0.8583 |
| 2×2 | 都对 2,066 / 都错 164 / 7B错·14B对 24 / 7B对·14B错 146 |

**④ 分歧源于「模糊度」而非「严格度」**——把 78 条配对按 F1 分档看 14B 翻案率,呈**非单调**(中间高、两端低),峰值在中段:

| F1 区间 | n | 14B 判对 | 翻案率 |
|---|---|---|---|
| [0, 0.2) | 28 | 22 | 21.4% |
| [0.2, 0.5) | 37 | 24 | **35.1%** |
| [0.5, 1.01) | 13 | 12 | 7.7% |

最烂的一档两个裁判反而高度一致地判「对」——EM/F1 判它错、两个模型都判它对,**严格口径下的假阴性占 28/78**。所以 7B/14B 差异不是「严格度差一档」,而是「对模糊答案的容忍阈值不同」。

**⑤ 复现噪声地板 1.25%**:同提示词、同模型、同批样本跑两遍(main-rubric vs prompt-rubric,n=1,600),判定不同 3 条(0.19%)、分数不同 20 条(1.25%)。bare 的 4.88% 是它的 3.9 倍,分数尺度差异是真实效应而非跑批抖动。

**⑥ 人工锚点校准**(5 类 × 60 条,方向性校准):

| 类别 | 均分 | 判对率 |
|---|---|---|
| perfect | 4.87 | 100% |
| high_f1_low_em | 4.55 | 100% |
| partial | 4.12 | 100% |
| wrong | 1.18 | 18.3% |
| abstain | 0.00 | 0% |

锚点区分度成立,方向全对。但 `high_f1_low_em`(EM=0 而 F1=0.946)被判满分——裁判与 EM 在「复述完整但字面不等」上的分歧是系统性的。

**⑦ 分歧案例逐条裁定**(21 条,明细见 `results/judge_cases.md` 第 10/11 节;可离线逐条勾选的空白工作表见 `results/judge_review_checklist.md`):

切片 = 7B 判对 / 14B 判错 16 条 + 双判对但 F1<0.2 的 5 条,按「同题同答」去重后 21 条逐条判读:

| 项 | 值 |
|---|---|
| 裁定 对 / 错 | **21 / 0** |
| 类别 | A 冗余无害 17、C 非冗余分歧 4(换述/更具体/金标不全/子串) |
| EM=0 占比 | **21/21** |
| 与裁定一致 | 7B-bare 21/21、7B-rubric 21/21、**14B 5/21** |

14B 的 16 次「判错」**无一命中**;21 条 EM 全为 0,严格口径在这批上假阴性率 100%。极端标本 #17(`DEV_1157_QUERY_1|noise0`):金标「澳洲球队」vs 答案「FC悉尼及阿德莱德联」,**字面零重叠(EM=0、F1=0.000)**,但答案比金标更具体且事实正确,三方裁判全判对。4 条非冗余分歧中,`DEV_192_QUERY_1|noise0` 暴露**金标不全**(只记「水属性」,暴鲤龙实为水/飞行)。

⚠️ **抽样偏倚**:该切片以「7B 判对」为入样条件,「全部判对」是选样属性,**不能外推为 14B 的整体误报率**,只能作为「14B 在该批报警中零命中」的下界证据;反方向证据见 `judge_cases.md` 第 3A 节(wrong 层 F1≤0.05 却被判对的 11 条 = 裁判漏检)。

## 目录

```
corpus/                  实验一语料(规范化 md + corpus.jsonl 元数据)
questions.jsonl          实验一测试集(100 题,含 A/B 档标注)
questions-frag-*.jsonl   实验一出题分片(合并前的工作文件,留档复现测试集构建)
configs/                 实验一 9 组实验配置(3 策略 × 3 粒度)
data/                    实验二数据(gitignored: DuReader 原始包+解析产物+持久索引)
data/cmrc/               实验三数据(gitignored: CMRC 原始包+解析产物+bge 索引)
data/cmrc/judge_set.jsonl  实验四裁判评估集(gitignored: 与实验三结果逐条对齐后的样本+问/金/答)
src/ingest.py            实验一语料清洗入库(剥系列导航行/状态注记行)
src/chunkers.py          实验一三种分块策略实现 + 代码块切断统计
src/merge_questions.py   实验一题库分片合并 + 结构校验 + 跨篇撞题检查
src/run_eval.py          实验一主评测:分块→嵌入→检索→指标
src/truncation_ablation.py  实验一截断伪影对照:fixed-1024 保头 vs 保尾 510 token
src/download_data.py     实验二数据拉取(hf-mirror,免鉴权)
src/prepare_dataset.py   实验二解析:段落池 + 查询抽样(固定种子)
src/build_index.py       实验二建索引:bge-small → npz 向量矩阵落盘
src/run_rerank.py        实验二主评测:精确召回 → 重排 → 指标/归因/截断/延迟
src/prepare_cmrc.py      实验三:CMRC 切块+offset 金标+bge 索引+800 题抽样
src/run_generate.py      实验三:三档上下文 × vLLM/transformers 生成跑批(支持 --resume)
src/score_em_f1.py       实验三:字级 EM/F1 分层汇总与归因
src/align_judge_set.py   实验四:裁判评估集构造(与实验三结果逐条对齐)
src/run_judge.py         实验四:四组裁判跑批(main / prompt 三档 / judge2 / anchor)
src/score_judge.py       实验四:裁判指标汇总(混淆矩阵/一致率/kappa/F1 分档相关性)
src/analyze_judge_cases.py  实验四:自洽性/一致性/分档分析 + 人工裁定表 + 复核清单
src/make_judge_figures.py   实验四:四张配图 + 数字摘要 → results/writing/exp4/
src/make_route_domains.py   实验五:KMeans 聚类构造知识域 + 确定每条 query 的真实域
src/run_route_eval.py       实验五:五组路由对照跑批(不路由/BM25/嵌入Top-1/嵌入Top-2/LLM)
src/score_route.py          实验五:路由准确率 / 端到端 / 误路由代价(盈亏平衡点)
src/make_route_figures.py   实验五:三张配图 + 数字摘要 → results/writing/exp5/
results/results.json     实验一跑批结果(指标 + 失效案例逐题存档)
results/rerank_results.json  实验二跑批结果
results/rerank_checkpoint.jsonl 实验二逐条 checkpoint(断电/关机后 --resume 续跑用)
results/cmrc_gen.jsonl       实验三逐条生成结果(含上下文构造元信息)
results/cmrc_gen_metrics.json 实验三分层指标汇总
results/autodl训练结果-20260909/  实验三 AutoDL 下载件归档(cmrc_gen.jsonl + metrics)
results/judge_scores.jsonl    实验四逐条裁判打分(13,708 条 × 四组)
results/judge_metrics.json    实验四裁判指标汇总(分组混淆矩阵/分档/相关性)
results/judge_cases.md        实验四案例分析(自洽性/一致性/分档/裁定表+小结,1~11 节)
results/judge_adjudication.json  实验四裁定结果(21 条;改该文件后重跑分析脚本自动回填)
results/judge_review_checklist.md 实验四裁定复核离线性工作表(逐条问/金/答+三方理由+空白勾选+誊清区,脚本生成)
results/autodl训练结果-20260910/  实验四 AutoDL 下载件归档(远端旧版 md 存证)
results/writing/             写作辅助产物(逐题案例 cases.json / 宽松口径 lenient.json / figures)
results/writing/exp4/        实验四写作辅助产物(figures 四张配图 + summary.json 数字摘要)
results/writing/exp5/        实验五写作辅助产物(figures 三张配图 + summary.json 数字摘要)
results/route_eval.jsonl     实验五逐条结果(455 条 × 五组)
results/route_metrics_full.json 实验五指标汇总(含误路由代价与盈亏平衡点)
data/route/                  实验五知识域产物(gitignored: 由 make_route_domains.py 本地生成,段落→域映射 + 簇质心)
```

## 指标口径

实验一:Hit@1 / Hit@5 / MRR@5,按 A/B 档分层,ground truth 在文章级。实验二:Hit@1/5/10、MRR@10,金标注在段落级,top-k 含 ≥1 正例记 hit。实验三:字级 EM(规范化后与答案逐字相等)/ F1(答案与预测的字集重合),按位置三档(top/mid/bottom)、噪声四档(noise0/1/3/5)、RAG 命中/缺失分层;CMRC 为抽取式任务,只测"从上下文定位并复述答案",不与纯 MRC leaderboard 直接对比。三者均为小样本诚实口径,报分层观察,不做显著性检验;实验二语料池为 dev 候选池(非 866k 全库),MRR 不与官方 leaderboard 直接对比。实验四:裁判输出「0~5 分 + 对/错」,`score>=4` 记「对」,与 EM 口径对照给一致率/混淆矩阵,另报 Cohen's kappa 与 PABAK 校正偶然一致;噪声敏感度用同题配对差值;人工锚点 5 类各 60 条仅作方向性校准,同样不做显著性检验。提示词三档实验仅覆盖 oracle_noise 子集(1,600 条),结论不外推到 pos/rag 语境。

## License

MIT。实验一语料为本人原创文章,测试集随语料同授权;实验二数据来自 DuReader-retrieval(百度/BAAI),经 `download_data.py` 自 hf-mirror 拉取,遵循其原始许可(研究用途);实验三数据来自 CMRC2018,经 `prepare_cmrc.py` 自 hf-mirror 拉取,遵循其原始许可(研究用途);实验四复用同一数据(经 `align_judge_set.py` 对齐),许可同上。
