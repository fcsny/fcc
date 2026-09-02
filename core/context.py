# -*- coding: utf-8 -*-
"""上下文组装：把 世界观 / 指令 / 人物卡 / 资料库 / 正文尾部 拼成一次请求。

这是整个软件的核心——拼得好不好，直接决定 AI 写得像不像你的小说。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .retriever import retrieve
from .storage import PROMPT_PRESETS, count_words


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """粗估 token 数：中文约 1 字 ≈ 0.7 token，英文约 4 字符 ≈ 1 token。"""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    rest = len(text) - cjk
    return int(cjk * 0.75 + max(rest, 0) / 3.6) + 8


def clean(text: str) -> str:
    return (text or "").replace("\r\n", "\n").strip()


def tail_text(content: str, n_chars: int) -> str:
    """取正文尾部 n 字，尽量从段落边界切开，避免半句话。"""
    content = content or ""
    if n_chars <= 0 or len(content) <= n_chars:
        return content
    cut = content[-n_chars:]
    idx = cut.find("\n")
    if 0 <= idx < 200:      # 只在丢掉很少内容时对齐到段落
        cut = cut[idx + 1:]
    return "…（前文已省略）\n" + cut


# ---------------------------------------------------------------------------
# 人物卡渲染
# ---------------------------------------------------------------------------

CHAR_FIELDS = [
    ("name", "姓名", True),
    ("aliases", "别名 / 称呼", False),
    ("gender", "性别", False),
    ("age", "年龄", False),
    ("appearance", "外貌特征", False),
    ("personality", "性格", False),
    ("speech", "语言风格 / 口癖", False),
    ("background", "背景经历", False),
    ("relations", "人际关系", False),
    ("notes", "作者备注", False),
    ("sample", "示例对话 / 范例", False),
]


def render_character(ch: Dict[str, Any]) -> str:
    lines = []
    for key, label, _req in CHAR_FIELDS:
        val = clean(ch.get(key, ""))
        if val:
            lines.append("- %s：%s" % (label, val.replace("\n", " / " if len(val) < 120 else "\n  ")))
    images = ch.get("images") or []
    if images:
        caps = [i.get("caption", "").strip() for i in images if i.get("caption", "").strip()]
        if caps:
            lines.append("- 立绘 / 参考图说明：%s" % "；".join(caps))
    if not lines:
        return ""
    title = clean(ch.get("name")) or "未命名角色"
    return "【%s】\n" % title + "\n".join(lines)


def render_characters(chars: Sequence[Dict[str, Any]]) -> str:
    blocks = [render_character(c) for c in chars]
    blocks = [b for b in blocks if b]
    return "\n\n".join(blocks)


def render_lore(hits: Sequence[Tuple[float, Dict[str, Any]]]) -> str:
    out = []
    for _score, item in hits:
        title = clean(item.get("title")) or "未命名资料"
        tags = clean(item.get("tags"))
        body = clean(item.get("content"))
        head = "【%s】" % title + ("（标签：%s）" % tags if tags else "")
        out.append(head + ("\n" + body if body else ""))
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# System 提示
# ---------------------------------------------------------------------------

def _render_one(item: Dict[str, Any]) -> str:
    title = clean(item.get("title")) or "未命名资料"
    tags = clean(item.get("tags"))
    body = clean(item.get("content"))
    head = "【%s】" % title + ("（标签：%s）" % tags if tags else "")
    return head + ("\n" + body if body else "")


def build_system(project) -> str:
    cfg = project.data["api"]
    override = clean(cfg.get("system_override", ""))
    if override:
        return override
    world = project.data["world"]
    parts = [
        "你是一位专业的小说作家，正在与一位人类作者协作创作。",
        "你必须严格遵守已给出的世界观、人物设定与写作指令，绝不能擅自偏离设定、"
        "不能替作者做宏观剧情决断，也不要跳到时间线很远的地方。",
        "输出正文时：使用简体中文、全角标点；只输出正文内容本身，"
        "不要输出任何解释、说明、备注、Markdown 标题或「以下是续写」这类客套话。",
    ]
    banned = clean(world.get("banned", ""))
    if banned and project.data["gen"].get("use_banned", True):
        parts.append("【绝对禁止】以下内容一旦出现即视为失败：%s" % banned.replace("\n", "、"))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 主构建
# ---------------------------------------------------------------------------

class BuildResult:
    def __init__(self, system: str, messages: List[Dict[str, str]],
                 lore_hits: List[Tuple[float, Dict[str, Any]]],
                 meta: Dict[str, Any]):
        self.system = system
        self.messages = messages
        self.lore_hits = lore_hits
        self.meta = meta

    @property
    def prompt_text(self) -> str:
        return "\n\n".join(m["content"] for m in self.messages)

    @property
    def token_estimate(self) -> int:
        return estimate_tokens(self.system) + sum(estimate_tokens(m["content"]) for m in self.messages)


def build_context(project,
                  article: Optional[Dict[str, Any]],
                  instruction: str,
                  preset_key: str,
                  selected_text: str = "",
                  char_ids: Optional[Sequence[str]] = None,
                  history: Optional[List[Dict[str, str]]] = None,
                  lore_override: Optional[List[Dict[str, Any]]] = None,
                  ) -> BuildResult:
    """组装一次生成请求所需的全部内容。"""
    gen = project.data["gen"]
    world = project.data["world"]
    preset = PROMPT_PRESETS.get(preset_key, PROMPT_PRESETS["continue"])

    blocks: List[str] = []

    # 1) 世界观 / 大纲 / 文风 / 指令
    world_parts = []
    if gen.get("use_world", True) and clean(world.get("worldview")):
        world_parts.append("## 世界观设定\n" + clean(world["worldview"]))
    if gen.get("use_outline", True) and clean(world.get("outline")):
        world_parts.append("## 故事大纲 / 剧情线\n" + clean(world["outline"]))
    if world_parts:
        blocks.append("\n\n".join(world_parts))

    if gen.get("use_style", True) and clean(world.get("style")):
        blocks.append("## 文风要求\n" + clean(world["style"]))
    if gen.get("use_instructions", True) and clean(world.get("instructions")):
        blocks.append("## 写作指令（必须遵守）\n" + clean(world["instructions"]))

    # 2) 人物卡
    chars_used: List[Dict[str, Any]] = []
    if gen.get("use_characters", True):
        if char_ids is None:
            chars_used = [c for c in project.data["characters"] if c.get("enabled", True)]
        else:
            idset = set(char_ids)
            chars_used = [c for c in project.data["characters"]
                          if c["id"] in idset and c.get("enabled", True)]
    if chars_used:
        blocks.append("## 相关人物设定\n" + render_characters(chars_used))

    # 3) 资料库（按相关度自动召回）
    lore_hits: List[Tuple[float, Dict[str, Any]]] = []
    lore_used: List[Dict[str, Any]] = []
    pinned: List[Dict[str, Any]] = []
    if gen.get("use_lore", True):
        pool_all = lore_override if lore_override is not None else \
            [l for l in project.data["lore"] if l.get("enabled", True)]
        # 常驻资料：核心设定不靠关键词碰运气，每次都带上
        pinned = [l for l in pool_all if l.get("pinned")]
        pinned_ids = {l["id"] for l in pinned}
        pool = [l for l in pool_all if l["id"] not in pinned_ids]
        query_parts = [
            instruction or "",
            selected_text or "",
            (article or {}).get("summary", ""),
            " ".join(c.get("name", "") for c in chars_used),
            tail_text((article or {}).get("content", ""), 800),
        ]
        query = "\n".join(p for p in query_parts if p)
        lore_hits = retrieve(query, pool,
                             topk=int(gen.get("lore_topk", 6)),
                             min_ratio=float(gen.get("lore_min_score", 0.0)))
        lore_used = pinned + [item for _s, item in lore_hits]
    if lore_used:
        head = "## 参考资料（与本次内容相关的设定，仅在相关时采用）"
        rendered = []
        if pinned:
            rendered.append("### 常驻设定（务必遵守）\n" +
                            "\n\n".join(_render_one(l) for l in pinned))
        if lore_hits:
            rendered.append("### 相关设定\n" + render_lore(lore_hits))
        blocks.append(head + "\n" + "\n\n".join(rendered))

    # 4) 当前章节
    if article is not None:
        head = ["## 当前章节：%s" % (clean(article.get("title")) or "无标题")]
        if clean(article.get("summary")):
            head.append("本章梗概：%s" % clean(article["summary"]))
        blocks.append("\n".join(head))

    # 5) 已有正文尾部
    if article is not None:
        tail = tail_text(article.get("content", ""), int(gen.get("tail_chars", 3000)))
        if clean(tail):
            blocks.append("## 已有正文（结尾部分）\n" + clean(tail))

    # 6) 待处理文本
    if selected_text and preset_key in ("rewrite", "expand", "polish"):
        blocks.append("## 待处理文本\n" + clean(selected_text))

    # 7) 任务
    task_lines = ["## 本次任务\n" + preset["task"]]
    if preset["length"]:
        task_lines.append(preset["length"])
    if instruction and clean(instruction):
        task_lines.append("作者的额外要求：%s" % clean(instruction))
    blocks.append("\n".join(task_lines))

    body = "\n\n".join(b for b in blocks if b)

    messages: List[Dict[str, str]] = []
    for h in (history or []):
        if clean(h.get("content", "")):
            messages.append({"role": h.get("role", "user"), "content": clean(h["content"])})
    messages.append({"role": "user", "content": body})

    meta = {
        "preset": preset.get("name", preset_key),
        "characters": [c.get("name", "") for c in chars_used],
        "lore": [l.get("title", "") for l in lore_used],
        "lore_pinned": [l.get("title", "") for l in pinned],
        "tail_chars": int(gen.get("tail_chars", 3000)),
        "article": (article or {}).get("title", ""),
    }
    return BuildResult(build_system(project), messages, lore_hits, meta)


def context_summary(result: BuildResult) -> str:
    """生成面板底部那一行"这次到底喂了什么"的摘要。"""
    m = result.meta
    bits = ["模式：%s" % m["preset"]]
    bits.append("人物：%s" % ("、".join(m["characters"]) if m["characters"] else "无"))
    bits.append("资料：%s" % ("、".join(m["lore"]) if m["lore"] else "无"))
    bits.append("正文尾部：%d 字" % m["tail_chars"])
    bits.append("约 %d tokens" % result.token_estimate)
    return " | ".join(bits)
