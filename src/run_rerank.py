# -*- coding: utf-8 -*-
"""rag-rerank-lab 主评测:双编码召回 → CrossEncoder 重排。

固定量: bge-small-zh-v1.5 召回(npz 向量矩阵 + numpy 精确余弦,build_index.py 产物)
变量:   重排(无 vs bge-reranker-base) × 候选深度 N(10/20/50)
指标:   Hit@1/5/10、MRR@10(top-k 含 ≥1 正例 / 首个正例排名倒数)
归因:   召回缺失(top-50 无正例) vs 排序错误(正例在池但排不进 top-k)
附加:   截断统计(双 512 token 窗)、分数可比性(阈值过滤实证)、延迟口径、查询长度分层

用法:
  python src/run_rerank.py                 # 全量 500 查询
  python src/run_rerank.py --limit 50     # 冒烟
模型下载走 hf-mirror: 环境变量 HF_ENDPOINT=https://hf-mirror.com
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ROOT = Path(__file__).resolve().parent.parent

EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-base"
# bge 系列官方检索用法:查询侧加指令前缀。同时跑无前缀对照(第 1 篇口径),
# 谁的 MRR@10 高用谁做召回层,两边数字都如实入结果。
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章:"
TOP_N = 50
RERANK_NS = [10, 20, 50]
EMBED_WINDOW = 512
RERANK_WINDOW = 512
SHORT_QUERY_MAX = 8  # 查询长度分层阈值(全集均值 9 字,8 字约对半切)


def read_jsonl(p: Path):
    # 语料含 U+2028/U+2029,必须按 \n 切,splitlines() 会误切
    return [json.loads(l) for l in p.read_text(encoding="utf-8").split("\n") if l.strip()]


def rank_metrics(ranked: list[str], positives: set) -> dict:
    """ranked: 依序 docid 列表;positives: 正例 docid 集。"""
    m = {}
    for k in (1, 5, 10):
        m[f"hit@{k}"] = int(bool(positives & set(ranked[:k])))
    m["mrr@10"] = 0.0
    for i, d in enumerate(ranked[:10]):
        if d in positives:
            m["mrr@10"] = 1.0 / (i + 1)
            break
    return m


def agg_metrics(rows: list[dict]) -> dict:
    out = {"n": len(rows)}
    for k in ("hit@1", "hit@5", "hit@10"):
        out[k] = round(sum(r[k] for r in rows) / len(rows), 4)
    out["mrr@10"] = round(sum(r["mrr@10"] for r in rows) / len(rows), 4)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 条查询(冒烟)")
    ap.add_argument("--data-dir", default=None,
                    help="数据目录(含 queries_sample.jsonl / passages.jsonl),缺省 data/dureader")
    ap.add_argument("--index-dir", default=None,
                    help="Chroma 索引目录,缺省 data/index/bge_small_zh")
    ap.add_argument("--out", default=None, help="结果输出路径,缺省 results/rerank_results.json")
    ap.add_argument("--resume", action="store_true",
                    help="从 results/rerank_checkpoint.jsonl 断点续跑(跳过已算 query)")
    args = ap.parse_args()

    import numpy as np
    from sentence_transformers import CrossEncoder, SentenceTransformer

    data_dir = Path(args.data_dir) if args.data_dir else ROOT / "data" / "dureader"
    index_npz = Path(args.index_dir) if args.index_dir else \
        ROOT / "data" / "index" / "bge_small_zh.npz"

    queries = read_jsonl(data_dir / "queries_sample.jsonl")
    if args.limit:
        queries = queries[: args.limit]
    for q in queries:
        q["pos"] = set(q["positives"])
        del q["positives"]
    print(f"queries: {len(queries)}")

    model = SentenceTransformer(EMBED_MODEL)
    z = np.load(index_npz)
    vec_ids = [str(x) for x in z["ids"]]   # docid 列表(与向量矩阵行对齐)
    vecs = z["vectors"]                      # (N, 512) 已归一化
    print(f"index: {len(vec_ids)} passages")
    # 段落原文(pair 构造与截断统计用)
    ptext = {p["docid"]: p["text"]
             for p in read_jsonl(data_dir / "passages.jsonl")}

    # ---------- 阶段 1: 双编码召回(query 前缀对照,精确余弦) ----------
    q_texts = [q["query"] for q in queries]
    t0 = time.time()
    emb_no = model.encode(q_texts, normalize_embeddings=True, show_progress_bar=False)
    emb_in = model.encode([QUERY_INSTRUCTION + t for t in q_texts],
                          normalize_embeddings=True, show_progress_bar=False)
    t_embed = time.time() - t0

    def topk_search(qe, k=TOP_N):
        """精确余弦 top-k:双方已归一化,点积即余弦。"""
        sims = qe @ vecs.T                                   # (n_q, N)
        idx = np.argpartition(-sims, kth=k - 1, axis=1)[:, :k]
        order = np.take_along_axis(
            idx, np.argsort(-np.take_along_axis(sims, idx, axis=1), axis=1), axis=1)
        return [[vec_ids[i] for i in row] for row in order]

    t1 = time.time()
    ids_no = topk_search(emb_no)
    ids_in = topk_search(emb_in)
    t_retr = time.time() - t1

    rows_no = [rank_metrics(ids_no[i], queries[i]["pos"]) for i in range(len(queries))]
    rows_in = [rank_metrics(ids_in[i], queries[i]["pos"]) for i in range(len(queries))]
    m_no, m_in = agg_metrics(rows_no), agg_metrics(rows_in)
    used, top_ids = ("instruction", ids_in) if m_in["mrr@10"] >= m_no["mrr@10"] \
        else ("no_instruction", ids_no)
    print(f"recall layer: no_prefix mrr@10={m_no['mrr@10']} | "
          f"with_prefix mrr@10={m_in['mrr@10']} → using [{used}]")
    retrieval = {"no_instruction": m_no, "with_instruction": m_in, "used": used}

    top_docs = [[ptext[d] for d in row] for row in top_ids]  # 对应段落原文

    # ---------- 阶段 2: CrossEncoder 重排 ----------
    print(f"loading reranker: {RERANK_MODEL}")
    ce = CrossEncoder(RERANK_MODEL, max_length=RERANK_WINDOW)

    t2 = time.time()
    all_scores: list[list[float]] = []
    pair_tok_over = 0
    pair_tok_total = 0
    rerank_rows: dict[int, list] = {n: [] for n in RERANK_NS}
    misses = []
    pos_scores, neg_scores = [], []
    rescued = killed = persist_fail = recall_missing = 0

    # ---- 阶段 2 checkpoint:逐条落盘,断电/关机不丢已算结果,可用 --resume 续跑 ----
    ckpt_path = ROOT / "results" / "rerank_checkpoint.jsonl"
    done: dict[str, dict] = {}
    if args.resume and ckpt_path.exists():
        for _l in ckpt_path.read_text(encoding="utf-8").split("\n"):
            if _l.strip():
                _r = json.loads(_l)
                done[_r["qid"]] = _r
        print(f"resume: {len(done)}/{len(queries)} queries already done, skipping")
    ckpt_f = open(ckpt_path, "a" if done else "w", encoding="utf-8")

    for i, q in enumerate(queries):
        rec = done.get(q["qid"])
        if rec is None:
            docs = top_docs[i]
            pairs = [(q["query"], d) for d in docs]
            scores = ce.predict(pairs, batch_size=32).tolist()

            # pair token 长度(截断统计,与重排同口径)
            tok = ce.tokenizer([q["query"]] * len(docs), docs, truncation=False)
            lens = [len(x) for x in tok["input_ids"]]
            rec = {"qid": q["qid"], "i": i, "scores": scores,
                   "tok_total": len(lens),
                   "tok_over": sum(1 for L in lens if L > RERANK_WINDOW)}
            ckpt_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            ckpt_f.flush()

        all_scores.append(rec["scores"])
        pair_tok_total += rec["tok_total"]
        pair_tok_over += rec["tok_over"]

        for j, (d, s) in enumerate(zip(top_ids[i], rec["scores"])):
            (pos_scores if d in q["pos"] else neg_scores).append(s)

        base_hit10 = bool(q["pos"] & set(top_ids[i][:10]))

        for n in RERANK_NS:
            order = sorted(range(min(n, len(rec["scores"]))),
                           key=lambda j: -rec["scores"][j])
            ranked = [top_ids[i][j] for j in order]
            rerank_rows[n].append(rank_metrics(ranked, q["pos"]))

        if i % 50 == 0:
            print(f"  rerank {i}/{len(queries)}  ({time.time() - t2:.0f}s)")

    ckpt_f.close()
    t_rerank = time.time() - t2

    rerank = {str(n): agg_metrics(rerank_rows[n]) for n in RERANK_NS}

    # ---------- 阶段 3: 归因(以 rerank@20 对照 baseline@10) ----------
    n20 = rerank_rows[20]
    for i, q in enumerate(queries):
        in_pool = bool(q["pos"] & set(top_ids[i]))
        base10 = bool(q["pos"] & set(top_ids[i][:10]))
        rr10 = n20[i]["hit@10"] == 1
        if not in_pool:
            recall_missing += 1
        elif base10 and not rr10:
            killed += 1
        elif not base10 and rr10:
            rescued += 1
        elif not base10 and not rr10:
            persist_fail += 1
        if len(misses) < 30 and not rr10:
            misses.append({
                "qid": q["qid"], "query": q["query"],
                "positive_in_top50": in_pool,
                "baseline_top10": [top_ids[i][j] for j in range(10)],
                "rerank_top10_docids": [top_ids[i][j] for j in
                                        sorted(range(20), key=lambda j: -all_scores[i][j])[:10]],
            })

    # ---------- 阶段 4: 截断统计(嵌入侧: 全语料段落) ----------
    enc_over = enc_total = 0
    bt = time.time()
    tok = model.tokenizer(list(ptext.values()), truncation=False)
    enc_total = len(tok["input_ids"])
    enc_over = sum(1 for x in tok["input_ids"] if len(x) > EMBED_WINDOW)
    print(f"corpus tokenize: {time.time() - bt:.0f}s")

    # ---------- 阶段 5: 分数可比性分析(坑 2:sigmoid 分数当置信度阈值) ----------
    def pct(a, p):
        a = sorted(a)
        return round(a[int(len(a) * p)], 3)

    # 固定阈值过滤实证:阈值扫 0.5/0.7/0.9,统计被误杀的正例 / 漏进来的负例
    threshold = {}
    for th in (0.5, 0.7, 0.9):
        threshold[str(th)] = {
            "pos_below": round(sum(1 for x in pos_scores if x < th) / len(pos_scores), 4),
            "neg_above": round(sum(1 for x in neg_scores if x >= th) / len(neg_scores), 4),
        }
    logit = {
        "pos_pair_mean": round(sum(pos_scores) / len(pos_scores), 3),
        "neg_pair_mean": round(sum(neg_scores) / len(neg_scores), 3),
        "all_score_min": round(min(min(s) for s in all_scores), 3),
        "all_score_max": round(max(max(s) for s in all_scores), 3),
        "all_score_p10_p50_p90": [pct([x for s in all_scores for x in s], p)
                                  for p in (0.1, 0.5, 0.9)],
        "fixed_threshold_sweep": threshold,
        "note": ("CrossEncoder.predict 默认输出 sigmoid 分数;绝对值跨查询不可比,"
                 "仅可组内排序——固定阈值过滤会误杀/漏放,见 threshold sweep"),
    }

    # ---------- 阶段 6: 查询长度分层 ----------
    short_idx = [i for i, q in enumerate(queries) if len(q["query"]) <= SHORT_QUERY_MAX]
    strat = {
        "short": {"n": len(short_idx),
                  "baseline": agg_metrics([rank_metrics(top_ids[i], queries[i]["pos"])
                                          for i in short_idx]),
                  "rerank@20": agg_metrics([n20[i] for i in short_idx])},
    }
    long_idx = [i for i in range(len(queries)) if i not in set(short_idx)]
    strat["long"] = {"n": len(long_idx),
                     "baseline": agg_metrics([rank_metrics(top_ids[i], queries[i]["pos"])
                                             for i in long_idx]),
                     "rerank@20": agg_metrics([n20[i] for i in long_idx])}

    # ---------- 汇总 ----------
    out = {
        "meta": {"embed_model": EMBED_MODEL, "rerank_model": RERANK_MODEL,
                 "n_queries": len(queries), "top_n": TOP_N,
                 "rerank_ns": RERANK_NS, "index_passages": len(vec_ids)},
        "retrieval": retrieval,
        "rerank": rerank,
        "attribution": {"recall_missing_top50": recall_missing,
                        "rescued_rerank20_hit10": rescued,
                        "killed_rerank20_hit10": killed,
                        "persist_fail_hit10": persist_fail},
        "latency": {"query_embed_ms_per_q": round(t_embed / len(queries) * 1000, 1),
                    "retrieve_ms_per_q": round(t_retr / len(queries) * 1000, 1),
                    "rerank_s_per_50pairs": round(t_rerank / len(queries), 3),
                    "rerank_pair_per_s": round(len(queries) * TOP_N / t_rerank, 1)},
        "truncation": {
            "embedder": {"window": EMBED_WINDOW, "total": enc_total,
                         "over": enc_over, "pct": round(enc_over / enc_total * 100, 2)},
            "reranker_pairs": {"window": RERANK_WINDOW, "total": pair_tok_total,
                               "over": pair_tok_over,
                               "pct": round(pair_tok_over / pair_tok_total * 100, 2)}},
        "logit_analysis": logit,
        "stratified_by_query_len": strat,
        "misses_examples": misses,
    }
    out_path = Path(args.out) if args.out else ROOT / "results" / "rerank_results.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + json.dumps({k: v for k, v in out.items()
                              if k not in ("misses_examples",)}, ensure_ascii=False, indent=1))
    print(f"\nsaved → {out_path}")


if __name__ == "__main__":
    main()
