# -*- coding: utf-8 -*-
"""DuReader-retrieval dev 集解析:抽段落池 + 查询抽样。

输入: data/raw/dev.jsonl (HuggingFace zyznull/dureader-retrieval-ranking, dev split)
      每行: {query_id, query, positive_passages:[{docid,text}], negative_passages:[...]}
输出: data/dureader/passages.jsonl        去重段落池(docid + text)
      data/dureader/queries_sample.jsonl  查询抽样(qid + query + positives)

抽样口径: random.Random(42).sample 500/2000,复现固定。
语料池: 全部正例∪负例的去重段落(93,885 篇)——负例本身是 BM25 难负例,
        语料池天然高难,不做任何挑选。

用法: python src/prepare_dataset.py
"""
import json
import random
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "dev.jsonl"
OUT = ROOT / "data" / "dureader"
SAMPLE_N = 500
SEED = 42


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    passages: OrderedDict[str, str] = OrderedDict()
    queries = []
    with open(RAW, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            pos_ids = []
            for p in d["positive_passages"]:
                passages.setdefault(p["docid"], p["text"])
                pos_ids.append(p["docid"])
            for p in d["negative_passages"]:
                passages.setdefault(p["docid"], p["text"])
            queries.append({"qid": d["query_id"], "query": d["query"],
                            "positives": pos_ids})

    with open(OUT / "passages.jsonl", "w", encoding="utf-8") as f:
        for pid, text in passages.items():
            f.write(json.dumps({"docid": pid, "text": text}, ensure_ascii=False) + "\n")

    rng = random.Random(SEED)
    sample = rng.sample(queries, SAMPLE_N)
    with open(OUT / "queries_sample.jsonl", "w", encoding="utf-8") as f:
        for q in sample:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    print(f"passages: {len(passages)}")
    print(f"queries: {len(sample)} / {len(queries)} (seed={SEED})")
    # 正例在池内的核对(应 100%)
    pset = set(passages)
    missing = sum(1 for q in sample if not set(q["positives"]) <= pset)
    print(f"positives missing from pool: {missing}")


if __name__ == "__main__":
    main()
