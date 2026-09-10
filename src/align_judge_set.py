# -*- coding: utf-8 -*-
"""实验四前置:构建 judge 评估集并做口径对齐。

把三份数据合成一张表,供 run_judge.py 直接消费:
  data/cmrc/sample.jsonl      800 题 question / answer_text(金标)
  results/cmrc_gen.jsonl      逐条生成(本地件 6216 行)
  score_em_f1 的字级 EM/F1   同一批生成的确定性评分(与第 3 篇主表同口径)

输出:
  data/cmrc/judge_set.jsonl   每行 {key,qid,mode,variant,question,gold,generated,
                                    em,f1,hit_gold,doc_chunks,ctx_chars,truncated}
对齐核验(打印):
  - 评估集条数、按 mode/variant 分布
  - 与主表 results/cmrc_gen_metrics.json 的 EM/F1 差异(应 ≤0.002)
  - jsonl 中存在但 sample 里没有的 qid(差集,如实记录不静默丢弃)
用法:
  python src/align_judge_set.py
"""
import json
from pathlib import Path

from score_em_f1 import score_pair          # 同目录,复用打分口径避免漂移

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "cmrc" / "sample.jsonl"
GEN = ROOT / "results" / "cmrc_gen.jsonl"
METRICS = ROOT / "results" / "cmrc_gen_metrics.json"
OUT = ROOT / "data" / "cmrc" / "judge_set.jsonl"


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    samples = {s["qid"]: s for s in read_jsonl(SAMPLE)}
    gens = read_jsonl(GEN)
    print(f"sample qids={len(samples)}  gen rows={len(gens)}")

    rows, miss_qid = [], set()
    for r in gens:
        s = samples.get(r["qid"])
        if s is None:                      # 差集:如实记录
            miss_qid.add(r["qid"])
            continue
        em, f1 = score_pair(r["generated"], s["answer_text"])
        rows.append({
            "key": f"{r['mode']}|{r['qid']}|{r['variant']}",
            "qid": r["qid"], "mode": r["mode"], "variant": r["variant"],
            "question": s["question"], "gold": s["answer_text"],
            "generated": r["generated"], "em": em, "f1": f1,
            "hit_gold": r.get("hit_gold", None),
            "doc_chunks": s.get("doc_chunks", 0),
            "ctx_chars": r.get("ctx_chars", 0),
            "truncated": r.get("truncated", False),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"judge_set rows={len(rows)} → {OUT}")
    if miss_qid:
        print(f"!! jsonl 中有 {len(miss_qid)} 个 qid 不在 sample(800) 内: "
              f"{sorted(miss_qid)[:5]}{'...' if len(miss_qid) > 5 else ''}")

    # ---------- 与主表对照 ----------
    def agg(sub):
        if not sub:
            return {"n": 0, "em": 0.0, "f1": 0.0}
        return {"n": len(sub),
                "em": round(sum(x["em"] for x in sub) / len(sub), 4),
                "f1": round(sum(x["f1"] for x in sub) / len(sub), 4)}

    print("\n档位    本评估集(n/EM/F1)            主表(EM/F1)")
    if METRICS.exists():
        m = json.loads(METRICS.read_text(encoding="utf-8"))["by_mode"]
        for mode in ("oracle_pos", "oracle_noise", "rag"):
            a = agg([r for r in rows if r["mode"] == mode])
            b = m.get(mode, {})
            print(f"  {mode:<13} {a['n']:>5} {a['em']:.4f}/{a['f1']:.4f}   "
                  f"{b.get('em', 0):.4f}/{b.get('f1', 0):.4f}")
        # ge3 位置主表
        ge3 = [r for r in rows if r["mode"] == "oracle_pos" and r["doc_chunks"] >= 3]
        print(f"  oracle_pos(ge3) {len(ge3)} 条")
        for v in ("top", "mid", "bottom"):
            a = agg([r for r in ge3 if r["variant"] == v])
            b = json.loads(METRICS.read_text(encoding="utf-8")).get(
                "position_effect_table", {}).get(v, {})
            print(f"    {v:<9} {a['n']:>5} {a['em']:.4f}/{a['f1']:.4f}   "
                  f"{b.get('em', 0):.4f}/{b.get('f1', 0):.4f}")
        for v in ("noise0", "noise1", "noise3", "noise5"):
            a = agg([r for r in rows if r["variant"] == v])
            b = m.get("oracle_noise", {}).get(v, {})
            print(f"    {v:<9} {a['n']:>5} {a['em']:.4f}/{a['f1']:.4f}   "
                  f"{b.get('em', 0):.4f}/{b.get('f1', 0):.4f}")
        for g in ("hit_gold", "miss_gold"):
            sub = [r for r in rows if r["mode"] == "rag" and
                   (r["hit_gold"] if g == "hit_gold" else not r["hit_gold"])]
            a = agg(sub)
            b = m.get("rag", {}).get(g, {})
            print(f"    {g:<9} {a['n']:>5} {a['em']:.4f}/{a['f1']:.4f}   "
                  f"{b.get('em', 0):.4f}/{b.get('f1', 0):.4f}")


if __name__ == "__main__":
    main()
