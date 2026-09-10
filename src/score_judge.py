# -*- coding: utf-8 -*-
"""实验四分析:judge 分数 vs 确定性 EM/F1。

输入:results/judge_scores.jsonl(run_judge.py 产物)
输出:results/judge_metrics.json + 打印分层表

观察项:
  1 判对率 vs EM(宽松多少)            6 按 F1 分段看分歧集中在哪
  2 混淆矩阵(假阳性/假阴性)           7 弃权样本 judge 怎么判
  3 judge 分 vs F1 的相关(Pearson/Spearman)  8 提示词三档及格率差异
  4 按档分层(noise/pos/rag hit/miss)  9 两裁判一致率 + Cohen's kappa
  5 anchor 五类已知质量的给分是否单调
依赖:numpy(scipy 不装, 秩相关手写)
用法: python src/score_judge.py
"""
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "results" / "judge_scores.jsonl"
OUT = ROOT / "results" / "judge_metrics.json"


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def pearson(x, y):
    if len(x) < 2:
        return 0.0
    x, y = np.asarray(x, float), np.asarray(y, float)
    sx, sy = x.std(), y.std()
    if sx == 0 or sy == 0:
        return 0.0
    return float(((x - x.mean()) * (y - y.mean())).mean() / (sx * sy))


def rank(a):
    a = np.asarray(a, float)
    order = a.argsort()
    r = np.empty(len(a), float)
    r[order] = np.arange(1, len(a) + 1)
    # 并列取平均秩
    for v in set(a.tolist()):
        idx = np.where(a == v)[0]
        if len(idx) > 1:
            r[idx] = r[idx].mean()
    return r


def spearman(x, y):
    return pearson(rank(x), rank(y))


def kappa(a, b):
    a, b = np.asarray(a), np.asarray(b)
    n = len(a)
    if n == 0:
        return 0.0
    po = float((a == b).mean())
    pe = sum(float((a == c).mean()) * float((b == c).mean()) for c in (0, 1))
    return (po - pe) / (1 - pe) if pe != 1 else 1.0


def agg(rows, key_score="score", key_correct="correct"):
    ok = [r for r in rows if r[key_score] is not None]
    if not ok:
        return {"n": len(rows), "scored": 0}
    return {
        "n": len(rows), "scored": len(ok),
        "mean_score": round(float(np.mean([r[key_score] for r in ok])), 4),
        "judge_acc": round(float(np.mean([r[key_correct] for r in ok])), 4),
        "em": round(float(np.mean([r["em"] for r in ok])), 4),
        "f1": round(float(np.mean([r["f1"] for r in ok])), 4),
        "parse_fail": sum(r["parse_fail"] for r in rows),
    }


def confusion(rows):
    tp = sum(1 for r in rows if r["correct"] == 1 and r["em"] == 1)
    fp = sum(1 for r in rows if r["correct"] == 1 and r["em"] == 0)   # judge 判对 EM=0
    fn = sum(1 for r in rows if r["correct"] == 0 and r["em"] == 1)
    tn = sum(1 for r in rows if r["correct"] == 0 and r["em"] == 0)
    return {"judge对_EM对": tp, "judge对_EM错(假阳性)": fp,
            "judge错_EM对(假阴性)": fn, "judge错_EM错": tn}


def main():
    rows = read_jsonl(SCORES)
    print(f"judge_scores rows={len(rows)}")
    tags = sorted(set(r["tag"] for r in rows))
    print("tags:", tags)

    out = {"n_rows": len(rows), "tags": tags, "by_tag": {}}

    # ---------- 主表:每个 tag 的基础对比 ----------
    for tag in tags:
        sub = [r for r in rows if r["tag"] == tag]
        a = agg(sub)
        a["confusion"] = confusion([r for r in sub if r["correct"] is not None])
        ok = [r for r in sub if r["score"] is not None]
        if ok:
            a["corr_f1_pearson"] = round(
                pearson([r["score"] for r in ok], [r["f1"] for r in ok]), 4)
            a["corr_f1_spearman"] = round(
                spearman([r["score"] for r in ok], [r["f1"] for r in ok]), 4)
            # 按 F1 分段
            bins = [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]
            a["f1_bins"] = []
            for lo, hi in bins:
                g = [r for r in ok if lo <= r["f1"] < hi]
                if not g:
                    continue
                a["f1_bins"].append({
                    "bin": f"[{lo:.1f},{hi:.1f})", "n": len(g),
                    "mean_score": round(float(np.mean([r["score"] for r in g])), 3),
                    "judge_acc": round(float(np.mean([r["correct"] for r in g])), 3),
                    "em": round(float(np.mean([r["em"] for r in g])), 3),
                })
            # 按生成档分层
            a["by_gen_variant"] = {}
            for v in sorted(set(r["gen_variant"] for r in ok)):
                g = [r for r in ok if r["gen_variant"] == v]
                a["by_gen_variant"][v] = agg(g)
            # rag 命中/缺失
            for name, cond in (("rag_hit", True), ("rag_miss", False)):
                g = [r for r in ok if r["gen_mode"] == "rag" and r["hit_gold"] is cond]
                if g:
                    a.setdefault("by_rag", {})[name] = agg(g)
            # 弃权样本
            g = [r for r in ok if r.get("raw") is not None and r["em"] == 0
                 and r["f1"] == 0]
            if g:
                a["zero_f1"] = agg(g)
        out["by_tag"][tag] = a

    # ---------- anchor:五类已知质量 ----------
    anc = [r for r in rows if r.get("anchor")]
    if anc:
        out["anchor"] = {}
        for tag_ in sorted(set(r["anchor"] for r in anc)):
            g = [r for r in anc if r["anchor"] == tag_]
            out["anchor"][tag_] = agg(g)
        print("\n[anchor] 五类已知质量的 judge 给分")
        for k, v in out["anchor"].items():
            print(f"  {k:<16} n={v.get('scored',0):>4}  均分={v.get('mean_score')}  "
                  f"判对率={v.get('judge_acc')}  EM={v.get('em')}")

    # ---------- 打印主表 ----------
    print("\n[主表] judge vs 确定性")
    for tag in tags:
        a = out["by_tag"][tag]
        print(f"  {tag}")
        print(f"    n={a.get('n')} 解析失败={a.get('parse_fail')}  "
              f"judge均分={a.get('mean_score')} 判对率={a.get('judge_acc')}  "
              f"EM={a.get('em')} F1={a.get('f1')}")
        print(f"    相关: pearson={a.get('corr_f1_pearson')} "
              f"spearman={a.get('corr_f1_spearman')}")
        print(f"    混淆: {a.get('confusion')}")

    # ---------- 两裁判一致率 ----------
    main_rows = [r for r in rows if r["tag"].startswith("main|")
                 and r["correct"] is not None]
    j2_rows = [r for r in rows if r["tag"].startswith("judge2|")
               and r["correct"] is not None]
    if main_rows and j2_rows:
        m1 = {r["key"]: r["correct"] for r in main_rows}
        m2 = {r["key"]: r["correct"] for r in j2_rows}
        common = sorted(set(m1) & set(m2))
        if common:
            a = [m1[k] for k in common]
            b = [m2[k] for k in common]
            out["two_judges"] = {
                "n_common": len(common),
                "agreement": round(float(np.mean([x == y for x, y in zip(a, b)])), 4),
                "kappa": round(kappa(a, b), 4),
                "acc_a": round(float(np.mean(a)), 4),
                "acc_b": round(float(np.mean(b)), 4),
            }
            print(f"\n[两裁判] {out['two_judges']}")

    # ---------- 提示词三档 ----------
    pv = {}
    for r in rows:
        if r["tag"].startswith("prompt|") and r["score"] is not None:
            pv.setdefault(r["prompt_variant"], []).append(r)
    if pv:
        out["prompt_variants"] = {}
        for k, g in sorted(pv.items()):
            out["prompt_variants"][k] = {
                **agg(g),
                "pass_rate": round(float(np.mean([1 if r["score"] >= 3 else 0
                                                  for r in g])), 4),
            }
        print("\n[提示词三档]")
        for k, v in out["prompt_variants"].items():
            print(f"  {k:<8} n={v['scored']:>4} 均分={v['mean_score']} "
                  f"判对率={v['judge_acc']} 及格率(≥3)={v['pass_rate']}")

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
