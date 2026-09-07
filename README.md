# rag-lab

> 中文技术博客语料上的 RAG 分块策略实测。配套文章:《RAG 分块策略实测:固定窗口 vs 递归切分 vs 结构感知,用 90 道题说话》(CSDN「RAG 链路实测」专栏第 1 篇)。

## 这是什么

用 9 篇中文技术长文做语料,90 道题做测试集,对比 3 种分块策略 × 3 种粒度共 9 组配置的检索命中率。不是教程,是一份带数字的评测报告。

- **语料**:9 篇中文技术长文(DeepSeek Harness 实测 ×4 / ARC-AGI-3 harness / DseWiki 数据实拉 / SkillSpector 扫描 / GLM 对比 ×2),约 7 万字
- **测试集**:90 题,分 A 档(主题级)/ B 档(细节级),ground truth 标到文章级
- **固定量**:bge-small-zh-v1.5 嵌入 / Chroma 向量库 / top-k=5 / overlap=50 字符
- **变量**:分块策略(固定窗口 / LangChain 递归切分 / Markdown 结构感知)× chunk 大小(256 / 512 / 1024 字符)

## 复现

```bash
pip install sentence-transformers chromadb langchain-text-splitters
python src/ingest.py                          # 语料入库(本地稿已含,Java 老文可追加)
python src/run_eval.py                        # 跑全部 9 组配置
python src/run_eval.py --config configs/recursive-512.json   # 单组
```

模型自动从 hf-mirror 下载。结果输出到 `results/results.json`。

## 目录

```
corpus/           语料(规范化 md + corpus.jsonl 元数据)
questions.jsonl   测试集(90 题)
configs/          9 组实验配置
src/ingest.py     语料清洗入库
src/chunkers.py   三种分块策略实现
src/run_eval.py   主评测:分块→嵌入→检索→指标
results/          跑批结果与失效案例存档
```

## 指标口径

Hit@1 / Hit@5 / MRR@5,按 A/B 档分层。ground truth 在文章级:top-k 命中目标文章即算 hit。附加观察:代码块被切断次数、跨域干扰计数、失效案例存档(见 results.json 的 misses 字段)。

n=90,报分层观察,不做显著性检验——这是小样本诚实口径。

## License

MIT。语料为本人原创文章,测试集随语料同授权。
