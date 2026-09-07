# -*- coding: utf-8 -*-
"""截断伪影对照:fixed-1024 的 chunk 分"保头 510 token"(模型默认行为) vs
"保尾 510 token"(手动)两种送入方式,隔离"截断方向 × 信号位置"效应。

若保尾版 A 档大跌 → fixed-1024 的主题级优势来自"主题词集中在 chunk 头部,
静默截断恰好保头"——截断伪影,不是大窗口本身的功劳。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chunkers import chunk_article  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

from sentence_transformers import SentenceTransformer  # noqa: E402
import chromadb  # noqa: E402

MODEL = "BAAI/bge-small-zh-v1.5"
MAX_TOKENS = 510


def main():
    model = SentenceTransformer(MODEL)
    tok = model.tokenizer

    articles = {}
    for line in (ROOT / "corpus" / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        meta = json.loads(line)
        articles[meta["id"]] = (ROOT / "corpus" / f"{meta['id']}.md").read_text(encoding="utf-8")
    questions = [json.loads(l) for l in
                 (ROOT / "questions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    chunks = []
    for aid, text in articles.items():
        chunks += chunk_article(aid, text, "fixed", 1024)

    def keep_head(text):
        ids = tok(text, add_special_tokens=False)["input_ids"]
        return tok.decode(ids[:MAX_TOKENS]) if len(ids) > MAX_TOKENS else text

    def keep_tail(text):
        ids = tok(text, add_special_tokens=False)["input_ids"]
        return tok.decode(ids[-MAX_TOKENS:]) if len(ids) > MAX_TOKENS else text

    for variant, fn in [("head(default)", keep_head), ("tail", keep_tail)]:
        texts = [fn(c["text"]) for c in chunks]
        embs = model.encode(texts, batch_size=32, normalize_embeddings=True,
                            show_progress_bar=False)
        client = chromadb.EphemeralClient()
        col = client.get_or_create_collection(f"abl-{variant[:4]}")
        col.add(ids=[c["chunk_id"] for c in chunks],
                embeddings=[e.tolist() for e in embs], documents=texts,
                metadatas=[{"article_id": c["article_id"]} for c in chunks])
        q_embs = model.encode([q["question"] for q in questions],
                              normalize_embeddings=True, show_progress_bar=False)
        rows = []
        for q, qe in zip(questions, q_embs):
            res = col.query(query_embeddings=[qe.tolist()], n_results=5)
            rows.append((q, [m["article_id"] for m in res["metadatas"][0]]))

        def _m(sub):
            if not sub:
                return (0, 0.0, 0.0)
            h1 = sum(1 for q, h in sub if q["article_id"] == h[0]) / len(sub)
            h5 = sum(1 for q, h in sub if q["article_id"] in h) / len(sub)
            return len(sub), round(h1, 3), round(h5, 3)

        for name, sub in [("A", [r for r in rows if r[0]["tier"] == "A"]),
                          ("B", [r for r in rows if r[0]["tier"] == "B"])]:
            n, h1, h5 = _m(sub)
            print(f"{variant:>14s} tier {name}: n={n} Hit@1={h1} Hit@5={h5}")


if __name__ == "__main__":
    main()
