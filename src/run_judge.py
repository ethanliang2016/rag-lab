# -*- coding: utf-8 -*-
"""实验四:LLM-as-judge 跑批。

被测对象不是 RAG,而是「评测方法」本身:同一批生成,确定性 EM/F1 已有分,
再让大模型裁判打一遍分,比较两者。

输入:data/cmrc/judge_set.jsonl(由 align_judge_set.py 生成,6,208 条,
     每行含 question/gold/generated/em/f1/mode/variant/hit_gold)
模式(--mode):
  main    主裁判 × 全量 6,208 条(J1 视角 + rubric 提示词)
  judge2  对照裁判(--model 指定)× 子集(rag 800 + noise0/5 1,600)
  prompt  提示词三档(bare/rubric/cot)× noise0+noise5 1,600 条
  anchor  锚定样本:五类已知质量 × 60 条(每类从真实样本构造,固定种子)
视角(--view):
  j1  question + 金答案 + 模型输出(默认,有参考)
  j2  question + 模型输出(无参考,纯"像不像答案")
引擎:vLLM 优先,--engine transformers 回退(不碰 torch 版本时的兜底)
输出:results/judge_scores.jsonl,按 (tag,key) 断点续跑 --resume
用法:
  python src/run_judge.py --mode main --limit 50        # 冒烟
  python src/run_judge.py --mode main --resume          # 全量
  python src/run_judge.py --mode judge2 --model Qwen/Qwen2.5-14B-Instruct-AWQ
"""
import argparse
import json
import os
import random
import re
import time
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ROOT = Path(__file__).resolve().parent.parent
JUDGE_SET = ROOT / "data" / "cmrc" / "judge_set.jsonl"
OUT = ROOT / "results" / "judge_scores.jsonl"

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_TOKENS = {"bare": 64, "rubric": 64, "cot": 256}

SYSTEM = ("你是严格的中文问答评分员。只根据给定的标准答案判断模型回答是否正确,"
          "不要引入任何外部知识,不要因为回答写得流畅就加分。")

RUBRIC = """评分标准：
5 分：与标准答案完全一致（逐字相同）
4 分：含义完全正确，但多了或少了极少量字词
3 分：答中了核心，但混入了无关内容
2 分：只沾边，主体不对
1 分：基本错误
0 分：完全错误、答非所问、或回答「无答案」

判定规则：分数 ≥ 4 记为「对」，否则记为「错」。"""

PROMPTS = {
    "bare": ("请给下面这个回答打 0-5 分，并判断对或错。\n\n"
             "问题：{q}\n标准答案：{gold}\n模型回答：{gen}\n\n"
             "按以下格式输出：\n评分：<0-5 的整数>\n判定：<对|错>"),
    "rubric": (RUBRIC + "\n\n问题：{q}\n标准答案：{gold}\n模型回答：{gen}\n\n"
               "按以下格式输出：\n评分：<0-5 的整数>\n判定：<对|错>\n理由：<一句话>"),
    "cot": (RUBRIC + "\n\n问题：{q}\n标准答案：{gold}\n模型回答：{gen}\n\n"
            "先写一句你的判断理由，再给分。按以下格式输出：\n"
            "理由：<一句话>\n评分：<0-5 的整数>\n判定：<对|错>"),
}

PROMPTS_J2 = {
    "rubric": (RUBRIC + "\n\n问题：{q}\n模型回答：{gen}\n\n"
               "注意：你不看得到标准答案，请依据问题本身判断这个回答是否合理可信。\n"
               "按以下格式输出：\n评分：<0-5 的整数>\n判定：<对|错>\n理由：<一句话>"),
}


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_prompt(row: dict, variant: str, view: str) -> str:
    if view == "j2":
        tmpl = PROMPTS_J2.get(variant, PROMPTS_J2["rubric"])
        return tmpl.format(q=row["question"], gen=row["generated"])
    return PROMPTS[variant].format(q=row["question"], gold=row["gold"],
                                   gen=row["generated"])


def parse_out(text: str) -> dict:
    """解析裁判输出;解析失败如实标记,不静默丢弃。"""
    m_score = re.search(r"评分\s*[:：]\s*([0-5])", text)
    m_ver = re.search(r"判定\s*[:：]\s*([对错])", text)
    if not m_score:
        return {"score": None, "correct": None, "parse_fail": 1,
                "reason": text.strip()[:200]}
    score = int(m_score.group(1))
    if m_ver:
        correct = 1 if m_ver.group(1) == "对" else 0
    else:                                  # 判定缺失时按 rubric 规则推
        correct = 1 if score >= 4 else 0
    reason = ""
    m_r = re.search(r"理由\s*[:：]\s*(.+)", text)
    if m_r:
        reason = m_r.group(1).strip()[:200]
    return {"score": score, "correct": correct, "parse_fail": 0, "reason": reason}


def pick_subset(rows: list[dict], mode: str) -> list[dict]:
    if mode == "main":
        return rows
    if mode == "judge2":
        return [r for r in rows
                if r["mode"] == "rag" or r["variant"] in ("noise0", "noise5")]
    if mode == "prompt":
        return [r for r in rows if r["variant"] in ("noise0", "noise5")]
    return rows


def build_anchor(rows: list[dict], n_per: int = 60, seed: int = 42) -> list[dict]:
    """五类已知质量档位,全部从真实样本构造(可复现,不编造)。"""
    rng = random.Random(seed)
    out = []
    # 1) 完美:em=1
    c1 = [r for r in rows if r["em"] == 1]
    # 2) 高 F1 低 EM(典型错法:答案在里头但裹了别的东西)
    c2 = [r for r in rows if r["em"] == 0 and r["f1"] >= 0.9]
    # 3) 中等:答案沾边
    c3 = [r for r in rows if 0.3 <= r["f1"] < 0.6]
    # 4) 完全跑偏(用真实低分样本)
    c4 = [r for r in rows if r["f1"] <= 0.05 and r["generated"].strip() != "无答案"]
    # 5) 弃权
    c5 = [r for r in rows if r["generated"].strip() == "无答案"]
    for tag, pool in (("perfect", c1), ("high_f1_low_em", c2),
                      ("partial", c3), ("wrong", c4), ("abstain", c5)):
        pick = rng.sample(pool, min(n_per, len(pool)))
        for r in pick:
            out.append({**r, "_anchor": tag})
        print(f"  anchor/{tag}: 池 {len(pool)} → 取 {len(pick)}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="main",
                    choices=["main", "judge2", "prompt", "anchor"])
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--variant", default="rubric", choices=["bare", "rubric", "cot"])
    ap.add_argument("--view", default="j1", choices=["j1", "j2"])
    ap.add_argument("--engine", default="auto", choices=["auto", "vllm", "transformers"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    rows = read_jsonl(JUDGE_SET)
    if args.mode == "anchor":
        task_rows = build_anchor(rows)
        variants = ["rubric"]
    elif args.mode == "prompt":
        task_rows = pick_subset(rows, args.mode)
        variants = ["bare", "rubric", "cot"]
    else:
        task_rows = pick_subset(rows, args.mode)
        variants = [args.variant]

    if args.limit:
        task_rows = task_rows[: args.limit]

    tag = f"{args.mode}|{args.model.split('/')[-1]}|{args.variant}|{args.view}"

    # ---------- 断点续跑 ----------
    done = set()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if args.resume and OUT.exists():
        for l in OUT.read_text(encoding="utf-8").splitlines():
            if l.strip():
                d = json.loads(l)
                done.add((d["tag"], d["key"]))

    tasks = []
    for v in variants:
        for r in task_rows:
            k = r["key"] + (f"#{r['_anchor']}" if "_anchor" in r else "")
            if (tag, k) in done:
                continue
            tasks.append((v, r, k))
    print(f"mode={args.mode} model={args.model} rows={len(task_rows)} "
          f"variants={variants} pending={len(tasks)}")

    if not tasks:
        print("nothing to do")
        return

    prompts = [build_prompt(r, v, args.view) for v, r, _ in tasks]

    # ---------- 引擎 ----------
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    import torch
    has_gpu = torch.cuda.is_available()
    engine = args.engine
    if engine == "auto":
        try:
            import vllm  # noqa: F401
            engine = "vllm" if has_gpu else "transformers"
        except Exception:
            engine = "transformers"
    print(f"engine={engine} cuda={has_gpu}")

    msgs = [tok.apply_chat_template(
        [{"role": "system", "content": SYSTEM},
         {"role": "user", "content": p}], tokenize=False, add_generation_prompt=True)
        for p in prompts]

    t0 = time.time()
    texts = []
    if engine == "vllm":
        from vllm import LLM, SamplingParams
        llm = LLM(model=args.model, dtype="auto", max_model_len=8192,
                  gpu_memory_utilization=0.90, trust_remote_code=True)
        # 同一批内 max_tokens 取该批所需最大值
        mt = max(MAX_TOKENS[v] for v, _, _ in tasks)
        outs = llm.generate(msgs, SamplingParams(temperature=0.0, max_tokens=mt))
        texts = [o.outputs[0].text for o in outs]
    else:
        model = None
        for v, r, k in tasks:
            pass  # 逐条生成见下
        from transformers import AutoModelForCausalLM
        model = AutoModelForCausalLM.from_pretrained(
            args.model, torch_dtype=(torch.float16 if has_gpu else torch.float32),
            trust_remote_code=True).to("cuda" if has_gpu else "cpu").eval()
        for i, (v, r, k) in enumerate(tasks):
            mt = MAX_TOKENS[v]
            inp = tok(msgs[i], return_tensors="pt").to(model.device)
            o = model.generate(**inp, max_new_tokens=mt, do_sample=False)
            texts.append(tok.decode(o[0][inp["input_ids"].shape[1]:],
                                    skip_special_tokens=True))
            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(tasks)} ({time.time()-t0:.0f}s)")

    # ---------- 落盘 ----------
    n_fail = 0
    with OUT.open("a" if args.resume and OUT.exists() else "w", encoding="utf-8") as f:
        for (v, r, k), raw in zip(tasks, texts):
            p = parse_out(raw)
            n_fail += p["parse_fail"]
            f.write(json.dumps({
                "tag": tag, "key": k, "mode": args.mode,
                "judge_model": args.model, "prompt_variant": v, "view": args.view,
                "qid": r["qid"], "gen_mode": r["mode"], "gen_variant": r["variant"],
                "em": r["em"], "f1": r["f1"], "hit_gold": r.get("hit_gold"),
                "anchor": r.get("_anchor"),
                **p, "raw": raw.strip()[:300],
            }, ensure_ascii=False) + "\n")
    print(f"done {len(tasks)} → {OUT}  parse_fail={n_fail}  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
