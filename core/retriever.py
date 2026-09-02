# -*- coding: utf-8 -*-
"""资料库检索：轻量 BM25，无第三方依赖。

为什么不是向量库：自娱自乐的小说资料库通常只有几十到几百条，
BM25 这种关键词算法零依赖、零启动成本、结果可控可解释，
而且对"专有名词 / 设定词条"这类写作场景的命中率反而比小向量模型更稳。
"""
from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Sequence, Tuple

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[\u4e00-\u9fff]")


def tokenize(text: str) -> List[str]:
    """中文按 2-gram 切（"魔法学院" -> 魔法/法学/学院），英数按词切。

    2-gram 对中文是性价比最高的朴素方案：不需要词典，也能命中部分重叠的词。
    """
    if not text:
        return []
    raw = [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]
    out: List[str] = []
    for tok in raw:
        if "\u4e00" <= tok <= "\u9fff":
            out.append(tok)
        else:
            out.append(tok)
    # 中文部分再做 bigram
    grams: List[str] = []
    run: List[str] = []
    for tok in out:
        if "\u4e00" <= tok[0] <= "\u9fff":
            run.append(tok)
        else:
            grams.extend(_bigrams(run))
            run = []
            grams.append(tok)
    grams.extend(_bigrams(run))
    return grams


def _bigrams(run: Sequence[str]) -> List[str]:
    if not run:
        return []
    if len(run) == 1:
        return [run[0]]
    return [run[i] + run[i + 1] for i in range(len(run) - 1)]


class BM25:
    """经典 BM25，支持字段加权。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: List[Dict[str, List[str]]] = []   # 每篇：{"title":[], "tags":[], "content":[]}
        self.meta: List[Dict] = []
        self.avg_len = 1.0
        self.df: Dict[Tuple[str, str], int] = {}     # (field, term) -> 文档频率
        self.n = 0

    def fit(self, items: Iterable[Dict]) -> "BM25":
        self.docs = []
        self.meta = []
        self.df = {}
        for it in items:
            if not it.get("enabled", True):
                continue
            fields = {
                "title": tokenize(it.get("title", "")),
                "tags": tokenize(it.get("tags", "")),
                "content": tokenize(it.get("content", "")),
            }
            self.docs.append(fields)
            self.meta.append(it)
            seen = set()
            for f, toks in fields.items():
                for t in toks:
                    key = (f, t)
                    if key not in seen:
                        self.df[key] = self.df.get(key, 0) + 1
                        seen.add(key)
        self.n = len(self.docs)
        if self.n:
            total = sum(sum(len(v) for v in d.values()) for d in self.docs)
            self.avg_len = max(total / self.n, 1.0)
        return self

    def _idf(self, field: str, term: str) -> float:
        df = self.df.get((field, term), 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, query: str, weights: Dict[str, float] = None) -> List[Tuple[float, Dict]]:
        """返回 [(score, item), ...] 降序。"""
        if not self.n:
            return []
        weights = weights or {"title": 3.0, "tags": 2.5, "content": 1.0}
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        results = []
        for idx, fields in enumerate(self.docs):
            total = 0.0
            for field, w in weights.items():
                toks = fields.get(field, [])
                if not toks:
                    continue
                tf: Dict[str, int] = {}
                for t in toks:
                    tf[t] = tf.get(t, 0) + 1
                dl = len(toks)
                norm = self.k1 * (1 - self.b + self.b * dl / self.avg_len)
                for qt in q_tokens:
                    f = tf.get(qt, 0)
                    if not f:
                        continue
                    total += w * self._idf(field, qt) * (f * (self.k1 + 1)) / (f + norm)
            if total > 0:
                results.append((total, self.meta[idx]))
        results.sort(key=lambda x: x[0], reverse=True)
        return results


def retrieve(query: str, lore_items: Sequence[Dict], topk: int = 6,
             min_ratio: float = 0.0) -> List[Tuple[float, Dict]]:
    """便捷入口：检索并按相对分数截断。

    min_ratio: 只保留得分 >= 最高分 * min_ratio 的条目，避免硬凑无关资料污染上下文。
    """
    if not lore_items or topk <= 0:
        return []
    engine = BM25().fit(lore_items)
    hits = engine.score(query)
    if not hits:
        return []
    if min_ratio > 0:
        ceiling = hits[0][0] * min_ratio
        hits = [h for h in hits if h[0] >= ceiling]
    return hits[:topk]
