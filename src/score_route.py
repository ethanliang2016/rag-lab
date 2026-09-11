# -*- coding: utf-8 -*-
"""第 5 篇（查询路由实测）· 第三步：算指标，重点是「误判一次的代价」。

核心指标：
  1. 路由准确率（Top-1 / Top-2）
  2. 端到端 Hit@10 / Recall@10 / Hit@1
  3. 误路由的召回损失 —— 路由判错的那批 query，效果掉了多少
  4. 延迟：全库 vs 单域

输入:results/route_eval.jsonl
输出:results/route_metrics_full.json + 终端摘要

用法: python src/score_route.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "results" / "route_eval.jsonl"
OUT = ROOT / "results" / "route_metrics_full.json"

METHOD_NAME = {
    "A": "A 基线（不路由，全库）",
    "B": "B BM25 关键词路由",
    "C": "C 嵌入质心 Top-1",
    "D": "D 嵌入质心 Top-2",
    "E": "E LLM 路由（0.5B）",
}


def hit(rows, m, key="hit"):
    return sum(r[m][key] for r in rows) / max(len(rows), 1)


def split_by_route(rows, m):
    """拆成三批：判对 / 判错 / 回退（dom=-1，解析失败退回全库）。

    E 组（0.5B LLM 路由）绝大多数是回退，必须单独统计，
    否则"判错"桶里会塞满实际走了全库的样本，把损失算成 0，结论失真。
    """
    ok, bad, fallback = [], [], []
    for r in rows:
        d = r[m]["dom"]
        if d is None or d == -1:
            fallback.append(r)
            continue
        if (r["true_dom"] == d) or (isinstance(d, list) and r["true_dom"] in d):
            ok.append(r)
        else:
            bad.append(r)
    return ok, bad, fallback


def main():
    rows = [json.loads(l) for l in EVAL.open(encoding="utf-8")]
    methods = [k for k in METHOD_NAME if k in rows[0]]
    base = "A"

    out = {"n": len(rows), "methods": {}, "misroute": {}}
    print(f"n = {len(rows)}\n")

    print("=== 总览 ===")
    for m in methods:
        s = {
            "hit@1": hit(rows, m, "hit1"),
            "hit@10": hit(rows, m, "hit"),
            "recall@10": hit(rows, m, "rec"),
            "ms_mean": sum(r[m]["ms"] for r in rows) / len(rows),
        }
        s["route_acc"] = len(split_by_route(rows, m)[0]) / len(rows) if m != base else None
        s["n_fallback"] = len(split_by_route(rows, m)[2]) if m != base else 0
        s["hit@10_delta"] = s["hit@10"] - hit(rows, base, "hit")
        s["speedup"] = (sum(r[base]["ms"] for r in rows) / len(rows)) / max(s["ms_mean"], 1e-9)
        out["methods"][m] = s
        acc = f"{s['route_acc'] * 100:5.1f}%" if s["route_acc"] is not None else "   —  "
        print(f"{METHOD_NAME[m]:<22} 路由准确 {acc}  "
              f"Hit@1 {s['hit@1'] * 100:5.1f}%  Hit@10 {s['hit@10'] * 100:5.1f}%"
              f"（{s['hit@10_delta'] * 100:+.1f}pp）  "
              f"Recall@10 {s['recall@10'] * 100:5.1f}%  "
              f"{s['ms_mean']:6.2f}ms（{s['speedup']:.1f}×）")

    print("\n=== 误判一次的代价（全文核心）===")
    for m in methods:
        if m == base:
            continue
        ok, bad, fb = split_by_route(rows, m)
        if not bad:
            print(f"{METHOD_NAME[m]}")
            print(f"   回退到全库 {len(fb)} 条（模型没输出可解析的域），"
                  f"判对 {len(ok)} 条 —— 该组不构成有效路由，不参与下图对比")
            out["misroute"][m] = {"n_ok": len(ok), "n_bad": 0, "n_fallback": len(fb)}
            continue
        blk = {
            "n_ok": len(ok), "n_bad": len(bad), "n_fallback": len(fb),
            "hit10_ok": hit(ok, m), "hit10_ok_base": hit(ok, base),
            "hit10_bad": hit(bad, m), "hit10_bad_base": hit(bad, base),
        }
        blk["loss_pp"] = (blk["hit10_bad_base"] - blk["hit10_bad"]) * 100
        blk["loss_recall"] = (hit(bad, base, "rec") - hit(bad, m, "rec")) * 100
        out["misroute"][m] = blk
        print(f"{METHOD_NAME[m]}")
        print(f"   路由对 {len(ok):>3} 条：Hit@10 {blk['hit10_ok'] * 100:5.1f}%"
              f"（同批基线 {blk['hit10_ok_base'] * 100:5.1f}%，差 "
              f"{(blk['hit10_ok'] - blk['hit10_ok_base']) * 100:+.1f}pp）")
        print(f"   路由错 {len(bad):>3} 条：Hit@10 {blk['hit10_bad'] * 100:5.1f}%"
              f"（同批基线 {blk['hit10_bad_base'] * 100:5.1f}%）"
              f"  →  **损失 {blk['loss_pp']:.1f}pp**，Recall@10 损失 {blk['loss_recall']:.1f}pp")

    print("\n=== 各域真实分布（看路由是否偏袒大域）===")
    k = max(r["true_dom"] for r in rows) + 1
    dist = [sum(1 for r in rows if r["true_dom"] == i) for i in range(k)]
    for i, n in enumerate(dist):
        print(f"   域{i}: {n:>3} 条 query（{n / len(rows) * 100:.1f}%）")

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
