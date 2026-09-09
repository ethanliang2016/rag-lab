# -*- coding: utf-8 -*-
"""第 3 篇(生成层)主评测:三种上下文构造 → LLM 生成 → jsonl 落盘。

承接 prepare_cmrc.py 的产物(块 + offset 金标 + bge npz),测"检索把对的段落
送到嘴边后,生成模型还漏多少"。

变量:上下文构造方式(3 类,目标 800 题 ≈ 6,000 次生成)
  - oracle_pos  :金块在上下文开头/中间/末尾(其余为该文档真块按原文序填充)
                 → 中文版 lost-in-the-middle;按源文档块数 doc_n 分层,
                 doc_n>=3 的子集才是干净的位置效应主表
  - oracle_noise:金块置首 + 掺 0/1/3/5 个高相似干扰块(bge top-20 内非本
                 文档块) → 上下文里有答案时,噪声把答对率打到多少
  - rag         :端到端,bge top-10 块直接拼上下文(不保证含金块),记 hit_gold
                 → 检索误差经生成层的最终代价(score_em_f1.py 归因)
固定量:温度 0(贪婪)、单上下文 <= --max-ctx-chars 字符(超限从尾部丢块并标记)、
  bge 查询带第 2 篇实测更优的指令前缀。

引擎:vLLM(优先,GPU 吞吐)自动回退 transformers(--engine 强制指定);
模型默认 Qwen/Qwen2.5-7B-Instruct(--model 可换,14B 同理)。
断点续跑:results/cmrc_gen.jsonl 按 key 记完成,`--resume` 秒级跳过。

用法:
  python src/run_generate.py --mode oracle_pos          # 只跑位置效应
  python src/run_generate.py --mode all --resume        # 三档 + 断点续跑
  python src/run_generate.py --mode all --limit 8 --engine transformers --cpu  # 本地冒烟
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "cmrc"
RESULT_DIR = ROOT / "results"

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章:"
MAX_CTX_CHARS = 8000      # 拼入上下文的中文字符上限(截尾,超限算 truncated)
MAX_NEW_TOKENS = 150
RAG_TOP_K = 10
NOISE_POOL = 20           # 干扰块候选池:bge top-20 内排除本文档块
BATCH_VLLM = 128

SYSTEM_MSG = ("你是忠实的中文阅读助手。根据下面给出的文档回答问题。答案必须是"
              "文档中出现过的连续原文,直接输出该原文,不要解释、不要改写、不要补充"
              "任何文档外的内容。如果文档中没有能回答问题的内容,只输出:无答案")


def read_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").split("\n") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="all",
                    choices=["oracle_pos", "oracle_noise", "rag", "all"])
    ap.add_argument("--limit", type=int, default=None, help="只取前 N 题(冒烟)")
    ap.add_argument("--model", default=MODEL_NAME)
    ap.add_argument("--engine", default="auto", choices=["auto", "vllm", "transformers"])
    ap.add_argument("--cpu", action="store_true", help="强制 CPU(本地冒烟)")
    ap.add_argument("--resume", action="store_true", help="从已有 jsonl 断点续跑")
    ap.add_argument("--max-ctx-chars", type=int, default=MAX_CTX_CHARS)
    args = ap.parse_args()

    # ---------- 数据加载 ----------
    samples = read_jsonl(DATA_DIR / "sample.jsonl")
    passages = read_jsonl(DATA_DIR / "passages.jsonl")
    if args.limit:
        samples = samples[: args.limit]
    by_id = {c["chunk_id"]: c for c in passages}
    by_doc: dict[str, list] = {}
    for c in passages:
        by_doc.setdefault(c["docid"], []).append(c)
    for doc in by_doc.values():
        doc.sort(key=lambda x: x["start"])
    print(f"samples={len(samples)} passages={len(passages)}")

    # ---------- 任务构造 ----------
    tasks: list[dict] = []          # {mode, qid, variant, ctx_ids}
    need_retrieval = args.mode in ("oracle_noise", "rag", "all")
    for s in samples:
        gid = s["qid"]
        gold = s["gold_chunk"]      # 金块;None=答案跨切点(少见),无法 oracle
        doc_blocks = by_doc[gid]
        if gold is not None and args.mode in ("oracle_pos", "all"):
            gold_id = gold
            rest = [c for c in doc_blocks if c["chunk_id"] != gold_id]
            n = len(doc_blocks)
            variants = ["sole"] if n == 1 \
                else ["top", "bottom"] + (["mid"] if n >= 3 else [])
            for v in variants:
                if v == "sole":
                    order = [gold_id]
                elif v == "top":
                    order = [gold_id] + [c["chunk_id"] for c in rest]
                elif v == "bottom":
                    order = [c["chunk_id"] for c in rest] + [gold_id]
                else:
                    mid = [c["chunk_id"] for c in rest]
                    mid.insert(len(mid) // 2, gold_id)
                    order = mid
                tasks.append({"mode": "oracle_pos", "qid": gid,
                              "variant": v, "ctx_ids": order, "doc_n": n})
        if gold is not None and args.mode in ("oracle_noise", "all"):
            tasks.append({"mode": "oracle_noise", "qid": gid,
                          "variant": "noise0", "ctx_ids": [gold]})
            for k in (1, 3, 5):
                tasks.append({"mode": "oracle_noise", "qid": gid,
                              "variant": f"noise{k}", "ctx_ids": [gold]})
        if args.mode in ("rag", "all"):
            tasks.append({"mode": "rag", "qid": gid, "variant": "k10",
                          "ctx_ids": []})

    # ---------- 检索预计算(noise 干扰块 / rag top-10) ----------
    retrieval_top: dict[str, dict] = {}
    if need_retrieval:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        z = np.load(DATA_DIR / "cmrc_blocks.npz")
        vec_ids = [str(x) for x in z["ids"]]
        vecs = z["vectors"]
        emb_model = SentenceTransformer(EMBED_MODEL)
        qs = [s["question"] for s in samples]
        qe = emb_model.encode(
            [QUERY_INSTRUCTION + t for t in qs],
            normalize_embeddings=True, show_progress_bar=False)

        def topk(qv, k, exclude_doc=None):
            sims = qv @ vecs.T
            order = np.argsort(-sims)[:k]
            out = []
            for i in order:
                cid = vec_ids[i]
                if exclude_doc and by_id[cid]["docid"] == exclude_doc:
                    continue
                out.append((cid, float(sims[i])))
                if len(out) >= k:
                    break
            return out

        for s, qv in zip(samples, qe):
            gid = s["qid"]
            retrieval_top[gid] = {
                "noise": topk(qv, NOISE_POOL, exclude_doc=gid),
                "rag": topk(qv, RAG_TOP_K),
            }
        print("retrieval vectors ready")

    for t in tasks:
        if t["mode"] == "oracle_noise" and t["variant"] != "noise0":
            noise = [cid for cid, _ in retrieval_top[t["qid"]]["noise"]]
            k = int(t["variant"][len("noise"):])
            t["ctx_ids"] = [t["ctx_ids"][0]] + noise[:k]
        if t["mode"] == "rag":
            t["ctx_ids"] = [cid for cid, _ in retrieval_top[t["qid"]]["rag"]]
    if args.mode != "all":
        tasks = [t for t in tasks if t["mode"] == args.mode]
    print(f"tasks: {len(tasks)}  (qids={len(samples)})")

    # ---------- tokenizer + 引擎 ----------
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)

    import torch
    device = "cuda" if (torch.cuda.is_available() and not args.cpu) else "cpu"
    engine = args.engine
    if engine == "auto":
        engine = "vllm" if (device == "cuda" and _has_vllm()) else "transformers"
    print(f"engine={engine} device={device} model={args.model}")

    generator = _make_generator(engine, args.model, device)

    # ---------- checkpoint ----------
    RESULT_DIR.mkdir(exist_ok=True)
    out_path = RESULT_DIR / "cmrc_gen.jsonl"
    done: set[str] = set()
    if args.resume and out_path.exists():
        for l in out_path.read_text(encoding="utf-8").split("\n"):
            if l.strip():
                done.add(json.loads(l)["key"])
        print(f"resume: {len(done)} done already")

    pending = [t for t in tasks if f"{t['mode']}|{t['qid']}|{t['variant']}" not in done]
    print(f"pending: {len(pending)}")

    # ---------- prompt 构造 ----------
    def build_prompt(task):
        texts = [by_id[cid]["text"] for cid in task["ctx_ids"] if cid in by_id]
        total = sum(len(x) for x in texts)
        truncated = total > args.max_ctx_chars
        if truncated:
            kept, acc = [], 0
            for x in texts:
                if acc + len(x) > args.max_ctx_chars:
                    break
                kept.append(x)
                acc += len(x)
            texts = kept
        user = "文档:\n" + "\n".join(texts) + "\n\n问题:" + \
            _q_of(task["qid"])
        msg = tokenizer.apply_chat_template(
            [{"role": "system", "content": SYSTEM_MSG},
             {"role": "user", "content": user}],
            tokenize=False, add_generation_prompt=True)
        return msg, truncated, sum(len(x) for x in texts)

    def _q_of(qid):
        for s in samples:
            if s["qid"] == qid:
                return s["question"]
        return ""

    t0 = time.time()
    out_f = open(out_path, "a" if args.resume and out_path.exists() else "w",
                 encoding="utf-8")
    done_n = 0
    if engine == "vllm":
        from vllm import SamplingParams
        sp = SamplingParams(temperature=0.0, max_tokens=MAX_NEW_TOKENS)
        for i in range(0, len(pending), BATCH_VLLM):
            chunk = pending[i:i + BATCH_VLLM]
            prompts = []
            for task in chunk:
                p, trunc, chars = build_prompt(task)
                task["_trunc"] = trunc
                task["_chars"] = chars
                prompts.append(p)
            outputs = generator.generate(prompts, sp)
            for task, out in zip(chunk, outputs):
                rec = _record(task, out.outputs[0].text)
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out_f.flush()
                done_n += 1
            if done_n % 200 == 0:
                print(f"  {done_n}/{len(pending)}  ({time.time() - t0:.0f}s)")
    else:
        model, tok = generator
        for i, task in enumerate(pending):
            p, trunc, chars = build_prompt(task)
            task["_trunc"] = trunc
            task["_chars"] = chars
            inp = tok(p, return_tensors="pt").to(device)
            out = model.generate(**inp, max_new_tokens=MAX_NEW_TOKENS,
                                 do_sample=False)
            text = tok.decode(out[0][inp["input_ids"].shape[1]:],
                              skip_special_tokens=True)
            rec = _record(task, text)
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            done_n += 1
            if i % 10 == 0:
                print(f"  {i}/{len(pending)}  ({time.time() - t0:.0f}s)")
    out_f.close()
    print(f"done {done_n}/{len(pending)} → {out_path}  ({time.time() - t0:.0f}s)")


def _has_vllm():
    try:
        import vllm  # noqa: F401
        return True
    except Exception:
        return False


def _make_generator(engine, model_name, device):
    if engine == "vllm":
        from vllm import LLM
        print("loading vLLM ...")
        return LLM(model=model_name, dtype="auto", max_model_len=16384,
                   gpu_memory_utilization=0.92, trust_remote_code=True)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    print("loading transformers ...")
    dtype = torch.float16 if device == "cuda" else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        model_name, trust_remote_code=True, torch_dtype=dtype).to(device).eval()
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    return model, tokenizer


def _record(task, text):
    gold = _GOLD.get(task["qid"])
    return {
        "key": f"{task['mode']}|{task['qid']}|{task['variant']}",
        "mode": task["mode"], "qid": task["qid"], "variant": task["variant"],
        "doc_n": task.get("doc_n", 0),
        "ctx_chunk_ids": task["ctx_ids"],
        "ctx_chars": task.get("_chars", 0),
        "truncated": task.get("_trunc", False),
        "hit_gold": (gold is not None and gold in set(task["ctx_ids"])),
        "generated": text.strip(),
    }


_GOLD: dict[str, str] = {}


if __name__ == "__main__":
    _GOLD = {s["qid"]: s["gold_chunk"]
             for s in read_jsonl(DATA_DIR / "sample.jsonl")}
    main()
