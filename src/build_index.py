# -*- coding: utf-8 -*-
"""DuReader-retrieval 段落池建索引: bge-small-zh-v1.5 → 向量矩阵落盘 npz。

语料固定后嵌入只算一次(9.4 万段落,CPU 约 80 分钟);产物 npz 直接复用,
重排实验换的只是排序层,不动索引——"检索层的脏活只干一次"。

为什么不用 Chroma PersistentClient: 实测 Windows + chromadb 1.5.9 上,
进程正常退出后 HNSW 段二进制不落盘(仅 index_metadata.pickle),重开即
InternalError: Error loading hnsw index,向量本体丢失。对 9.4 万×512 维
的规模,numpy 精确余弦检索本来就更合适(秒级、零近似噪声、可复现)。

输入: data/dureader/passages.jsonl
输出: data/index/bge_small_zh.npz  (ids + 归一化向量矩阵)
      data/index/build_log.json   (吞吐与耗时记录)

用法: python src/build_index.py
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
PASSAGES = ROOT / "data" / "dureader" / "passages.jsonl"
INDEX_DIR = ROOT / "data" / "index"
OUT_NPZ = INDEX_DIR / "bge_small_zh.npz"
BATCH = 64


def main():
    import numpy as np
    from sentence_transformers import SentenceTransformer

    # 注意: 段落文本内含 U+2028/U+2029,splitlines() 会误切,必须按 \n 切
    passages = [json.loads(l) for l in
                PASSAGES.read_text(encoding="utf-8").split("\n") if l.strip()]
    print(f"passages: {len(passages)}")

    if OUT_NPZ.exists():
        print(f"index exists: {OUT_NPZ}, skip (delete to rebuild)")
        return

    model = SentenceTransformer(MODEL_NAME)
    t0 = time.time()
    embs = model.encode([p["text"] for p in passages], batch_size=BATCH,
                        normalize_embeddings=True, show_progress_bar=True)
    t_enc = time.time() - t0

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    ids = np.array([p["docid"] for p in passages])
    np.savez(OUT_NPZ, ids=ids, vectors=np.asarray(embs, dtype=np.float32))

    log = {"passages": len(passages), "model": MODEL_NAME,
           "encode_seconds": round(t_enc, 1),
           "encode_rate_per_s": round(len(passages) / t_enc, 1)}
    (INDEX_DIR / "build_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(log, ensure_ascii=False))


if __name__ == "__main__":
    main()
