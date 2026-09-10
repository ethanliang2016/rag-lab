# -*- coding: utf-8 -*-
"""第 3 篇(生成层)数据准备:CMRC2018 validation → 检索语料 + 抽样 + bge 索引。

一次构建、三档复用(与第 2 篇"检索层脏活只干一次"同构):
- 语料:validation 3,219 篇 context 全量切块。块策略取第 1 篇 fixed 基线的
  固定字符窗(window=200/overlap=50),并记录每块的 [start,end) 字符 offset——
  答案覆盖判定因此是字符区间相交,确定性,不靠相似度近似。
- 金标:每行 {qid, question, docid, answer_text, answer_start};
  金块判定 = 块区间覆盖 [answer_start, answer_start+len(answer_text))。
- 索引:全部块 → bge-small-zh-v1.5 向量 npz(与行对齐),沿用第 2 篇
  "npz + numpy 精确余弦"(免 Chroma 持久化坑)。
- 抽样:seed=42 抽 800 题作主表(--full 全量),800×3 题对子先不在此做,
  生成任务构造在 run_generate.py。

产物:
  data/cmrc/passages.jsonl     语料块 {chunk_id, docid, start, end, text}
  data/cmrc/cmrc_val.jsonl     全量金标 {qid, question, docid, answer_text, answer_start}
  data/cmrc/sample.jsonl       抽样子集(行结构与 cmrc_val 同)
  data/cmrc/cmrc_blocks.npz    bge 向量,行对齐 passages.jsonl

用法:
  python src/prepare_cmrc.py                  # 全量 3,219 篇 → 抽 800
  python src/prepare_cmrc.py --full           # 全量抽样(备选)
  python src/prepare_cmrc.py --limit-docs 40  # 冒烟(只取前 40 篇)
数据源:hf-mirror `hfl/cmrc2018`,split=validation(数据卡:3,219 行)。
"""
import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "cmrc"

WINDOW = 200          # 固定字符窗(第 1 篇 fixed 基线同款口径)
OVERLAP = 50          # 全系列固定
SAMPLE_N = 800
SEED = 42
MODEL_NAME = "BAAI/bge-small-zh-v1.5"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章:"  # 第 2 篇实测前缀更优


def chunk_window(text: str, size: int = WINDOW, overlap: int = OVERLAP):
    """固定字符滑窗,返回 [(text_slice, start, end)],start 为字符 offset。"""
    step = max(1, size - overlap)
    out = []
    for start in range(0, max(1, len(text)), step):
        end = min(len(text), start + size)
        piece = text[start:end]
        if not piece.strip():
            break
        out.append((piece, start, end))
        if end >= len(text):
            break
    return out


def gold_block_id(blocks: list[dict], ans_start: int, ans_len: int) -> str | None:
    """返回覆盖答案字符区间的块;无完全覆盖(答案横跨切点)则退回含起点的块。"""
    lo, hi = ans_start, ans_start + ans_len
    for b in blocks:
        if b["start"] <= lo and hi <= b["end"]:
            return b["chunk_id"]
    for b in blocks:                       # 回退:区间相交最大优先取首覆盖起点者
        if b["start"] <= lo < b["end"]:
            return b["chunk_id"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="全量抽样,不做 800 截断")
    ap.add_argument("--limit-docs", type=int, default=None,
                    help="只取 validation 前 N 篇(冒烟用)")
    ap.add_argument("--force", action="store_true", help="强制重建(删除既有产物)")
    ap.add_argument("--no-index", action="store_true",
                    help="跳过 bge 索引构建(只出 sample.jsonl/切块,本地对齐口径用)")
    args = ap.parse_args()

    from datasets import load_dataset
    import numpy as np
    from sentence_transformers import SentenceTransformer

    if args.force and DATA_DIR.exists():
        import shutil
        shutil.rmtree(DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("loading hfl/cmrc2018 validation ...")
    ds = load_dataset("hfl/cmrc2018", split="validation")
    if args.limit_docs:
        ds = ds.select(range(args.limit_docs))
    rows = list(ds)
    print(f"rows: {len(rows)}")

    # ---------- 1. 语料切块 + 金标 ----------
    passages, golds = [], []
    t0 = time.time()
    for i, r in enumerate(rows):
        docid = r["id"]
        ctx = r["context"]
        ans = r["answers"]["text"][0]
        ans_start = int(r["answers"]["answer_start"][0])
        blocks = []
        for j, (piece, s, e) in enumerate(chunk_window(ctx)):
            cid = f"{docid}#b{j}"
            passages.append({"chunk_id": cid, "docid": docid,
                             "start": s, "end": e, "text": piece})
            blocks.append({"chunk_id": cid, "start": s, "end": e})
        golds.append({"qid": docid, "question": r["question"], "docid": docid,
                      "answer_text": ans, "answer_start": ans_start,
                      "gold_chunk": gold_block_id(blocks, ans_start, len(ans)),
                      "doc_chunks": len(blocks)})
    print(f"chunking: {len(passages)} blocks from {len(rows)} docs "
          f"({time.time() - t0:.1f}s)")

    with open(DATA_DIR / "passages.jsonl", "w", encoding="utf-8") as f:
        for p in passages:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(DATA_DIR / "cmrc_val.jsonl", "w", encoding="utf-8") as f:
        for g in golds:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    goldless = sum(1 for g in golds if g["gold_chunk"] is None)
    print(f"goldless(答案跨切点,oracle 需降级): {goldless}")
    n3 = sum(1 for g in golds if g["doc_chunks"] >= 3)
    print(f"doc_chunks>=3 的题(位置效应主表适用): {n3}/{len(golds)}")

    # ---------- 2. 抽样 ----------
    rng = random.Random(SEED)
    sample_n = len(golds) if args.full else min(SAMPLE_N, len(golds))
    sample = rng.sample(golds, sample_n)
    sample = sorted(sample, key=lambda g: g["qid"])
    with open(DATA_DIR / "sample.jsonl", "w", encoding="utf-8") as f:
        for g in sample:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    print(f"sample: {len(sample)}")

    if args.no_index:
        print(f"--no-index: 已在 {DATA_DIR} 生成 passages/cmrc_val/sample,跳过 bge 索引")
        return

    # ---------- 3. bge 索引 ----------
    out_npz = DATA_DIR / "cmrc_blocks.npz"
    if out_npz.exists():
        print(f"index exists: {out_npz}, skip (delete to rebuild)")
        return
    print(f"loading {MODEL_NAME} ...")
    model = SentenceTransformer(MODEL_NAME)
    t1 = time.time()
    embs = model.encode([p["text"] for p in passages], batch_size=64,
                        normalize_embeddings=True, show_progress_bar=True)
    print(f"encode: {time.time() - t1:.1f}s for {len(passages)} blocks")
    ids = np.array([p["chunk_id"] for p in passages])
    np.savez(out_npz, ids=ids, vectors=np.asarray(embs, dtype=np.float32))
    meta = {"n_docs": len(rows), "n_blocks": len(passages),
            "window": WINDOW, "overlap": OVERLAP, "sample": len(sample),
            "doc_chunks_ge3": n3, "goldless": goldless,
            "limit_docs": args.limit_docs}
    (DATA_DIR / "prepare_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved → {out_npz}  meta={meta}")


if __name__ == "__main__":
    main()
