# -*- coding: utf-8 -*-
"""第 5 篇（查询路由实测）· 第一步：构造知识域。

读 bge-small-zh 的 93,885 条段落嵌入，用 KMeans 聚成 K 个语义域，
并把每条 query 的「真实域」定为其金标段落所在的簇。

为什么用聚类、不能用随机分配：
    随机分配出来的域内部没有语义一致性，任何路由方法都不可能生效，
    会得出「路由没用」的错误结论。聚类保证域内语义连贯。

输入:data/dureader/passages.jsonl、data/index/bge_small_zh.npz、data/dureader/queries_sample.jsonl
输出:data/route/domains.json（pid→域、query→真实域、域规模、域主题词）
     data/route/centroids.npy（K×512 簇质心，已 L2 归一化）

用法: python src/make_route_domains.py [--k 4] [--seed 42]
"""
import argparse
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import CountVectorizer

ROOT = Path(__file__).resolve().parent.parent
PASSAGES = ROOT / "data" / "dureader" / "passages.jsonl"
INDEX = ROOT / "data" / "index" / "bge_small_zh.npz"
QUERIES = ROOT / "data" / "dureader" / "queries_sample.jsonl"
OUTDIR = ROOT / "data" / "route"


def read_jsonl(p):
    with p.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def domain_topic_words(texts_by_dom, k, topn=14):
    """给每个域抽一组"主题词"，用来人工确认域内语义是否连贯。

    做法：字符 1~2gram 计数，取该域频率相对全局最高的若干个。
    """
    all_texts = [t for dom in range(k) for t in texts_by_dom[dom]]
    vec = CountVectorizer(analyzer="char", ngram_range=(1, 2), min_df=5, max_features=60000)
    X = vec.fit_transform(all_texts)
    vocab = np.array(vec.get_feature_names_out())
    global_rate = np.asarray(X.sum(axis=0)).ravel() / max(X.sum(), 1)

    out = []
    start = 0
    for dom in range(k):
        n = len(texts_by_dom[dom])
        sub = X[start:start + n]
        start += n
        dom_rate = np.asarray(sub.sum(axis=0)).ravel() / max(sub.sum(), 1)
        lift = dom_rate / (global_rate + 1e-9)
        # 只保留在该域出现够多次的，避免长尾噪声
        cnt = np.asarray(sub.sum(axis=0)).ravel()
        lift[cnt < max(5, n * 0.002)] = 0
        top = np.argsort(-lift)[:topn]
        out.append([vocab[i] for i in top if lift[i] > 1.5])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=4, help="域个数")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sample-per-dom", type=int, default=3000,
                    help="抽主题词时每个域最多用多少条文本")
    args = ap.parse_args()
    K, SEED = args.k, args.seed

    passages = read_jsonl(PASSAGES)
    queries = read_jsonl(QUERIES)
    z = np.load(INDEX)
    ids, vecs = z["ids"], z["vectors"]

    # ids 与 passages 的行序是否一致？不一致就按 docid 建映射重排
    pids = [p["docid"] for p in passages]
    if len(pids) != len(ids):
        raise SystemExit(f"段落数 {len(pids)} 与索引行数 {len(ids)} 不一致")
    same_order = all(a == b for a, b in zip(pids, ids))
    if not same_order:
        pos = {d: i for i, d in enumerate(ids)}
        order = [pos[d] for d in pids]
        vecs = vecs[order]
        ids = np.array(pids)
        print("索引与段落行序不一致，已按 docid 重排")
    print(f"段落 {len(pids)} 条，嵌入 {vecs.shape}")

    # L2 归一化后聚类（等价于按余弦距离聚）
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1e-12
    vecs_n = vecs / norms

    print(f"KMeans(K={K}, seed={SEED}) ...")
    km = KMeans(n_clusters=K, n_init=10, random_state=SEED)
    labels = km.fit_predict(vecs_n)

    centroids = km.cluster_centers_
    centroids = centroids / (np.linalg.norm(centroids, axis=1, keepdims=True) + 1e-12)

    pid2dom = {d: int(l) for d, l in zip(pids, labels)}
    dom_sizes = [int((labels == i).sum()) for i in range(K)]

    # 每条 query 的真实域：金标段落所在簇的多数派
    q_true, multi, missing = {}, 0, 0
    for q in queries:
        doms = [pid2dom[p] for p in q.get("positives", []) if p in pid2dom]
        if not doms:
            missing += 1
            continue
        c = Counter(doms).most_common()
        if len(c) > 1 and c[0][1] == c[1][1]:
            multi += 1
        q_true[q["qid"]] = c[0][0]

    # 域主题词（抽样，控制耗时）
    rng = random.Random(SEED)
    texts_by_dom = []
    for i in range(K):
        idx = np.where(labels == i)[0]
        if len(idx) > args.sample_per_dom:
            idx = rng.sample(list(idx), args.sample_per_dom)
        texts_by_dom.append([passages[j]["text"] for j in idx])
    topics = domain_topic_words(texts_by_dom, K)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "centroids.npy").write_bytes(centroids.astype(np.float32).tobytes())
    np.save(OUTDIR / "centroids.npy", centroids.astype(np.float32))

    meta = {
        "k": K, "seed": SEED,
        "n_passages": len(pids),
        "dom_sizes": dom_sizes,
        "dom_topics": topics,
        "pid2dom": pid2dom,
        "query_true_dom": q_true,
        "n_query_total": len(queries),
        "n_query_scored": len(q_true),
        "n_query_multi_dom": multi,
        "n_query_missing": missing,
    }
    (OUTDIR / "domains.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    print(f"\n域规模: {dom_sizes}")
    for i, (n, w) in enumerate(zip(dom_sizes, topics)):
        print(f"  域{i}  n={n:<6} 主题词: {'、'.join(w[:10])}")
    print(f"\nquery 真实域: {len(q_true)}/{len(queries)} 条"
          f"（跨域平票 {multi} 条，金标缺失 {missing} 条）")
    print(f"saved → {OUTDIR / 'domains.json'}")
    print(f"saved → {OUTDIR / 'centroids.npy'}")


if __name__ == "__main__":
    main()
