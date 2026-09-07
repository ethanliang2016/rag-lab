# -*- coding: utf-8 -*-
"""合并出题片段 → questions.jsonl,并做结构校验 + 疑似跨篇撞题检查。

用法: python src/merge_questions.py [--check-only]
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLE_IDS = {"dsh-startup", "dsh-plugin", "dsh-market", "dsh-197pkg",
               "arc-harness", "dsewiki", "skillspector", "glm53", "hy4-glm"}
META_RE = re.compile(r"这篇文章|作者|文中|本文")


def check(qs):
    errs = []
    seen_ids = set()
    for q in qs:
        if q["article_id"] not in ARTICLE_IDS:
            errs.append(f"未知 article_id: {q['article_id']}")
        if q["tier"] not in ("A", "B"):
            errs.append(f"{q['id']}: tier 非法 {q['tier']}")
        if q["id"] in seen_ids:
            errs.append(f"重复 id: {q['id']}")
        seen_ids.add(q["id"])
        if META_RE.search(q["question"]):
            errs.append(f"{q['id']}: 含元指涉 → {q['question']}")
        if not (8 <= len(q["question"]) <= 40):
            errs.append(f"{q['id']}: 长度异常({len(q['question'])}) → {q['question']}")
    by_art = Counter(q["article_id"] for q in qs)
    tier = Counter(q["tier"] for q in qs)
    return errs, by_art, tier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    qs = []
    for frag in sorted(ROOT.glob("questions-frag-*.jsonl")):
        for line in frag.read_text(encoding="utf-8").splitlines():
            if line.strip():
                qs.append(json.loads(line))

    errs, by_art, tier = check(qs)
    print(f"total={len(qs)}  tier={dict(tier)}")
    for a, n in sorted(by_art.items()):
        print(f"  {a:14s} {n}")
    if errs:
        print("\n[FAIL]")
        for e in errs:
            print(" ", e)
        raise SystemExit(1)
    print("schema OK")

    # 疑似撞题:两题 question 有 6+ 字公共子串且 article_id 不同 → 人工复核
    print("\n疑似跨篇撞题(需人工复核):")
    dup = 0
    for i in range(len(qs)):
        for j in range(i + 1, len(qs)):
            a, b = qs[i], qs[j]
            if a["article_id"] == b["article_id"]:
                continue
            # 6字滑窗交集
            grams = {a["question"][k:k+6] for k in range(len(a["question"]) - 5)}
            if any(b["question"][k:k+6] in grams for k in range(len(b["question"]) - 5)):
                print(f"  {a['id']} vs {b['id']}\n    {a['question']}\n    {b['question']}")
                dup += 1
    print(f"撞题疑点: {dup}")

    if not args.check_only:
        out = ROOT / "questions.jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for q in qs:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")
        print(f"\nsaved → {out}")


if __name__ == "__main__":
    main()
