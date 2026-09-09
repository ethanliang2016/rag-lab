# -*- coding: utf-8 -*-
"""第 3 篇打分:EM + 字级 F1(确定性,零 LLM 裁判)。

输入:results/cmrc_gen.jsonl(run_generate.py 产物)+ data/cmrc/sample.jsonl 金标
输出:results/cmrc_gen_metrics.json + 打印分层汇总表。

EM:规范化(剥首尾空白/引号)后与标准答案逐字相等。
F1:按单字切分(去空白)算字集重合——CMRC 中文短答案,字级近似官方口径,
   确定性、零第三方依赖;报告口径注明"字级"。

分层:
  oracle_pos  → 按 variant(sole/top/mid/bottom);doc_chunks>=3 子集是干净的位置效应主表
  oracle_noise→ 按噪声档 noise0/1/3/5(0=仅金块无噪声,基线)
  rag         → 总体 + 按 hit_gold 拆分(金块进没进 top-10 两组),是"检索误差经
                生成层最终代价"的归因表;另存 hit_gold 但答错样本(检索对、生成漏)
用法: python src/score_em_f1.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "results" / "cmrc_gen.jsonl"
SAMPLE = ROOT / "data" / "cmrc" / "sample.jsonl"
OUT = ROOT / "results" / "cmrc_gen_metrics.json"

_QUOTE_CHARS = "“”‘’「」『』“”\"" + "'"


def norm(s: str) -> str:
    s = s.strip()
    while s and s[0] in _QUOTE_CHARS:
        s = s[1:].strip()
    while s and s[-1] in _QUOTE_CHARS:
        s = s[:-1].strip()
    return s


def score_pair(gen: str, gold: str) -> tuple[int, float]:
    """返回 (EM, F1)。字级。"""
    g, a = norm(gen), norm(gold)
    em = int(g == a)
    if not g and not a:
        return em, 1.0
    gs, as_ = set(g), set(a)
    inter = len(gs & as_)
    if not gs or not as_:
        return em, 0.0
    p, r = inter / len(gs), inter / len(as_)
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return em, f1


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").split("\n") if l.strip()]


def agg(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "em": 0.0, "f1": 0.0}
    n = len(rows)
    return {"n": n,
            "em": round(sum(r["em"] for r in rows) / n, 4),
            "f1": round(sum(r["f1"] for r in rows) / n, 4)}


def main():
    rows = read_jsonl(GEN)
    golds = {s["qid"]: s for s in read_jsonl(SAMPLE)}
    scored = []
    for r in rows:
        gold = golds.get(r["qid"])
        if gold is None:
            continue
        em, f1 = score_pair(r["generated"], gold["answer_text"])
        scored.append({**r, "em": em, "f1": f1,
                       "gold": gold["answer_text"], "doc_chunks": gold["doc_chunks"]})

    by_mode = {}
    pos_tables = {}
    for mode in ("oracle_pos", "oracle_noise", "rag"):
        sub = [r for r in scored if r["mode"] == mode]
        by_mode[mode] = agg(sub)
        if mode == "oracle_pos":
            ge3 = [r for r in sub if r["doc_chunks"] >= 3]
            by_mode[mode]["ge3_chunks"] = agg(ge3)
            for v in ("sole", "top", "mid", "bottom"):
                vs = [r for r in sub if r["variant"] == v]
                by_mode[mode][f"pos_{v}"] = agg(vs)
                if v in ("top", "mid", "bottom"):
                    pos_tables[v] = agg([r for r in ge3 if r["variant"] == v])
        elif mode == "oracle_noise":
            for n in ("0", "1", "3", "5"):
                by_mode[mode][f"noise{n}"] = agg(
                    [r for r in sub if r["variant"] == f"noise{n}"])
        elif mode == "rag":
            by_mode[mode]["hit_gold"] = agg([r for r in sub if r["hit_gold"]])
            by_mode[mode]["miss_gold"] = agg([r for r in sub if not r["hit_gold"]])
            # 检索对、生成漏的样本(写作素材:生成层自身窟窿)
            fails = [{"qid": r["qid"], "question": _question(golds, r["qid"]),
                      "variant": r["variant"], "gold": r["gold"],
                      "generated": r["generated"]}
                     for r in sub if r["hit_gold"] and r["em"] == 0][:15]
            by_mode[mode]["retrieval_ok_gen_fail_examples"] = fails

    out = {"n_generations": len(scored), "by_mode": by_mode,
           "position_effect_table": pos_tables}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    def line(k, m):
        print(f"  {k:<24s} n={m['n']:>5d}  EM={m['em']:.3f}  F1={m['f1']:.3f}")

    print(f"n_generations={len(scored)}")
    print("[oracle_pos] 位置效应(上下文块数>=3 为主表)")
    line("overall", by_mode["oracle_pos"])
    line("  ge3_chunks", by_mode["oracle_pos"]["ge3_chunks"])
    for v in ("top", "mid", "bottom"):
        line(f"  pos_{v}(ge3)", by_mode["oracle_pos"][f"pos_{v}"])
    print("[oracle_noise] 噪声干扰(0=基线)")
    line("overall", by_mode["oracle_noise"])
    for n in ("0", "1", "3", "5"):
        line(f"  noise{n}", by_mode["oracle_noise"][f"noise{n}"])
    print("[rag] 端到端")
    line("overall", by_mode["rag"])
    line("  hit_gold", by_mode["rag"]["hit_gold"])
    line("  miss_gold", by_mode["rag"]["miss_gold"])
    print(f"\nsaved → {OUT}")


def _question(golds, qid):
    g = golds.get(qid)
    return g["question"] if g else ""


if __name__ == "__main__":
    main()
