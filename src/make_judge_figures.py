# -*- coding: utf-8 -*-
"""实验四配图:裁判可信性四张图 + 可引用的数字摘要。

输入:results/judge_metrics.json(score_judge.py 产出)+ results/judge_scores.jsonl(逐条打分)
输出:results/writing/exp4/figures/*.png + results/writing/exp4/summary.json

四张图:
  fig1_f1_saturation.png   F1 分档 → 裁判判对率 vs EM 率(主表 7B, n=6,208)
  fig2_prompt_scale.png    提示词三档:均分 / 与 EM 判定一致率 / 自洽矛盾率(反着走)
  fig3_noise_response.png  noise0→noise5 三条斜率:判对率几乎不动,F1 与 EM 下滑
  fig4_midband_disagree.png 78 条配对的 14B 翻案率按 F1 分档(峰值在中段,非单调)

用法: python src/make_judge_figures.py
"""
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
METRICS = ROOT / "results" / "judge_metrics.json"
SCORES = ROOT / "results" / "judge_scores.jsonl"
OUTDIR = ROOT / "results" / "writing" / "exp4"
FIGDIR = OUTDIR / "figures"

C_BLUE = "#2b6cb0"
C_ORANGE = "#dd6b20"
C_GRAY = "#9aa0a6"
C_RED = "#c53030"

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "axes.unicode_minus": False,
    "figure.dpi": 200,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "#c8ccd2",
    "axes.labelcolor": "#333333",
    "text.color": "#333333",
    "xtick.color": "#555555",
    "ytick.color": "#555555",
    "font.size": 11,
})


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def grid(ax, axis="y"):
    ax.grid(axis=axis, linestyle="--", linewidth=0.7, color="#dcdfe4", alpha=0.9)
    ax.set_axisbelow(True)


def save(fig, name):
    FIGDIR.mkdir(parents=True, exist_ok=True)
    p = FIGDIR / name
    fig.savefig(p)
    plt.close(fig)
    print(f"saved → {p}")


def bar_labels(ax, bars, fmt="{:.1f}%", pad=1.5, size=10):
    for b in bars:
        ax.annotate(fmt.format(b.get_height()),
                    (b.get_x() + b.get_width() / 2, b.get_height()),
                    textcoords="offset points", xytext=(0, pad),
                    ha="center", fontsize=size, color="#333333")


def main():
    M = json.loads(METRICS.read_text(encoding="utf-8"))
    rows = read_jsonl(SCORES)
    OUTDIR.mkdir(parents=True, exist_ok=True)

    main_tag = "main|Qwen2.5-7B-Instruct|rubric|j1"
    M_main = M["by_tag"][main_tag]
    summary = {}

    # ================= fig1:F1 分档 → 判对率 vs EM 率 =================
    bins = M_main["f1_bins"]
    labels = [b["bin"].replace("0.0", "0").replace("1.0", "1") for b in bins]
    acc = [b["judge_acc"] * 100 for b in bins]
    em = [b["em"] * 100 for b in bins]
    ns = [b["n"] for b in bins]

    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    x = range(len(bins))
    w = 0.38
    b1 = ax.bar([i - w / 2 for i in x], acc, w, label="裁判判对率", color=C_BLUE)
    b2 = ax.bar([i + w / 2 for i in x], em, w, label="EM（逐字正确率）", color=C_GRAY)
    bar_labels(ax, b1)
    bar_labels(ax, b2)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{l}\nn={n}" for l, n in zip(labels, ns)])
    ax.set_xlabel("字级 F1 区间")
    ax.set_ylabel("占比 (%)")
    ax.set_ylim(0, 122)
    ax.legend(frameon=False, loc="upper left")
    ax.set_title("裁判的「对」在 F1≥0.2 就饱和，EM 到 F1 0.8 以上才抬头（n=6,208）",
                 fontsize=12, pad=12)
    grid(ax)
    save(fig, "fig1_f1_saturation.png")
    summary["fig1_f1_bins"] = bins

    # ================= fig2:提示词三档的量尺 =================
    order = ["bare", "rubric", "cot"]
    pv = M["prompt_variants"]
    names = {"bare": "bare\n（直接判）", "rubric": "rubric\n（给评分标准）",
             "cot": "cot\n（先推理再判）"}
    mean_score = [pv[k]["mean_score"] for k in order]
    agree = [pv[k]["judge_acc"] * 100 for k in order]

    inc = {}
    for v in order:
        g = [r for r in rows if r["tag"].startswith("prompt|")
             and r.get("prompt_variant") == v and r.get("score") is not None]
        bad = [r for r in g if (r["score"] >= 4) != (r["correct"] == 1)]
        inc[v] = (len(bad) / max(len(g), 1) * 100, len(g), len(bad))

    fig, axes = plt.subplots(1, 3, figsize=(11.6, 4.2))
    panels = [
        (mean_score, "均分（0~5）", C_BLUE, "{:.3f}", 4.5, 5.2),
        (agree, "与 EM 判定一致率 (%)", C_ORANGE, "{:.1f}%", 80, 112),
        ([inc[k][0] for k in order], "自洽矛盾率 (%)", C_RED, "{:.2f}%", 0, 6.6),
    ]
    for ax, (vals, title, color, fmt, y0, y1) in zip(axes, panels):
        bars = ax.bar([names[k].split("\n")[0] for k in order], vals, 0.58, color=color)
        bar_labels(ax, bars, fmt=fmt)
        ax.set_ylim(y0, y1)
        ax.set_title(title, fontsize=11)
        grid(ax)
    fig.suptitle("均分最高的那档，一致率最低、自相矛盾最多（同批 1,600 条 × 3 档）",
                 fontsize=12.5, y=1.02)
    save(fig, "fig2_prompt_scale.png")
    summary["fig2_prompt"] = {
        k: {"mean_score": pv[k]["mean_score"], "agree_em": pv[k]["judge_acc"],
            "pass_rate": pv[k]["pass_rate"], "inconsistent": inc[k][0],
            "inconsistent_n": inc[k][2], "n": inc[k][1]}
        for k in order
    }

    # ================= fig3:noise0 → noise5 的三条斜率 =================
    gv = M_main["by_gen_variant"]
    pair = {
        "裁判判对率": [gv["noise0"]["judge_acc"] * 100, gv["noise5"]["judge_acc"] * 100],
        "字级 F1": [gv["noise0"]["f1"] * 100, gv["noise5"]["f1"] * 100],
        "EM": [gv["noise0"]["em"] * 100, gv["noise5"]["em"] * 100],
    }
    style = {"裁判判对率": (C_BLUE, "o"), "字级 F1": (C_ORANGE, "s"), "EM": (C_RED, "^")}

    fig, ax = plt.subplots(figsize=(7.6, 4.8))
    for k, (v0, v5) in pair.items():
        c, m = style[k]
        ax.plot([0, 1], [v0, v5], marker=m, markersize=9, linewidth=2.4,
                color=c, label=f"{k}（{v5 - v0:+.2f}pp）")
        ax.annotate(f"{v0:.2f}", (0, v0), textcoords="offset points", xytext=(-14, 6),
                    fontsize=10, color=c)
        ax.annotate(f"{v5:.2f}", (1, v5), textcoords="offset points", xytext=(10, -4),
                    fontsize=10, color=c)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["noise0\n（仅答案块）", "noise5\n（掺 5 个干扰块）"])
    ax.set_xlim(-0.35, 1.35)
    ax.set_ylim(0, 105)
    ax.set_ylabel("数值 (%)")
    ax.legend(frameon=False, loc="center left")
    ax.set_title("同题配对 800 组：F1 掉 8.78pp、EM 掉 6.75pp，判对率只动 0.13pp",
                 fontsize=12, pad=12)
    grid(ax)
    save(fig, "fig3_noise_response.png")
    summary["fig3_noise_pair"] = {
        k: {"noise0": v[0], "noise5": v[1], "delta": v[1] - v[0]} for k, v in pair.items()
    }

    # ================= fig4:中段分歧(78 条配对的 14B 翻案率) =================
    Idx = {}
    for r in rows:
        Idx[(r["tag"].split("|")[0], r.get("prompt_variant"),
             r["qid"], r["gen_variant"])] = r

    bare_bad = [r for r in rows if r["tag"].startswith("prompt|")
                and r.get("prompt_variant") == "bare" and r.get("score") is not None
                and (r["score"] >= 4) != (r["correct"] == 1)]
    tri = []
    for b in bare_bad:
        m1 = Idx.get(("main", "rubric", b["qid"], b["gen_variant"]))
        m2 = Idx.get(("judge2", "rubric", b["qid"], b["gen_variant"]))
        if m1 and m2:
            tri.append((b, m1, m2))

    bands = [(0.0, 0.2), (0.2, 0.5), (0.5, 1.01)]
    band_lab, band_n, band_rate = [], [], []
    for lo, hi in bands:
        sub = [t for t in tri if lo <= t[0]["f1"] < hi]
        wrong = sum(1 for _, _, m in sub if m["correct"] == 0)
        band_lab.append(f"[{lo:g}, {hi:g})" if hi <= 1 else f"[{lo:g}, 1]")
        band_n.append(len(sub))
        band_rate.append(wrong / max(len(sub), 1) * 100)

    fig, ax = plt.subplots(figsize=(7.4, 4.6))
    bars = ax.bar(band_lab, band_rate, 0.5, color=C_BLUE)
    bar_labels(ax, bars)
    for r_, n_ in zip(bars, band_n):
        ax.annotate(f"n={n_}", (r_.get_x() + r_.get_width() / 2, 0),
                    textcoords="offset points", xytext=(0, 6),
                    ha="center", fontsize=9.5, color="#ffffff")
    ax.set_ylim(0, 45)
    ax.set_xlabel("配对样本的 F1 区间（共 78 条）")
    ax.set_ylabel("14B 翻案率 (%)")
    ax.set_title("7B/14B 分歧不是「严格度差一档」：峰值在 F1 中段，两端反而一致",
                 fontsize=12, pad=12)
    grid(ax)
    save(fig, "fig4_midband_disagree.png")

    bare_avg = sum(t[0]["score"] for t in tri) / max(len(tri), 1)
    rub_avg = sum(t[1]["score"] for t in tri) / max(len(tri), 1)
    same = sum(1 for t in tri if t[0]["correct"] == t[1]["correct"])
    summary["fig4_tri"] = {
        "n": len(tri),
        "bare_mean_score": round(bare_avg, 4),
        "rubric_mean_score": round(rub_avg, 4),
        "judge_agree": same,
        "judge2_overrule": sum(1 for _, _, m in tri if m["correct"] == 0),
        "bands": [{"band": l, "n": n, "overrule_rate": round(r, 4)}
                  for l, n, r in zip(band_lab, band_n, band_rate)],
    }

    # ================= 摘要:关键数字 =================
    confusion = M_main["confusion"]
    summary["main"] = {
        "tag": main_tag, "n": M_main["n"], "mean_score": M_main["mean_score"],
        "judge_acc": M_main["judge_acc"], "em": M_main["em"], "f1": M_main["f1"],
        "confusion": confusion,
        "false_positive": confusion["judge对_EM错(假阳性)"],
        "false_negative": confusion["judge错_EM对(假阴性)"],
        "pearson": M_main["corr_f1_pearson"], "spearman": M_main["corr_f1_spearman"],
        "parse_fail": M_main["parse_fail"],
        "by_rag": {k: {"n": v["n"], "judge_acc": v["judge_acc"],
                       "mean_score": v["mean_score"], "f1": v["f1"]}
                   for k, v in M_main["by_rag"].items()},
        "zero_f1": M_main["zero_f1"],
    }
    summary["judge2"] = {
        "n": M["by_tag"]["judge2|Qwen2.5-14B-Instruct-AWQ|rubric|j1"]["n"],
        "judge_acc": M["by_tag"]["judge2|Qwen2.5-14B-Instruct-AWQ|rubric|j1"]["judge_acc"],
        "mean_score": M["by_tag"]["judge2|Qwen2.5-14B-Instruct-AWQ|rubric|j1"]["mean_score"],
        "pearson": M["by_tag"]["judge2|Qwen2.5-14B-Instruct-AWQ|rubric|j1"]["corr_f1_pearson"],
        "spearman": M["by_tag"]["judge2|Qwen2.5-14B-Instruct-AWQ|rubric|j1"]["corr_f1_spearman"],
    }
    summary["two_judges"] = M["two_judges"]
    summary["anchor"] = M["anchor"]

    # 复现噪声地板:同提示词同模型同批跑两遍
    m1 = {r["key"]: r for r in rows if r["tag"].startswith("main|")}
    pr = {r["key"]: r for r in rows if r["tag"].startswith("prompt|")
          and r.get("prompt_variant") == "rubric"}
    common = sorted(set(m1) & set(pr))
    summary["repro_noise"] = {
        "n": len(common),
        "verdict_diff": sum(1 for k in common if m1[k]["correct"] != pr[k]["correct"]),
        "score_diff": sum(1 for k in common if m1[k]["score"] != pr[k]["score"]),
    }

    (OUTDIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved → {OUTDIR / 'summary.json'}")
    print(f"    tri n={len(tri)}  bare均分={bare_avg:.2f} → rubric均分={rub_avg:.2f} "
          f"判定一致={same}/{len(tri)}  14B翻案={summary['fig4_tri']['judge2_overrule']}")
    for l, n, r in zip(band_lab, band_n, band_rate):
        print(f"    {l} n={n:>3} 翻案率={r:.1f}%")


if __name__ == "__main__":
    main()
