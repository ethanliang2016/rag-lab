# -*- coding: utf-8 -*-
"""rag-lab 主评测:分块策略 × 粒度 → 检索命中率。

固定量: bge-small-zh-v1.5 / Chroma(top-k=5) / overlap=50
变量:   strategy(fixed|recursive|structure) × size(256|512|1024)
指标:   Hit@1 / Hit@5 / MRR@5,按 A(主题级)/B(细节级) 分层 + 总体
附加:   代码块切断数、跨域干扰(java 文进 ai 题 top-5 的次数)

用法:
  python src/run_eval.py                    # 跑 configs/ 全部
  python src/run_eval.py --config configs/recursive-512.json
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from chunkers import chunk_article, count_codeblock_cuts  # noqa: E402

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
TOP_K = 5


def load_corpus() -> dict[str, dict]:
    arts = {}
    for line in (ROOT / "corpus" / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        m = json.loads(line)
        m["text"] = (ROOT / "corpus" / f"{m['id']}.md").read_text(encoding="utf-8")
        arts[m["id"]] = m
    return arts


def load_questions() -> list[dict]:
    qfile = ROOT / "questions.jsonl"
    return [json.loads(l) for l in qfile.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_index(chunks, model):
    """Chroma 内存索引,每配置独立 collection,避免串味。"""
    import chromadb
    client = chromadb.EphemeralClient()
    col = client.get_or_create_collection("raglab")
    texts = [c["text"] for c in chunks]
    embs = model.encode(texts, batch_size=32, normalize_embeddings=True,
                        show_progress_bar=False)
    col.add(ids=[c["chunk_id"] for c in chunks],
            embeddings=[e.tolist() for e in embs],
            documents=texts,
            metadatas=[{"article_id": c["article_id"]} for c in chunks])
    return col


def evaluate(col, questions, model):
    q_texts = [q["question"] for q in questions]
    q_embs = model.encode(q_texts, normalize_embeddings=True, show_progress_bar=False)
    # 查询向量也过一遍 embedding;Chroma 余弦
    rows = []
    for q, qe in zip(questions, q_embs):
        res = col.query(query_embeddings=[qe.tolist()], n_results=TOP_K)
        hit_ids = [m["article_id"] for m in res["metadatas"][0]]
        rows.append({"q": q, "hits": hit_ids})
    return rows


def metrics(rows):
    def _m(sub):
        if not sub:
            return {"n": 0, "hit1": 0.0, "hit5": 0.0, "mrr5": 0.0}
        h1 = sum(1 for r in sub if r["q"]["article_id"] == r["hits"][0]) / len(sub)
        h5 = sum(1 for r in sub if r["q"]["article_id"] in r["hits"][:5]) / len(sub)
        mrr = 0.0
        for r in sub:
            tgt = r["q"]["article_id"]
            if tgt in r["hits"]:
                mrr += 1.0 / (r["hits"].index(tgt) + 1)
        return {"n": len(sub), "hit1": round(h1, 4), "hit5": round(h5, 4),
                "mrr5": round(mrr / len(sub), 4)}

    return {"overall": _m(rows),
            "A": _m([r for r in rows if r["q"]["tier"] == "A"]),
            "B": _m([r for r in rows if r["q"]["tier"] == "B"])}


def run_config(cfg, model, articles, questions):
    t0 = time.time()
    chunks = []
    for aid, art in articles.items():
        chunks += chunk_article(aid, art["text"], cfg["strategy"], cfg["size"])
    cuts = count_codeblock_cuts(chunks)
    col = build_index(chunks, model)
    rows = evaluate(col, questions, model)
    m = metrics(rows)
    # 跨域干扰: ai 域问题的 top-5 里出现 java 文的次数
    cross = 0
    for r in rows:
        if articles[r["q"]["article_id"]]["domain"] == "ai":
            cross += sum(1 for h in r["hits"] if articles[h]["domain"] == "java")
    out = {"config": cfg, "chunks": len(chunks), "codeblock_cuts": cuts,
           "cross_domain": cross, "metrics": m, "seconds": round(time.time() - t0, 1)}
    # 失效案例存档:Hit@1 未中的题(写作素材)
    out["misses"] = [{"q": r["q"]["id"], "question": r["q"]["question"],
                      "tier": r["q"]["tier"], "target": r["q"]["article_id"],
                      "top1": r["hits"][0]} for r in rows
                     if r["q"]["article_id"] != r["hits"][0]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None, help="单个配置 json 路径,缺省跑 configs/ 全部")
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)

    articles = load_corpus()
    questions = load_questions()
    print(f"corpus={len(articles)} articles, questions={len(questions)}")

    cfg_files = [Path(args.config)] if args.config else sorted(
        (ROOT / "configs").glob("*.json"))
    results = []
    for cf in cfg_files:
        cfg = json.loads(cf.read_text(encoding="utf-8"))
        r = run_config(cfg, model, articles, questions)
        results.append(r)
        o = r["metrics"]["overall"]
        print(f"{cfg['strategy']:>9s}-{cfg['size']:>4d}  chunks={r['chunks']:>4d}  "
              f"cuts={r['codeblock_cuts']:>3d}  "
              f"Hit@1={o['hit1']:.3f} Hit@5={o['hit5']:.3f} MRR@5={o['mrr5']:.3f}  "
              f"({r['seconds']}s)")

    out_path = ROOT / "results" / "results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"\nsaved → {out_path}")


if __name__ == "__main__":
    main()
