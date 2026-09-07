# -*- coding: utf-8 -*-
"""三种分块策略:fixed / recursive / structure。

- fixed: 固定字符窗口 + overlap 滑窗(基线)
- recursive: LangChain RecursiveCharacterTextSplitter,中文分隔符
             (框架组件作为被测对象——不是教程,是对照组)
- structure: 自建 Markdown 结构感知(标题分节,代码块原子不可切,
             超长节按段落→句子回退)

所有策略统一返回 [{article_id, chunk_id, text}]。
"""
from langchain_text_splitters import RecursiveCharacterTextSplitter

OVERLAP = 50  # 全系列固定,单变量原则

CHINESE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", ""]


def chunk_fixed(article_id: str, text: str, size: int) -> list[dict]:
    """固定字符窗口 + overlap 滑窗。"""
    step = max(1, size - OVERLAP)
    chunks = []
    for i, start in enumerate(range(0, max(1, len(text)), step)):
        piece = text[start:start + size]
        if not piece.strip():
            break
        chunks.append({"article_id": article_id, "chunk_id": f"{article_id}#f{i}",
                       "text": piece})
        if start + size >= len(text):
            break
    return chunks


def chunk_recursive(article_id: str, text: str, size: int) -> list[dict]:
    """LangChain 递归字符切分(中文分隔符),框架默认行为的对照组。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size, chunk_overlap=OVERLAP, separators=CHINESE_SEPARATORS,
        keep_separator=True, strip_whitespace=False)
    chunks = []
    for i, piece in enumerate(splitter.split_text(text)):
        chunks.append({"article_id": article_id, "chunk_id": f"{article_id}#r{i}",
                       "text": piece})
    return chunks


def _split_paragraphs(section: str, size: int) -> list[str]:
    """超长节内回退切分:段落(空行)→句子(。!?;)。代码行/表格行不主动切断。"""
    if len(section) <= size:
        return [section]
    paras = section.split("\n\n")
    out, buf = [], ""
    for p in paras:
        # 单段仍超长:按句子切
        if len(p) > size:
            sents, sbuf = [], ""
            for ch_i, ch in enumerate(p):
                sbuf += ch
                if ch in "。！？；" and len(sbuf) >= max(32, size // 4):
                    sents.append(sbuf)
                    sbuf = ""
            if sbuf:
                sents.append(sbuf)
            paras_inner = sents
            for s in paras_inner:
                if len(buf) + len(s) + 2 <= size:
                    buf = (buf + "\n\n" + s) if buf else s
                else:
                    if buf:
                        out.append(buf)
                    buf = s
            continue
        if len(buf) + len(p) + 2 <= size:
            buf = (buf + "\n\n" + p) if buf else p
        else:
            if buf:
                out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out


def chunk_structure(article_id: str, text: str, size: int) -> list[dict]:
    """Markdown 结构感知:按标题分节;代码块/表格行视为原子行,不内部切断。

    实现口径:以行为单位组装,行不腰斩(代码块因此天然原子),
    溢出 size 的行序列按段落/句子回退(见 _split_paragraphs)。
    """
    lines = text.split("\n")
    sections, cur = [], []          # sections: [(heading, [lines])]
    heading = "#"
    for line in lines:
        if line.strip().startswith("#"):
            if cur:
                sections.append((heading, cur))
            heading, cur = line.strip(), []
        else:
            cur.append(line)
    if cur:
        sections.append((heading, cur))

    chunks = []
    for heading, sec_lines in sections:
        sec_text = (heading + "\n" if heading else "") + "\n".join(sec_lines)
        for piece in _split_paragraphs(sec_text, size):
            if piece.strip():
                chunks.append(piece)

    merged = []
    for piece in chunks:
        if merged and len(merged[-1]) + len(piece) + 1 <= size:
            merged[-1] += "\n" + piece   # 小节合并,逼近 size 上限
        else:
            merged.append(piece)
    return [{"article_id": article_id, "chunk_id": f"{article_id}#s{i}",
             "text": p} for i, p in enumerate(merged)]


CHUNKERS = {"fixed": chunk_fixed, "recursive": chunk_recursive,
            "structure": chunk_structure}


def chunk_article(article_id: str, text: str, strategy: str, size: int) -> list[dict]:
    return CHUNKERS[strategy](article_id, text, size)


def count_codeblock_cuts(chunks: list[dict]) -> int:
    """代码块被切断次数:块内 ``` 围栏数为奇 → 有代码块被腰斩。"""
    cuts = 0
    for c in chunks:
        if c["text"].count("```") % 2 == 1:
            cuts += 1
    return cuts
