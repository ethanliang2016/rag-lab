# -*- coding: utf-8 -*-
"""实验四补充分析:一致性细节 + 分歧案例导出。

输入:results/judge_scores.jsonl, data/cmrc/judge_set.jsonl
输出:results/judge_cases.md(可直接贴进文章) + 终端摘要

看十件事:
  1 裁判自洽性: score>=4 是否等于判定"对"(是否存在 5 分判错 / 3 分判对)
  2 一致性细节: kappa / PABAK / 2x2(正类压倒时 kappa 会被系统性压低)
  3 案例: wrong 层假阳性(裁判漏检)
  4 案例: high_f1_low_em(EM 误杀) / F1=0 判对 / 裁判冤枉 EM=1
  5 noise0 vs noise5 配对: 裁判对"质量下降"到底有没有反应
  6 prompt 三档逐样本: 判定翻转率
  7 自检: main(rubric) 与 prompt(rubric) 同批同提示词, 判定应一致
  8 bare 低分判对 × rubric 配对: 分数尺度由提示词决定, 判定方向不变
  9 F1 分档 × 14B 判定: 7B/14B 分歧是否集中在低 F1 段
 10 人工裁定表: 7B/14B 分歧 + 严格口径假阴性候选(含问/金/答/三方理由)

用法: python src/analyze_judge_cases.py
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORES = ROOT / "results" / "judge_scores.jsonl"
JUDGE_SET = ROOT / "data" / "cmrc" / "judge_set.jsonl"
OUT = ROOT / "results" / "judge_cases.md"


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    rows = read_jsonl(SCORES)
    items = {r["key"]: r for r in read_jsonl(JUDGE_SET)}
    L = ["# 实验四补充分析\n"]
    p = print

    # ---------- 1 裁判自洽性 ----------
    p("\n[1] 裁判自洽性（score>=4 应等于判定：对）")
    L.append("\n## 1. 裁判自洽性（分数与判定是否自相矛盾）\n")
    for tag in sorted(set(r["tag"] for r in rows)):
        g = [r for r in rows if r["tag"] == tag and r["score"] is not None]
        bad = [r for r in g if (r["score"] >= 4) != (r["correct"] == 1)]
        rate = len(bad) / max(len(g), 1) * 100
        p(f"    {tag:<45} n={len(g):>5}  矛盾={len(bad):>3} ({rate:.2f}%)")
        L.append(f"- `{tag}`：n={len(g)}，矛盾 **{len(bad)}** 条（{rate:.2f}%）")
        for r in bad[:3]:
            L.append(f"  - `{r['key']}` score={r['score']} correct={r['correct']} "
                     f"raw={r['raw'][:70]!r}")

    # ---------- 2 一致性细节 ----------
    m1 = {r["key"]: r["correct"] for r in rows
          if r["tag"].startswith("main|") and r["correct"] is not None}
    m2 = {r["key"]: r["correct"] for r in rows
          if r["tag"].startswith("judge2|") and r["correct"] is not None}
    common = sorted(set(m1) & set(m2))
    a, b = [m1[k] for k in common], [m2[k] for k in common]
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa1, pb1 = sum(a) / n, sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    kappa = (po - pe) / (1 - pe)
    pabak = 2 * po - 1
    both_w = sum(1 for x, y in zip(a, b) if x == 0 and y == 0)
    a_only = sum(1 for x, y in zip(a, b) if x == 0 and y == 1)
    b_only = sum(1 for x, y in zip(a, b) if x == 1 and y == 0)
    both_r = n - both_w - a_only - b_only
    p(f"\n[2] 一致性 n={n} Po={po:.4f} Pe={pe:.4f} kappa={kappa:.4f} PABAK={pabak:.4f}")
    p(f"    2x2: 都对={both_r} 都错={both_w} 7B错/14B对={a_only} 7B对/14B错={b_only}")
    L.append(f"\n## 2. 两裁判一致性\n\n- n={n}，Po={po:.4f}，Pe={pe:.4f}（正类 {pa1:.1%}），"
             f"kappa={kappa:.4f}，**PABAK={pabak:.4f}**")
    L.append(f"- 2x2：都对={both_r}｜都错={both_w}｜7B错·14B对={a_only}｜7B对·14B错={b_only}")
    L.append(f"- 7B 判对率 {pa1:.4f}，14B 判对率 {pb1:.4f}（14B 更严格）")

    # ---------- 3/4 案例 ----------
    def block(title, recs):
        L.append(f"\n## {title}\n")
        p(f"\n[{title}] {len(recs)} 条")
        for r in recs:
            it = items.get(r["key"].split("#")[0], {})
            L.append(f"### `{r['key']}`　EM={r['em']}　F1={r['f1']:.3f}　"
                     f"裁判 {r['score']} 分 / {'对' if r['correct'] else '错'}\n")
            if it:
                L.append(f"- **问**：{it.get('question', '')}")
                L.append(f"- **金**：{it.get('gold', '')}")
                L.append(f"- **答**：{it.get('generated', '')}")
            L.append(f"- **裁判理由**：{r.get('reason', '')}\n")

    anc = [r for r in rows if r.get("anchor")]
    block("3A. wrong 层被判「对」——裁判漏检（F1≤0.05 却判对）",
          [r for r in anc if r["anchor"] == "wrong" and r["correct"] == 1])
    block("3B. high_f1_low_em——EM 误杀典型（F1≥0.9 却 EM=0，取前 8）",
          [r for r in anc if r["anchor"] == "high_f1_low_em"][:8])
    block("3C. 裁判「冤枉」EM=1 的样本（main 组全部）",
          [r for r in rows if r["tag"].startswith("main|")
           and r["em"] == 1 and r["correct"] == 0])
    block("3D. main 组 F1=0 却被判「对」（取前 10）",
          [r for r in rows if r["tag"].startswith("main|")
           and r["f1"] == 0 and r["correct"] == 1][:10])

    # ---------- 5 noise 配对 ----------
    idx = {}
    for r in rows:
        if r["tag"].startswith("main|"):
            idx[(r["qid"], r["gen_variant"])] = r
    pairs = [idx[(k[0], "noise0")] for k in idx if k[1] == "noise0"]
    pairs = [(r, idx[(r["qid"], "noise5")]) for r in pairs if (r["qid"], "noise5") in idx]
    if pairs:
        N = len(pairs)
        n0 = sum(1 for x, _ in pairs if x["correct"] == 1)
        n5 = sum(1 for _, y in pairs if y["correct"] == 1)
        n05 = sum(1 for x, y in pairs if x["correct"] == 1 and y["correct"] == 0)
        n50 = sum(1 for x, y in pairs if x["correct"] == 0 and y["correct"] == 1)
        f0 = sum(x["f1"] for x, _ in pairs) / N
        f5 = sum(y["f1"] for _, y in pairs) / N
        e0 = sum(x["em"] for x, _ in pairs) / N
        e5 = sum(y["em"] for _, y in pairs) / N
        p(f"\n[5] noise0 vs noise5 配对 n={N}")
        p(f"    判对率 {n0/N:.4f} → {n5/N:.4f} 差={(n0-n5)/N:+.4f}")
        p(f"    F1     {f0:.4f} → {f5:.4f} 差={f0-f5:+.4f}")
        p(f"    EM     {e0:.4f} → {e5:.4f} 差={e0-e5:+.4f}")
        p(f"    翻转: 0对→5错={n05}  0错→5对={n50}")
        L.append(f"\n## 5. noise0 vs noise5 配对（同 qid，n={N}）\n")
        L.append("| 指标 | noise0 | noise5 | 变化 |")
        L.append("|---|---|---|---|")
        L.append(f"| judge 判对率 | {n0/N:.4f} | {n5/N:.4f} | **{(n0-n5)/N:+.4f}** |")
        L.append(f"| F1 均值 | {f0:.4f} | {f5:.4f} | **{f0-f5:+.4f}** |")
        L.append(f"| EM 均值 | {e0:.4f} | {e5:.4f} | **{e0-e5:+.4f}** |")
        L.append(f"\n判定翻转：noise0对→noise5错 = {n05}，noise0错→noise5对 = {n50}")

    # ---------- 6 prompt 三档 ----------
    pv = defaultdict(dict)
    for r in rows:
        if r["tag"].startswith("prompt|") and r["correct"] is not None:
            pv[r["key"]][r["prompt_variant"]] = r["correct"]
    full = {k: v for k, v in pv.items() if len(v) == 3}
    if full:
        p(f"\n[6] prompt 三档逐样本 n={len(full)}")
        L.append(f"\n## 6. prompt 三档逐样本判定差异（n={len(full)}）\n")
        for x, y in (("bare", "rubric"), ("bare", "cot"), ("rubric", "cot")):
            f = sum(1 for v in full.values() if v[x] != v[y])
            p(f"    {x:<7} vs {y:<7} 判定不同 {f:>4} 条 ({f/len(full)*100:.2f}%)")
            L.append(f"- {x} vs {y}：判定不同 **{f}** 条（{f/len(full)*100:.2f}%）")

    # ---------- 7 自检 ----------
    mainr = {r["key"]: r for r in rows if r["tag"].startswith("main|")}
    promr = {r["key"]: r for r in rows if r["tag"].startswith("prompt|")
             and r["prompt_variant"] == "rubric"}
    common2 = sorted(set(mainr) & set(promr))
    if common2:
        diff = [k for k in common2 if mainr[k]["correct"] != promr[k]["correct"]]
        sdiff = [k for k in common2 if mainr[k]["score"] != promr[k]["score"]]
        p(f"\n[7] 自检 main(rubric) vs prompt(rubric) n={len(common2)}")
        p(f"    判定不同={len(diff)} ({len(diff)/len(common2)*100:.2f}%)  "
          f"分数不同={len(sdiff)} ({len(sdiff)/len(common2)*100:.2f}%)")
        L.append(f"\n## 7. 自检：main 与 prompt 的 rubric 档（同批同提示词）\n")
        L.append(f"- n={len(common2)}，判定不同 **{len(diff)}** 条"
                 f"（{len(diff)/len(common2)*100:.2f}%），分数不同 **{len(sdiff)}** 条"
                 f"（{len(sdiff)/len(common2)*100:.2f}%）")

    # ---------- 8 bare 低分判对 × rubric 配对 ----------
    Idx = {}
    for r in rows:
        Idx[(r["tag"].split("|")[0], r["prompt_variant"], r["qid"], r["gen_variant"])] = r

    def get(mode, pv, r):
        return Idx.get((mode, pv, r["qid"], r["gen_variant"]))

    bare_bad = [r for r in rows if r["tag"].startswith("prompt|")
                and r["prompt_variant"] == "bare" and r["score"] is not None
                and (r["score"] >= 4) != (r["correct"] == 1)]
    tri = [(b, get("main", "rubric", b), get("judge2", "rubric", b)) for b in bare_bad]
    tri = [t for t in tri if t[1] and t[2]]

    if tri:
        fb = sum(b["score"] for b, _, _ in tri) / len(tri)
        fr = sum(m["score"] for _, m, _ in tri) / len(tri)
        bc, rc = defaultdict(int), defaultdict(int)
        for b, m, _ in tri:
            bc[b["score"]] += 1
            rc[m["score"]] += 1
        same = sum(1 for b, m, _ in tri if b["correct"] == m["correct"])
        n14w = sum(1 for _, _, m in tri if m["correct"] == 0)
        p(f"\n[8] bare 低分判对 n={len(tri)} × rubric 配对")
        p(f"    bare   均分={fb:.2f} 分布={dict(sorted(bc.items()))}")
        p(f"    rubric 均分={fr:.2f} 分布={dict(sorted(rc.items()))}")
        p(f"    判定一致={same}/{len(tri)}   14B 翻案={n14w}")
        L.append("\n## 8. 同一批样本的分数尺度（bare vs rubric，配对）\n")
        L.append(f"- n={len(tri)}（bare 判定「对」但 score<4 的样本）")
        L.append(f"- **bare 均分 {fb:.2f}**，分布 {dict(sorted(bc.items()))}")
        L.append(f"- **rubric 均分 {fr:.2f}**，分布 {dict(sorted(rc.items()))}")
        L.append(f"- 分差 **{fr - fb:+.2f}**；两档判定一致率 {same / len(tri):.1%}")
        L.append("- 读法：判定方向由内容决定，**分数尺度由提示词决定**\n")

        # ---------- 9 F1 分档 × 14B ----------
        p(f"\n[9] F1 分档 × 14B 判定")
        L.append("\n## 9. F1 分档 × 14B 判定\n")
        L.append("| F1 区间 | n | 14B 判对 | 14B 判错 | 翻案率 |")
        L.append("|---|---|---|---|---|")
        for lo, hi in [(0, 0.2), (0.2, 0.5), (0.5, 1.01)]:
            sub = [t for t in tri if lo <= t[0]["f1"] < hi]
            if not sub:
                continue
            ok = sum(1 for _, _, m in sub if m["correct"] == 1)
            p(f"    F1∈[{lo},{hi}) n={len(sub):>2} 14B判对={ok:>2} 判错={len(sub) - ok:>2}")
            L.append(f"| [{lo}, {hi}) | {len(sub)} | {ok} | {len(sub) - ok} "
                     f"| {(len(sub) - ok) / len(sub):.1%} |")
        L.append("\n> 分歧若源于「14B 更严格」，应集中在最低 F1 段；实测峰值在 **0.2~0.5**，"
                 "指向「含金标但掺入冗余」这一争议区。\n")

        # ---------- 10 人工裁定表 ----------
        dis = [(b, m1, m2) for b, m1, m2 in tri if m2["correct"] == 0]
        cand = sorted([t for t in tri if t[2]["correct"] == 1 and t[0]["f1"] < 0.2],
                      key=lambda t: t[0]["f1"])[:6]
        def _dedup(seq):
            """同题同答去重：噪声档常生成完全相同的文本，避免人工重复裁定。"""
            seen, out = set(), []
            for _t in seq:
                _it = items.get(_t[0]["key"].split("#")[0], {})
                sig = (_t[0]["qid"], " ".join((_it.get("generated") or "").split()))
                if sig in seen:
                    continue
                seen.add(sig)
                out.append(_t)
            return out

        n_raw = len(dis) + len(cand)
        dis, cand = _dedup(dis), _dedup(cand)
        sel = dis + cand
        L.append(f"\n## 10. 人工裁定表（n={len(sel)}）\n")
        L.append(f"> 已按「同题同答」去重：原 {n_raw} 条 → {len(sel)} 条"
                 f"（噪声档常生成完全相同的文本）\n")
        L.append(f"> 前 {len(dis)} 条 = 7B 判对 / 14B 判错（模型间分歧）；"
                 f"后 {len(cand)} 条 = 两裁判都判「对」但 F1<0.2（严格口径假阴性候选）\n")
        L.append("> 裁定建议分两类：**A 冗余无害**（金标完整、多余内容不矛盾 → 判对）；"
                 "**B 冗余有害**（多余内容引入错误信息 → 判错）\n")
        L.append("| # | key | F1 | 7B-bare | 7B-rubric | 14B | 人工裁定 | 类别 |")
        L.append("|---|---|---|---|---|---|---|---|")
        yn = lambda r: f"{r['score']}/{'对' if r['correct'] else '错'}"
        rz = lambda r: " ".join((r.get("reason") or r.get("raw") or "").split())[:160]
        for i, (b, m1, m2) in enumerate(sel, 1):
            L.append(f"| {i} | `{b['key']}` | {b['f1']:.3f} | {yn(b)} "
                     f"| {yn(m1)} | {yn(m2)} | | |")
        L.append("")
        L.append("<details><summary>逐条明细（问题 / 金标 / 生成 / 三方理由）</summary>\n")
        for i, (b, m1, m2) in enumerate(sel, 1):
            it = items.get(b["key"].split("#")[0], {})
            L.append(f"\n### {i}. `{b['key']}`　EM={b['em']}　F1={b['f1']:.3f}\n")
            L.append(f"- **问**：{it.get('question', '')}")
            L.append(f"- **金**：{it.get('gold', '')}")
            L.append(f"- **答**：{it.get('generated', '')}")
            L.append(f"- **7B-bare**：{b['score']} 分 / "
                     f"{'对' if b['correct'] else '错'} — {rz(b)}")
            L.append(f"- **7B-rubric**：{m1['score']} 分 / "
                     f"{'对' if m1['correct'] else '错'} — {rz(m1)}")
            L.append(f"- **14B**：{m2['score']} 分 / "
                     f"{'对' if m2['correct'] else '错'} — {rz(m2)}")
            L.append("- **人工裁定**：⬜ 对　⬜ 错　类别：⬜A　⬜B")
        L.append("\n</details>\n")

    OUT.write_text("\n".join(L), encoding="utf-8")
    p(f"\nsaved → {OUT}")


if __name__ == "__main__":
    main()
