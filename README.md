# rag-lab

> RAG 链路实测的配套实验仓库(CSDN「RAG 链路实测」专栏)。一个仓库,两个实验:每篇文章对应一组可复现实验,数据、脚本、结果全量入库或一条命令拉取。

| # | 文章 | 实验 | 状态 |
|---|---|---|---|
| 1 | [RAG 分块策略实测](https://blog.csdn.net/weixin_39885962/article/details/164459646) | 10 篇中文技术文 × 100 题 × 9 组分块配置 | v1.1 已发布 |
| 2 | [RAG 重排序实测](https://blog.csdn.net/weixin_39885962/article/details/164712425) | DuReader-retrieval 93,885 段落 × 500 真实查询 × 召回/重排对照 | v1 已发布(2026-09-09) |
| 3 | RAG 生成层实测(未发布) | CMRC2018 dev 3,219 题 × 三档上下文 × Qwen2.5-7B 生成 | 脚本已就绪,待 AutoDL 跑批 |

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

## 目录

```
corpus/                  实验一语料(规范化 md + corpus.jsonl 元数据)
questions.jsonl          实验一测试集(100 题,含 A/B 档标注)
questions-frag-*.jsonl   实验一出题分片(合并前的工作文件,留档复现测试集构建)
configs/                 实验一 9 组实验配置(3 策略 × 3 粒度)
data/                    实验二数据(gitignored: DuReader 原始包+解析产物+持久索引)
data/cmrc/               实验三数据(gitignored: CMRC 原始包+解析产物+bge 索引)
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
results/results.json     实验一跑批结果(指标 + 失效案例逐题存档)
results/rerank_results.json  实验二跑批结果
results/rerank_checkpoint.jsonl 实验二逐条 checkpoint(断电/关机后 --resume 续跑用)
results/cmrc_gen.jsonl       实验三逐条生成结果(含上下文构造元信息)
results/cmrc_gen_metrics.json 实验三分层指标汇总
```

## 指标口径

实验一:Hit@1 / Hit@5 / MRR@5,按 A/B 档分层,ground truth 在文章级。实验二:Hit@1/5/10、MRR@10,金标注在段落级,top-k 含 ≥1 正例记 hit。实验三:字级 EM(规范化后与答案逐字相等)/ F1(答案与预测的字集重合),按位置三档(top/mid/bottom)、噪声四档(noise0/1/3/5)、RAG 命中/缺失分层;CMRC 为抽取式任务,只测"从上下文定位并复述答案",不与纯 MRC leaderboard 直接对比。三者均为小样本诚实口径,报分层观察,不做显著性检验;实验二语料池为 dev 候选池(非 866k 全库),MRR 不与官方 leaderboard 直接对比。

## License

MIT。实验一语料为本人原创文章,测试集随语料同授权;实验二数据来自 DuReader-retrieval(百度/BAAI),经 `download_data.py` 自 hf-mirror 拉取,遵循其原始许可(研究用途);实验三数据来自 CMRC2018,经 `prepare_cmrc.py` 自 hf-mirror 拉取,遵循其原始许可(研究用途)。
