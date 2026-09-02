# -*- coding: utf-8 -*-
"""项目数据层：负责项目文件(.aiwriter.json)的读写、图片资源管理与导入导出。

设计目标：
1. 单文件存储，方便手动备份 / 版本管理；
2. 图片等二进制资源放在同目录的 images/ 下，JSON 内只存相对路径；
3. 所有写操作先写临时文件再原子替换，避免断电/崩溃导致项目损坏。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from typing import Any, Dict, List, Optional

APP_NAME = "AIWriter"
PROJECT_EXT = ".aiwriter.json"
IMAGE_DIR_NAME = "images"

# 图片扩展名白名单（tkinter 原生 PhotoImage 只吃 png/gif，装了 Pillow 则通吃）
IMAGE_EXT_WHITE = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ppm", ".pgm"}


def new_id(prefix: str = "") -> str:
    return (prefix + "_" if prefix else "") + uuid.uuid4().hex[:12]


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def safe_filename(name: str, default: str = "untitled") -> str:
    """把任意字符串洗成可安全用于文件名的形式（保留中日韩字符）。"""
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    name = name.strip().strip(".")
    return name[:80] or default


# ---------------------------------------------------------------------------
# 默认数据结构
# ---------------------------------------------------------------------------

DEFAULT_API = {
    "provider": "openai",                # openai(兼容) / anthropic / custom
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o-mini",
    "temperature": 0.9,
    "top_p": 1.0,
    "max_tokens": 4096,
    "timeout": 180,
    "extra_headers": "",                 # 每行一个：Key: Value
    "extra_body": "",                    # 额外 JSON 字段，合并进请求体
    "system_override": "",               # 非空时完全替换默认 system 提示
}

DEFAULT_WORLD = {
    "title": "未命名世界观",
    "worldview": "",      # 世界观设定
    "outline": "",        # 故事大纲 / 剧情线
    "style": "",          # 文风要求
    "banned": "",         # 禁用词 / 雷点
    "instructions": "",   # 全局写作指令
    "snippets": [],       # 常用指令片段：[{id, name, text}]
}

DEFAULT_GEN = {
    "tail_chars": 3000,        # 携带正文尾部字数
    "lore_topk": 6,            # 资料库自动召回条数
    "lore_min_score": 0.6,     # 召回最低相关度（0~1，相对最高分）
    "use_world": True,
    "use_outline": True,
    "use_style": True,
    "use_banned": True,
    "use_instructions": True,
    "use_characters": True,
    "use_lore": True,
    "preset": "continue",      # 当前生成模式
}

PROMPT_PRESETS = {
    "continue": {
        "name": "续写正文",
        "task": "请接着【已有正文】的结尾继续写作，保持人称、时态、文风与节奏完全一致，"
                "自然衔接最后一句，只输出新增的小说正文，不要复述已有内容，不要写任何解释、注释或标题。",
        "length": "本次续写 800~1500 字左右，写到一个有张力的小段落结束。",
    },
    "rewrite": {
        "name": "重写选中",
        "task": "请重写【待处理文本】这一段，保持原意与剧情走向不变，但可以优化句式、节奏与描写，"
                "只输出重写后的正文。",
        "length": "篇幅与原文相当。",
    },
    "expand": {
        "name": "扩写选中",
        "task": "请将【待处理文本】扩写得更丰满：补充环境、感官与人物心理细节，增强画面感与情绪张力，"
                "只输出扩写后的正文。",
        "length": "扩写为原文的 2~3 倍长度。",
    },
    "polish": {
        "name": "润色选中",
        "task": "请对【待处理文本】做文字润色：修正错字病句、改善冗余表达、让语句更流畅有韵律，"
                "但不改变情节、人设与文风，只输出润色后的正文。",
        "length": "篇幅与原文相当。",
    },
    "chat": {
        "name": "自由问答",
        "task": "请基于【世界观 / 人物卡 / 资料库 / 已有正文】回答用户的问题，或完成用户提出的写作任务，"
                "用中文作答。",
        "length": "",
    },
}


def _default_character(name: str = "新角色") -> Dict[str, Any]:
    return {
        "id": new_id("char"),
        "name": name,
        "aliases": "",
        "gender": "",
        "age": "",
        "appearance": "",
        "personality": "",
        "background": "",
        "speech": "",          # 口癖 / 语言风格
        "relations": "",       # 人际关系
        "notes": "",           # 补充备注（作者自己看的，也会喂给 AI）
        "sample": "",          # 示例对话 / 范例片段
        "images": [],          # [{"path": "images/xxx.png", "caption": "说明"}]
        "enabled": True,       # 是否允许被 AI 参考
        "updated": now_str(),
    }


def _default_lore(title: str = "新资料") -> Dict[str, Any]:
    return {
        "id": new_id("lore"),
        "title": title,
        "tags": "",
        "content": "",
        "enabled": True,
        "pinned": False,     # 常驻：不管关键词是否命中，每次生成都带上
        "updated": now_str(),
    }


def _default_article(title: str = "新章节") -> Dict[str, Any]:
    return {
        "id": new_id("art"),
        "title": title,
        "summary": "",     # 本章梗概，会作为上下文喂给 AI
        "content": "",
        "updated": now_str(),
    }


def default_project(name: str = "我的小说") -> Dict[str, Any]:
    return {
        "format": 1,
        "meta": {"name": name, "created": now_str(), "updated": now_str()},
        "api": dict(DEFAULT_API),
        "world": dict(DEFAULT_WORLD),
        "gen": dict(DEFAULT_GEN),
        "characters": [],
        "lore": [],
        "articles": [_default_article("第一章")],
    }


# ---------------------------------------------------------------------------
# 项目存取
# ---------------------------------------------------------------------------

class Project:
    """一个小说项目的内存模型 + 持久化。"""

    def __init__(self, path: Optional[str] = None, data: Optional[Dict[str, Any]] = None):
        self.path = path
        self.data: Dict[str, Any] = data or default_project()
        self.dirty = False
        self._migrate()

    # -- 基础 ------------------------------------------------------------
    @property
    def name(self) -> str:
        return self.data.get("meta", {}).get("name", "未命名项目")

    @name.setter
    def name(self, value: str) -> None:
        self.data.setdefault("meta", {})["name"] = value
        self.dirty = True

    @property
    def image_dir(self) -> str:
        base = os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()
        return os.path.join(base, IMAGE_DIR_NAME)

    def _migrate(self) -> None:
        """补齐旧版本/受损项目缺失的字段，保证 UI 永远拿得到键。"""
        d = self.data
        d.setdefault("format", 1)
        meta = d.setdefault("meta", {})
        if not isinstance(meta, dict):
            meta = {}
            d["meta"] = meta
        meta["name"] = meta.get("name") or "未命名项目"
        meta.setdefault("created", now_str())
        meta.setdefault("updated", now_str())
        for key, default in (("api", DEFAULT_API), ("world", DEFAULT_WORLD), ("gen", DEFAULT_GEN)):
            cur = d.setdefault(key, {})
            if not isinstance(cur, dict):
                cur = {}
                d[key] = cur
            for k, v in default.items():
                cur.setdefault(k, v)
        for key in ("characters", "lore", "articles"):
            if not isinstance(d.get(key), list):
                d[key] = []
        # 条目内部字段兜底
        for c in d["characters"]:
            for k, v in _default_character().items():
                c.setdefault(k, v)
            c["images"] = [i for i in c.get("images", []) if isinstance(i, dict)]
        for l in d["lore"]:
            for k, v in _default_lore().items():
                l.setdefault(k, v)
        for a in d["articles"]:
            for k, v in _default_article().items():
                a.setdefault(k, v)
        if not d["articles"]:
            d["articles"].append(_default_article("第一章"))
        # 数值字段类型纠偏（手改 JSON 容易写错）
        g = d["gen"]
        for k in ("tail_chars", "lore_topk"):
            try:
                g[k] = int(g[k])
            except (TypeError, ValueError):
                g[k] = DEFAULT_GEN[k]
        try:
            g["lore_min_score"] = float(g["lore_min_score"])
        except (TypeError, ValueError):
            g["lore_min_score"] = DEFAULT_GEN["lore_min_score"]
        for k in ("temperature", "top_p"):
            try:
                d["api"][k] = float(d["api"][k])
            except (TypeError, ValueError):
                d["api"][k] = DEFAULT_API[k]
        for k in ("max_tokens", "timeout"):
            try:
                d["api"][k] = int(d["api"][k])
            except (TypeError, ValueError):
                d["api"][k] = DEFAULT_API[k]

    # -- 加载 / 保存 ------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(path=path, data=data)

    def save(self, path: Optional[str] = None) -> str:
        if path:
            self.path = path
        if not self.path:
            raise ValueError("尚未指定项目保存路径")
        self.data.setdefault("meta", {})["updated"] = now_str()
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=".aiwriter-", suffix=".tmp",
                                            dir=os.path.dirname(os.path.abspath(self.path)) or ".")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)  # 原子替换，避免写一半损坏
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
        self.dirty = False
        return self.path

    def touch(self) -> None:
        self.dirty = True

    # -- 图片资源 ---------------------------------------------------------
    def add_image(self, src_path: str) -> Optional[str]:
        """把外部图片复制进项目 images/ 目录，返回相对路径（失败返回 None）。"""
        ext = os.path.splitext(src_path)[1].lower()
        if ext not in IMAGE_EXT_WHITE:
            return None
        os.makedirs(self.image_dir, exist_ok=True)
        rel = os.path.join(IMAGE_DIR_NAME,
                           "%s%s" % (uuid.uuid4().hex[:12], ext))
        dst = os.path.join(os.path.dirname(os.path.abspath(self.path or ".")), rel)
        shutil.copy2(src_path, dst)
        return rel.replace("\\", "/")

    def abs_image(self, rel_path: str) -> str:
        base = os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()
        return os.path.join(base, rel_path or "")

    # -- 人物卡 -----------------------------------------------------------
    def add_character(self, name: str = "新角色") -> Dict[str, Any]:
        ch = _default_character(name)
        self.data["characters"].append(ch)
        self.dirty = True
        return ch

    def remove_character(self, char_id: str) -> None:
        self.data["characters"] = [c for c in self.data["characters"] if c["id"] != char_id]
        self.dirty = True

    def get_character(self, char_id: str) -> Optional[Dict[str, Any]]:
        for c in self.data["characters"]:
            if c["id"] == char_id:
                return c
        return None

    # -- 资料库 -----------------------------------------------------------
    def get_lore(self, lore_id: str) -> Optional[Dict[str, Any]]:
        """按 id 取一条资料（与 get_character / get_article 配套）。"""
        if not lore_id:
            return None
        for l in self.data["lore"]:
            if l["id"] == lore_id:
                return l
        return None

    def add_lore(self, title: str = "新资料") -> Dict[str, Any]:
        lo = _default_lore(title)
        self.data["lore"].append(lo)
        self.dirty = True
        return lo

    def remove_lore(self, lore_id: str) -> None:
        self.data["lore"] = [l for l in self.data["lore"] if l["id"] != lore_id]
        self.dirty = True

    # -- 文章 -------------------------------------------------------------
    def add_article(self, title: str = "新章节") -> Dict[str, Any]:
        art = _default_article(title)
        self.data["articles"].append(art)
        self.dirty = True
        return art

    def remove_article(self, art_id: str) -> None:
        self.data["articles"] = [a for a in self.data["articles"] if a["id"] != art_id]
        if not self.data["articles"]:
            self.data["articles"].append(_default_article("第一章"))
        self.dirty = True

    def get_article(self, art_id: str) -> Optional[Dict[str, Any]]:
        for a in self.data["articles"]:
            if a["id"] == art_id:
                return a
        return None

    @property
    def total_words(self) -> int:
        return sum(len(a.get("content", "")) for a in self.data["articles"])

    # -- 导入导出 ---------------------------------------------------------
    def export_bundle(self, zip_path: str) -> str:
        """把项目 JSON + 图片资源打包成一个 zip，方便换机器 / 备份。"""
        base = os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            if self.path and os.path.exists(self.path):
                z.write(self.path, os.path.basename(self.path))
            img_dir = self.image_dir
            if os.path.isdir(img_dir):
                for root, _dirs, files in os.walk(img_dir):
                    for fn in files:
                        full = os.path.join(root, fn)
                        z.write(full, os.path.relpath(full, base))
        return zip_path

    @classmethod
    def import_bundle(cls, zip_path: str, target_dir: str) -> "Project":
        """从 zip 包恢复项目（含图片）。"""
        os.makedirs(target_dir, exist_ok=True)
        json_path = None
        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            for n in names:
                if n.endswith(PROJECT_EXT):
                    json_path = os.path.join(target_dir, os.path.basename(n))
                    break
            if json_path is None:
                raise ValueError("压缩包里没有找到 %s 项目文件" % PROJECT_EXT)
            z.extractall(target_dir)
        return cls.load(json_path)


def export_article_text(article: Dict[str, Any], path: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(article.get("title", "").strip() + "\n\n")
        f.write(article.get("content", ""))
    return path


def export_all_text(project: "Project", path: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        for i, a in enumerate(project.data["articles"]):
            f.write("\n\n" + "=" * 20 + " %s " % a.get("title", "") + "=" * 20 + "\n\n")
            f.write(a.get("content", ""))
    return path


def find_projects(root_dir: str) -> List[str]:
    """扫描目录下所有项目文件，用于"最近项目"列表。"""
    out = []
    for fn in sorted(os.listdir(root_dir)):
        if fn.endswith(PROJECT_EXT):
            out.append(os.path.join(root_dir, fn))
    return out


def count_words(text: str) -> int:
    """中英文混排字数统计：中日韩逐字计，英文按单词计。"""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    words = len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text))
    return cjk + words
