# -*- coding: utf-8 -*-
"""第 5 篇（查询路由实测）配图。

  fig1_route_tradeoff.png  端到端 Hit@10 与延迟对照：路由是在用效果换速度
  fig2_misroute_cost.png   误判一次的代价：路由对 vs 路由错，对照同批基线
  fig3_breakeven.png       盈亏平衡曲线：路由准确率要多少才开始赚钱

输入:results/route_metrics_full.json、results/route_eval.jsonl
输出:results/writing/exp5/figures/*.png + summary.json

用法: python src/make_route_figures.py
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
METRICS = ROOT / "results" / "route_metrics_full.json"
EVAL = ROOT / "results" / "route_eval.jsonl"
OUTDIR = ROOT / "results" / "writing" / "exp5"
FIGDIR = OUTDIR / "figures"

C_BLUE = "#2b6cb0"
C_ORANGE = "#dd6b20"
C_GRAY = "#9aa0a6"
C_RED = "#c53030"
C_GREEN = "#2f855a"

LABEL = {"A": "A 基线\n全库", "B": "B BM25\n路由", "C": "C 嵌入\nTop-1",
         "D": "D 嵌入\nTop-2", "E": "E LLM\n0.5B"}

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "axes.unicode_minus": False,
    "figure.dpi": 200, "savefig.dpi": 200, "savefig.bbox": "tight",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#c8ccd2", "axes.labelcolor": "#333333",
    "text.color": "#333333", "xtick.color": "#555555", "ytick.color": "#555555",
    "font.size": 11,
})


def grid(ax, axis="y"):
    ax.grid(axis=axis, linestyle="--", linewidth=0.7, color="#dcdfe4", alpha=0.9)
    ax.set_axisbelow(True)


def save(fig, name):
    FIGDIR.mkdir(parents=True, exist_ok=True)
    p = FIGDIR / name
    fig.savefig(p)
    plt.close(fig)
    print(f"saved → {p}")


def main():
    M = json.loads(METRICS.read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in EVAL.open(encoding="utf-8")]
    OUTDIR.mkdir(parents=True, exist_ok=True)

    methods = [k for k in ["A", "B", "C", "D", "E"] if k in M["methods"]]
    n = M["n"]
    # 回退率过半的组（如 0.5B LLM，绝大多数没输出可解析的域）不构成有效路由，
    # 放进对比图会把"损失"稀释成 0，只留在 fig1 与正文里单独说明
    routed = [k for k in methods
              if k != "A" and M["methods"][k].get("n_fallback", 0) < n * 0.5]

    # ============ fig1：效果 vs 速度 ============
    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.4))
    ax = axes[0]
    vals = [M["methods"][m]["hit@10"] * 100 for m in methods]
    bars = ax.bar([LABEL[m] for m in methods], vals, 0.58,
                  color=[C_GRAY if m == "A" else C_BLUE for m in methods])
    for b, m in zip(bars, methods):
        d = M["methods"][m].get("hit@10_delta")
        txt = f"{b.get_height():.1f}%" + ("" if m == "A" else f"\n{d * 100:+.1f}pp")
        ax.annotate(txt, (b.get_x() + b.get_width() / 2, b.get_height()),
                    textcoords="offset points", xytext=(0, 2),
                    ha="center", fontsize=9.5)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Hit@10 (%)")
    ax.set_title("端到端效果：路由全都更差", fontsize=11.5)
    grid(ax)

    ax = axes[1]
    ms = [M["methods"][m]["ms_mean"] for m in methods]
    bars = ax.bar([LABEL[m] for m in methods], ms, 0.58,
                  color=[C_GRAY if m == "A" else C_ORANGE for m in methods])
    for b, m in zip(bars, methods):
        s = M["methods"][m]["speedup"]
        ax.annotate(f"{b.get_height():.1f}ms" + ("" if m == "A" else f"\n{s:.1f}×"),
                    (b.get_x() + b.get_width() / 2, b.get_height()),
                    textcoords="offset points", xytext=(0, 2), ha="center", fontsize=9.5)
    ax.set_ylim(0, max(ms) * 1.35)
    ax.set_ylabel("单次检索 (ms)")
    ax.set_title("但快了 1.9~3.9 倍", fontsize=11.5)
    grid(ax)
    fig.suptitle(f"路由的本质：用效果换速度（n={n}，DuReader 93,885 段落）",
                 fontsize=12.5, y=1.03)
    save(fig, "fig1_route_tradeoff.png")

    # ============ fig2：误判代价 ============
    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    x = np.arange(len(routed))
    w = 0.2
    ok_v = [M["misroute"][m]["hit10_ok"] * 100 for m in routed]
    bad_v = [M["misroute"][m]["hit10_bad"] * 100 for m in routed]
    ok_b = [M["misroute"][m]["hit10_ok_base"] * 100 for m in routed]
    bad_b = [M["misroute"][m]["hit10_bad_base"] * 100 for m in routed]

    b1 = ax.bar(x - w * 1.5, ok_b, w, color=C_GRAY, label="路由对 · 同批基线")
    b2 = ax.bar(x - w * 0.5, ok_v, w, color=C_GREEN, label="路由对 · 实际")
    b3 = ax.bar(x + w * 0.5, bad_b, w, color=C_GRAY,
                hatch="//", label="路由错 · 同批基线")
    b4 = ax.bar(x + w * 1.5, bad_v, w, color=C_RED, label="路由错 · 实际")
    for bars in (b1, b2, b3, b4):
        for b in bars:
            ax.annotate(f"{b.get_height():.0f}", (b.get_x() + b.get_width() / 2,
                                                  b.get_height()),
                        textcoords="offset points", xytext=(0, 2),
                        ha="center", fontsize=8.5)
    for i, m in enumerate(routed):
        loss = M["misroute"][m]["loss_pp"]
        # 损失数字必须放在红色柱「上方」——放在柱内会红字压红柱，看不见
        ax.annotate(f"损失 {loss:.0f}pp", (x[i] + w * 1.5, bad_v[i]),
                    textcoords="offset points", xytext=(0, 17),
                    ha="center", fontsize=10.5, color=C_RED, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels([LABEL[m].replace("\n", " ") for m in routed])
    ax.set_ylabel("Hit@10 (%)")
    ax.set_ylim(0, 132)
    ax.legend(frameon=False, loc="upper center", ncol=2, fontsize=9.5,
              bbox_to_anchor=(0.5, 1.0))
    ax.set_title("判对只赚 1pp，判错直接赔 50pp —— 非对称的代价", fontsize=12, pad=12)
    grid(ax)
    save(fig, "fig2_misroute_cost.png")

    # ============ fig3：盈亏平衡曲线 ============
    # 取路由方法里「判对收益」与「判错损失」的中位代表（用 B 组，单域路由的典型）
    ref = routed[0]
    gain = (M["misroute"][ref]["hit10_ok"] - M["misroute"][ref]["hit10_ok_base"]) * 100
    loss = -M["misroute"][ref]["loss_pp"]
    acc = np.linspace(0.5, 1.0, 501)
    delta = acc * gain + (1 - acc) * loss
    be = -loss / (gain - loss)

    fig, ax = plt.subplots(figsize=(8.6, 5.0))
    ax.plot(acc * 100, delta, linewidth=2.4, color=C_BLUE)
    ax.axhline(0, color="#666666", linewidth=1.0)
    ax.axvline(be * 100, color=C_RED, linestyle="--", linewidth=1.4)
    ax.fill_between(acc * 100, delta, 0, where=(delta < 0),
                    color=C_RED, alpha=0.10)
    ax.fill_between(acc * 100, delta, 0, where=(delta >= 0),
                    color=C_GREEN, alpha=0.12)
    ax.annotate(f"盈亏平衡点 {be * 100:.1f}%",
                (be * 100, 0), textcoords="offset points", xytext=(-96, 14),
                fontsize=11, color=C_RED, fontweight="bold")

    for m in routed:
        a = M["methods"][m]["route_acc"] * 100
        d = M["methods"][m]["hit@10_delta"] * 100
        ax.plot([a], [d], marker="o", markersize=9, color=C_ORANGE, zorder=5)
        ax.annotate(f"{LABEL[m].split(chr(10))[0]} {a:.1f}%", (a, d),
                    textcoords="offset points", xytext=(8, -14),
                    fontsize=10, color=C_ORANGE)
    ax.set_xlabel("路由准确率 (%)")
    ax.set_ylabel("端到端 Hit@10 变化 (pp)")
    ax.set_xlim(50, 100)
    ax.set_title(f"按实测「判对 +{gain:.1f}pp / 判错 {loss:.1f}pp」推算：\n"
                 f"路由准确率不到 {be * 100:.0f}%，就是在亏", fontsize=12, pad=12)
    grid(ax)
    save(fig, "fig3_breakeven.png")

    # ============ 摘要 ============
    summ = {
        "n": n,
        "corpus": 93885,
        "methods": M["methods"],
        "misroute": M["misroute"],
        "breakeven": {
            "gain_pp": gain, "loss_pp": loss,
            "breakeven_acc": be, "ref_method": ref,
        },
        "dom_query_dist": [sum(1 for r in rows if r["true_dom"] == i)
                           for i in range(max(r["true_dom"] for r in rows) + 1)],
    }
    (OUTDIR / "summary.json").write_text(
        json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved → {OUTDIR / 'summary.json'}")
    print(f"\n盈亏平衡：判对 +{gain:.2f}pp / 判错 {loss:.1f}pp → 需要 {be * 100:.2f}% 准确率")


if __name__ == "__main__":
    main()
