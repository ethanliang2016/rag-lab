# -*- coding: utf-8 -*-
"""第 5 篇（查询路由实测）· 第二步：五组路由对照跑批。

    A 基线        不路由，全库 93,885 检索
    B BM25 路由    query 与 4 个域的关键词画像做 BM25，取 Top-1 域
    C 嵌入 Top-1   query 嵌入与域质心余弦，取 Top-1 域
    D 嵌入 Top-2   同上取 Top-2 域
    E LLM 路由     Qwen2.5-0.5B 读域主题词后选域（--llm 开启）

输入:data/dureader/*、data/index/bge_small_zh.npz、data/route/domains.json
输出:results/route_eval.jsonl（逐条）、results/route_metrics.json（汇总）

用法: python src/run_route_eval.py [--topk 10] [--llm]
"""
import argparse
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PASSAGES = ROOT / "data" / "dureader" / "passages.jsonl"
INDEX = ROOT / "data" / "index" / "bge_small_zh.npz"
QUERIES = ROOT / "data" / "dureader" / "queries_sample.jsonl"
ROUTE = ROOT / "data" / "route"
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
LLM_NAME = "Qwen/Qwen2.5-0.5B-Instruct"


def read_jsonl(p):
    with p.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ---------------- BM25 路由：把每个域当一篇"文档" ----------------
def char_ngrams(s, n=(1, 2)):
    s = re.sub(r"\s+", "", s)
    out = []
    for k in n:
        out += [s[i:i + k] for i in range(len(s) - k + 1)]
    return out


class DomainBM25:
    """4 个域各当一篇文档，query 与它们算 BM25。

    画像用抽样构建：一个域两万多条段落全量扫字符 ngram 要跑几分钟且吃内存，
    抽样几千条得到的关键词分布在统计上等价。
    """

    def __init__(self, texts_by_dom, k1=1.5, b=0.75, sample=5000, seed=42):
        import random
        self.k1, self.b = k1, b
        rng = random.Random(seed)
        self.tf = []
        for texts in texts_by_dom:
            if len(texts) > sample:
                texts = rng.sample(texts, sample)
            c = Counter()
            for t in texts:
                c.update(char_ngrams(t))
            self.tf.append(c)
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / max(len(self.len), 1)
        df = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(self.tf)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def route(self, query):
        qt = Counter(char_ngrams(query))
        best, best_s = 0, -1e9
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w, c in qt.items():
                f = tf.get(w, 0)
                if not f:
                    continue
                s += (self.idf.get(w, 0.0) * f * (self.k1 + 1)
                      / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)))
            if s > best_s:
                best, best_s = i, s
        return best

    def top2(self, query):
        qt = Counter(char_ngrams(query))
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w, c in qt.items():
                f = tf.get(w, 0)
                if not f:
                    continue
                s += (self.idf.get(w, 0.0) * f * (self.k1 + 1)
                      / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)))
            scores.append((s, i))
        scores.sort(reverse=True)
        return [i for _, i in scores[:2]]


class CentroidRouter:
    def __init__(self, centroids):
        self.c = centroids  # (K, d) 已归一化

    def order(self, qv):
        sims = self.c @ qv
        return np.argsort(-sims)


class LLMRouter:
    def __init__(self, topics):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch
        self.tok = AutoTokenizer.from_pretrained(LLM_NAME, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            LLM_NAME, trust_remote_code=True, torch_dtype=torch.float32)
        self.model.eval()
        desc = "\n".join(f"{i}. {'、'.join(t[:8])}" for i, t in enumerate(topics))
        self.desc = desc
        self.fail = 0

    def route(self, query):
        import torch
        prompt = (f"下面是 4 个知识领域的主题词：\n{self.desc}\n\n"
                  f"请只回答一个问题属于哪个领域，输出一个数字（0-3）。\n"
                  f"问题：{query}\n领域编号：")
        ids = self.tok(prompt, return_tensors="pt")
        with torch.no_grad():
            out = self.model.generate(**ids, max_new_tokens=4, do_sample=False,
                                      pad_token_id=self.tok.eos_token_id)
        txt = self.tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        m = re.search(r"[0-3]", txt)
        if not m:
            self.fail += 1
            return -1
        return int(m.group(0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--llm", action="store_true", help="是否跑 E 组（LLM 路由）")
    args = ap.parse_args()
    K10 = args.topk

    passages = read_jsonl(PASSAGES)
    queries = read_jsonl(QUERIES)
    z = np.load(INDEX)
    vecs = z["vectors"].astype(np.float32)
    meta = json.loads((ROUTE / "domains.json").read_text(encoding="utf-8"))
    K = meta["k"]
    pid2dom = meta["pid2dom"]
    centroids = np.load(ROUTE / "centroids.npy").astype(np.float32)

    vecs = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12)
    labels = np.array([pid2dom[p["docid"]] for p in passages])
    dom_rows = [np.where(labels == i)[0] for i in range(K)]
    all_rows = np.arange(len(passages))

    # 只用有金标的 query
    qs = [q for q in queries if any(p in pid2dom for p in q.get("positives", []))]
    print(f"可计分 query: {len(qs)} / {len(queries)}（其余无金标段落）")

    from sentence_transformers import SentenceTransformer
    print("加载 bge-small-zh ...", flush=True)
    model = SentenceTransformer(MODEL_NAME)
    t0 = time.time()
    q_emb = model.encode([q["query"] for q in qs], normalize_embeddings=True,
                         batch_size=32, show_progress_bar=False)
    print(f"query 编码 {time.time() - t0:.1f}s")

    print("构建 BM25 域画像 ...", flush=True)
    bm25 = DomainBM25([[passages[j]["text"] for j in dom_rows[i]] for i in range(K)])
    print("  done", flush=True)
    cent = CentroidRouter(centroids)
    llm = LLMRouter(meta["dom_topics"]) if args.llm else None

    def search(rows, qv, k=K10):
        sims = vecs[rows] @ qv
        if k >= len(sims):
            take = np.argsort(-sims)
        else:
            take = np.argpartition(-sims, k)[:k]
            take = take[np.argsort(-sims[take])]
        return rows[take], sims[take]

    def score(fn_rows, q, qv):
        """返回 (命中列表, 检索耗时ms)"""
        t = time.perf_counter()
        rows, _ = search(fn_rows(), qv)
        ms = (time.perf_counter() - t) * 1000
        pos = set(p for p in q["positives"] if p in pid2dom)
        got = [passages[j]["docid"] for j in rows]
        hit = 1 if (set(got) & pos) else 0
        rec = len(set(got) & pos) / max(len(pos), 1)
        hit1 = 1 if got and got[0] in pos else 0
        return hit, rec, hit1, ms

    out = []
    for qi, q in enumerate(qs):
        qv = q_emb[qi]
        true_dom = meta["query_true_dom"][q["qid"]]
        row = {"qid": q["qid"], "query": q["query"], "true_dom": true_dom}

        # A 基线：全库
        hit, rec, h1, ms = score(lambda: all_rows, q, qv)
        row["A"] = {"dom": None, "hit": hit, "rec": rec, "hit1": h1, "ms": ms}

        # B BM25 路由
        d = bm25.route(q["query"])
        hit, rec, h1, ms = score(lambda d=d: dom_rows[d], q, qv)
        row["B"] = {"dom": int(d), "hit": hit, "rec": rec, "hit1": h1, "ms": ms}

        # C / D 嵌入质心路由
        order = cent.order(qv)
        d1 = int(order[0])
        hit, rec, h1, ms = score(lambda d=d1: dom_rows[d], q, qv)
        row["C"] = {"dom": d1, "hit": hit, "rec": rec, "hit1": h1, "ms": ms}
        top2 = [int(x) for x in order[:2]]
        rows2 = np.concatenate([dom_rows[x] for x in top2])
        hit, rec, h1, ms = score(lambda r=rows2: r, q, qv)
        row["D"] = {"dom": top2, "hit": hit, "rec": rec, "hit1": h1, "ms": ms}

        # E LLM 路由
        if llm:
            dl = llm.route(q["query"])
            if dl < 0:
                hit, rec, h1, ms = score(lambda: all_rows, q, qv)
                row["E"] = {"dom": -1, "hit": hit, "rec": rec, "hit1": h1, "ms": ms}
            else:
                hit, rec, h1, ms = score(lambda d=dl: dom_rows[d], q, qv)
                row["E"] = {"dom": dl, "hit": hit, "rec": rec, "hit1": h1, "ms": ms}

        out.append(row)
        if (qi + 1) % 100 == 0:
            print(f"  {qi + 1}/{len(qs)}")

    (ROOT / "results").mkdir(exist_ok=True)
    with (ROOT / "results" / "route_eval.jsonl").open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---------- 汇总 ----------
    methods = ["A", "B", "C", "D"] + (["E"] if llm else [])
    summ = {"n": len(out), "topk": K10, "k": K, "dom_sizes": meta["dom_sizes"],
            "methods": {}}
    for m in methods:
        hits = [r[m]["hit"] for r in out]
        recs = [r[m]["rec"] for r in out]
        h1s = [r[m]["hit1"] for r in out]
        mss = [r[m]["ms"] for r in out]
        correct = [1 for r in out
                   if (r["true_dom"] == r[m]["dom"]
                       or (isinstance(r[m]["dom"], list) and r["true_dom"] in r[m]["dom"]))]
        summ["methods"][m] = {
            "hit@10": sum(hits) / len(hits),
            "recall@10": sum(recs) / len(recs),
            "hit@1": sum(h1s) / len(h1s),
            "route_correct": len(correct),
            "route_acc": len(correct) / len(out),
            "ms_mean": sum(mss) / len(mss),
            "ms_p50": float(np.percentile(mss, 50)),
        }

    (ROOT / "results" / "route_metrics.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 汇总 ===")
    for m in methods:
        s = summ["methods"][m]
        print(f"{m}: 路由准确 {s['route_acc'] * 100:5.1f}%  "
              f"Hit@10 {s['hit@10'] * 100:5.1f}%  Recall@10 {s['recall@10'] * 100:5.1f}%  "
              f"{s['ms_mean']:.2f}ms")
    print(f"saved → results/route_eval.jsonl ({len(out)} 条)")
    print("saved → results/route_metrics.json")
    if llm:
        print(f"LLM 路由解析失败 {llm.fail} 次")


if __name__ == "__main__":
    main()
