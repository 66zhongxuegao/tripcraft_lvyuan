"""确定性字符 n-gram 向量索引 —— 离线、无第三方依赖的轻量检索兜底。

设计目标（PPT 技术点 P7）：

- ``embed(text)``：把文本拆成字符 n-gram（n=2,3），用 blake2b 稳定哈希映射到
  ``dim`` 维计数向量，再做 L2 归一化。哈希、计数、累加顺序全部确定，
  因此**同一文本在任何进程、任何 PYTHONHASHSEED 下得到同一向量**
  （不使用内置 ``hash()``，它受哈希随机化影响）。
- ``VectorIndex``：内存内追加式索引；``search`` 用余弦相似度降序返回
  ``(doc_id, score, meta)``。空索引、空 query、空白 query 一律返回 ``[]``，
  同一 query 多次检索结果完全一致。
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter

__all__ = ["embed", "VectorIndex"]

_NGRAM_SIZES = (2, 3)
_HASH_DIGEST_SIZE = 8


def _normalize(text: str) -> str:
    """去掉所有空白并小写：让「旅 行 定 制」与「旅行定制」产生同样的 n-gram。"""
    return "".join((text or "").lower().split())


def _ngrams(text: str) -> list[str]:
    seq = _normalize(text)
    grams: list[str] = []
    for n in _NGRAM_SIZES:
        if len(seq) < n:
            continue
        grams.extend(seq[i : i + n] for i in range(len(seq) - n + 1))
    if not grams and seq:
        # 单字符文本没有 2/3-gram，退化为整串一个特征，避免零向量。
        grams.append(seq)
    return grams


def _stable_hash(gram: str) -> int:
    """跨进程稳定的哈希：blake2b 是标准库实现，与 PYTHONHASHSEED 无关。"""
    digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=_HASH_DIGEST_SIZE).digest()
    return int.from_bytes(digest, "big")


def embed(text: str, dim: int = 256) -> list[float]:
    """把文本编码成 L2 归一化的 ``dim`` 维向量（纯 Python，确定性）。"""
    if dim <= 0:
        raise ValueError(f"dim 必须为正整数，收到 {dim!r}")
    vec = [0.0] * dim
    for gram, count in sorted(Counter(_ngrams(text)).items()):
        vec[_stable_hash(gram) % dim] += float(count)
    norm = math.sqrt(sum(value * value for value in vec))
    if norm == 0.0:
        return vec
    return [value / norm for value in vec]


class VectorIndex:
    """追加式内存向量索引：``add`` 追加，``search`` 余弦降序，可 ``clear``。"""

    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError(f"dim 必须为正整数，收到 {dim!r}")
        self.dim = dim
        self._entries: list[tuple[str, list[float], dict]] = []

    def add(self, doc_id: str, text: str, meta: dict | None = None) -> None:
        """追加一条文档；同 ``doc_id`` 重复 add 视为多条（不覆盖）。"""
        self._entries.append((str(doc_id), embed(text, self.dim), dict(meta or {})))

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float, dict]]:
        """按余弦相似度降序返回 ``(doc_id, score, meta)``；同分保持插入顺序。"""
        if top_k <= 0 or not self._entries:
            return []
        query_vec = embed(query, self.dim)
        query_norm = math.sqrt(sum(value * value for value in query_vec))
        if query_norm == 0.0:
            return []
        scored = [
            (doc_id, sum(q * d for q, d in zip(query_vec, vec)) / query_norm, dict(meta))
            for doc_id, vec, meta in self._entries
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]
