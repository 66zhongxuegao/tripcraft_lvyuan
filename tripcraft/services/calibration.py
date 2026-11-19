"""P11 校准集与双评一致性（离线，无第三方依赖）。

- ``load_calibration``：优先走 ``tripcraft.calibration.dataset.load_samples``
  （读 ``data/calibration/samples.jsonl``，真实校准集接口）；现存样本只有单评人工
  标注（``labels[].level``），没有 a/b 双评记录，因此取不到双评行时回退到内置 3 条样例。
- ``agreement``：两组连续评分的 exact / within_5 / Cohen's kappa。
  连续分先按 ``ceil(score / 20)`` 离散成 1..5 档，再按多分类标准公式算 kappa。
- ``evaluate``：``records`` 每条 ``{"a": float, "b": float}``，返回 agreement + ``ok``。
"""

from __future__ import annotations

import math
from collections import Counter

KAPPA_OK = 0.6
WITHIN = 5.0

# 内置样例：a/b 为两位评分者给出的 0-100 分
BUILTIN_SAMPLES: tuple[dict, ...] = (
    {"a": 92.0, "b": 90.0},
    {"a": 78.0, "b": 74.0},
    {"a": 65.0, "b": 58.0},
)


def _bucket(score: float) -> int:
    """0-100 连续分 → 1..5 档（ceil(score/20)，两端夹紧）。"""
    return max(1, min(5, math.ceil(score / 20)))


def _load_existing() -> list[dict]:
    """读现有校准集里带 a/b 双评的记录；单评样本不算。"""
    from tripcraft.calibration.dataset import load_samples

    out = []
    for row in load_samples():
        a, b = row.get("a"), row.get("b")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out.append({"a": float(a), "b": float(b)})
    return out


def load_calibration() -> list[dict]:
    """现有校准集优先，无可用双评数据时返回内置 3 条样例。"""
    return _load_existing() or [dict(r) for r in BUILTIN_SAMPLES]


def agreement(ratings_a: list[float], ratings_b: list[float]) -> dict:
    """两组评分的 exact / within_5 / Cohen's kappa（多分类，连续分先离散化）。"""
    a = [float(x) for x in ratings_a]
    b = [float(x) for x in ratings_b]
    if len(a) != len(b):
        raise ValueError(f"两组评分长度不等：len(a)={len(a)} len(b)={len(b)}")
    n = len(a)
    if n == 0:
        return {"n": 0, "exact": 0.0, "within_5": 0.0, "cohen_kappa": 0.0}

    exact = sum(1 for x, y in zip(a, b) if x == y) / n
    within_5 = sum(1 for x, y in zip(a, b) if abs(x - y) <= WITHIN) / n

    la = [_bucket(x) for x in a]
    lb = [_bucket(y) for y in b]
    po = sum(1 for x, y in zip(la, lb) if x == y) / n
    ca, cb = Counter(la), Counter(lb)
    pe = sum(ca[c] * cb[c] for c in ca) / (n * n)
    if pe >= 1.0:                       # 两组都只用了一个档：无方差，kappa 退化为 1/0
        kappa = 1.0 if po >= 1.0 else 0.0
    else:
        kappa = (po - pe) / (1.0 - pe)

    return {"n": n, "exact": exact, "within_5": within_5, "cohen_kappa": kappa}


def evaluate(records: list[dict]) -> dict:
    """records 每条 {"a": float, "b": float}；返回 agreement 结果 + ok（kappa >= 0.6）。"""
    out = agreement([r["a"] for r in records], [r["b"] for r in records])
    out["ok"] = out["cohen_kappa"] >= KAPPA_OK
    return out
