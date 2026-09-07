# -*- coding: utf-8 -*-
"""语料入库:本地 CSDN 稿 → corpus/ 规范化 md + corpus.jsonl 元数据。

清洗规则(对应 JD "文档解析、数据清洗" 职责,文章里有一句交代):
- 剥系列导航行(> 本文是「...」第 N 篇 ...)
- 剥状态/修订注记行(状态:CSDN 投稿稿 / 修订记录 / 发布时删除)
- 其余内容原样保留(代码块/表格不动)

用法: python src/ingest.py
新增语料:在 MANIFEST 里加一行 (slug, domain, 源文件路径)。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"

# slug -> (domain, 源文件)。domain: ai = 2026 AI 实测线, java = 2022 Java 老文(待用户站内导出)
MANIFEST = [
    ("dsh-startup",  "ai", "AI情报收集/深度实测/DSH系列/DSH-上手实录-CSDN稿-v2.md"),
    ("dsh-plugin",   "ai", "AI情报收集/深度实测/DSH系列/插件开发实录/DSH插件开发实录-CSDN稿.md"),
    ("dsh-market",   "ai", "AI情报收集/深度实测/DSH系列/DSH插件市场实测-CSDN稿.md"),
    ("dsh-197pkg",   "ai", "AI情报收集/深度实测/DSH系列/DSH-197包架构清单-核验版.md"),
    ("arc-harness",  "ai", "AI情报收集/深度实测/ARC-AGI3-harness实验/ARC-AGI3-harness实测-CSDN稿.md"),
    ("dsewiki",      "ai", "AI情报收集/深度实测/DseWiki逃逸agents/DseWiki逃逸agents数据实拉-CSDN稿-v5.md"),
    ("skillspector", "ai", "AI情报收集/深度实测/SkillSpector-skills注入实测/SkillSpector-skills注入实测-CSDN稿.md"),
    ("glm53",        "ai", "AI情报收集/深度实测/GLM-5.3实测/GLM5.3-vs-GLM5.2-同题实测报告v2.md"),
    ("hy4-glm",      "ai", "AI情报收集/深度实测/Hy4-vs-GLM5.3实测/Hy4-vs-GLM5.3-实测报告.md"),
    # java 域:站内导出后在此追加,如 ("spring-tx", "java", "AI情报收集/深度实测/RAG语料-java老文/spring事务.md")
]

# 待剥离的行级模式(锚定行首)
STRIP_PATTERNS = [
    re.compile(r"^>\s*本文是「.*」第\s*\d+\s*篇.*$"),          # 系列导航行
    re.compile(r"^>\s*状态[:：].*$"),                          # 状态注记行
    re.compile(r"^状态[:：].*$"),
    re.compile(r"^>\s*\(发布时删除.*$"),
    re.compile(r"^#{1,6}\s*(修订记录|修订历史|版本记录).*$"),   # 修订记录标题
    re.compile(r"^本文是.*第\s*\d+\s*篇.*$"),
    re.compile(r"^>.*(发布时删除|选自).*$"),                    # 引注/选自行(变体)
]

TITLE_RE = re.compile(r"^#\s+(.+)$")


def clean(text: str) -> tuple[str, str]:
    """返回 (清洗后正文, 文章标题)。"""
    title = ""
    kept = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            kept.append(line)
            continue
        if not in_code:
            if not title:
                m = TITLE_RE.match(line)
                if m:
                    title = m.group(1).strip()
            if any(p.match(line.strip()) for p in STRIP_PATTERNS):
                continue
        kept.append(line)
    return "\n".join(kept).strip() + "\n", title


def main():
    CORPUS_DIR.mkdir(exist_ok=True)
    meta = []
    for slug, domain, rel in MANIFEST:
        src = ROOT.parent / rel
        if not src.exists():
            print(f"[miss] {slug}: {src}")
            continue
        text, title = clean(src.read_text(encoding="utf-8"))
        out = CORPUS_DIR / f"{slug}.md"
        out.write_text(text, encoding="utf-8")
        meta.append({"id": slug, "domain": domain, "title": title or slug,
                      "chars": len(text), "source": rel})
        print(f"[ok] {slug:14s} {len(text):>7d} chars  {title[:40]}")
    with open(CORPUS_DIR / "corpus.jsonl", "w", encoding="utf-8") as f:
        for m in meta:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    total = sum(m["chars"] for m in meta)
    print(f"\n{len(meta)} articles, {total} chars total")


if __name__ == "__main__":
    main()
