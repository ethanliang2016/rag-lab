# -*- coding: utf-8 -*-
"""从 hf-mirror 拉取 DuReader-retrieval dev split(免鉴权,国内直连)。

数据本体不入 git(license 为研究用途,重分发口径存疑),clone 者跑本脚本自取,
口径与官方发布一致——这也是"公开数据集实验可复现"的正确姿势。

输入: 无
输出: data/raw/dev.jsonl.gz

用法: python src/download_data.py
"""
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = ("https://hf-mirror.com/datasets/zyznull/dureader-retrieval-ranking/"
       "resolve/main/dev.jsonl.gz")


def main():
    out = ROOT / "data" / "raw" / "dev.jsonl.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        print(f"already exists: {out} ({out.stat().st_size} bytes), skip")
        return
    print(f"downloading: {URL}")
    req = urllib.request.Request(URL, headers={"User-Agent": "rag-rerank-lab"})
    with urllib.request.urlopen(req, timeout=600) as r, open(out, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    print(f"saved: {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
