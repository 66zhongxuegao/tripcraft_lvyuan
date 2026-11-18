"""P6 / P7 独立交叉验收（ver-04，只读实现）。

契约来源：``.dsh-run/ppt-spec.md`` 第 75-94 行。
本文件只做验证，不改实现；每个断言对应契约或任务书中的一条要求。

- P6 ``tripcraft/services/retrieval_router.py``：三库路由、检索结果字段、top_k、空结果不抛。
- P7 ``tripcraft/services/vector_index.py``：embed 确定性、相近文本余弦更高、search 降序、
  空索引、重复 add。
"""

from __future__ import annotations

import math

import pytest

from tripcraft.services import retrieval as retrieval_mod
from tripcraft.services import retrieval_router as router


# ---------------------------------------------------------------- 工具

def _cosine(a: list[float], b: list[float]) -> float:
    """独立实现的余弦相似度，用于核对 search 的得分口径。"""
    assert len(a) == len(b)
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    assert norm_a > 0 and norm_b > 0
    return dot / (norm_a * norm_b)


def _vector_index_module():
    """延迟导入 P7 模块：P7 未就绪时 P6 用例仍能单独给出结论。"""
    from tripcraft.services import vector_index

    return vector_index


# ================================================================ P6 路由

@pytest.mark.parametrize(
    "task, expected",
    [
        ("报价与成本", "sop"),
        ("订单案例复盘", "order"),
        ("知识点讲解", "textbook"),
    ],
)
def test_route_known_categories(task: str, expected: str) -> None:
    assert router.route(task) == expected


@pytest.mark.parametrize("task", ["", "   ", "帮我查一下明天的天气", "zzz 未收录任务"])
def test_route_unknown_falls_back_to_textbook(task: str) -> None:
    assert router.route(task) == "textbook"


def test_libraries_contract() -> None:
    assert set(router.LIBRARIES) == {"textbook", "sop", "order"}


# ================================================================ P6 检索

@pytest.mark.parametrize(
    "task, expected_library",
    [
        ("报价与成本", "sop"),
        ("订单案例复盘", "order"),
        ("知识点讲解", "textbook"),
    ],
)
def test_retrieve_fields_and_library(task: str, expected_library: str) -> None:
    results = router.retrieve(task, "C1.1", "开场")
    assert results, f"{task!r} 对 C1.1 应能召回知识片段"
    for item in results:
        assert set(item) == {"text", "source", "library", "scenario"}
        assert isinstance(item["text"], str) and item["text"].strip()
        assert isinstance(item["source"], str) and item["source"].strip()
        assert item["library"] == expected_library
        assert item["library"] in router.LIBRARIES
        assert isinstance(item["scenario"], str) and item["scenario"].strip()
        assert "C1.1" in item["scenario"], "scenario 应包含技能点上下文"


def test_retrieve_top_k_effective() -> None:
    one = router.retrieve("报价与成本", "C1.1", "", top_k=1)
    three = router.retrieve("报价与成本", "C1.1", "", top_k=3)
    assert len(one) == 1
    assert len(three) == 3
    assert len(three) <= 3


def test_retrieve_default_top_k_within_six() -> None:
    results = router.retrieve("报价与成本", "C1.1", "")
    assert 1 <= len(results) <= 6


def test_retrieve_unknown_skill_point_returns_empty() -> None:
    assert router.retrieve("报价与成本", "SP_NOT_EXIST", "开场") == []


def test_retrieve_retriever_failure_returns_empty(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("retriever 不可用")

    monkeypatch.setattr(retrieval_mod, "get_retriever", _boom)
    assert router.retrieve("报价与成本", "C1.1", "开场") == []


# ================================================================ P7 embed

def test_embed_is_deterministic() -> None:
    vector_index = _vector_index_module()
    first = vector_index.embed("同样的文本")
    second = vector_index.embed("同样的文本")
    assert first == second
    assert len(first) == 256


def test_embed_respects_dim() -> None:
    vector_index = _vector_index_module()
    assert len(vector_index.embed("同样的文本", dim=32)) == 32


def test_embed_similar_text_scores_higher_than_unrelated() -> None:
    vector_index = _vector_index_module()
    base = "客户报价单需要填写行程日期、人数与费用明细"
    similar = "客户报价单需要填写行程日期和人数，还有费用明细"
    unrelated = "今天天气晴朗，适合去海边散步并拍照留念"

    similar_cos = _cosine(vector_index.embed(base), vector_index.embed(similar))
    unrelated_cos = _cosine(vector_index.embed(base), vector_index.embed(unrelated))
    assert similar_cos > unrelated_cos, (
        f"相近文本余弦 {similar_cos:.4f} 应大于无关文本 {unrelated_cos:.4f}"
    )


# ================================================================ P7 search

def test_search_scores_are_descending() -> None:
    vector_index = _vector_index_module()
    index = vector_index.VectorIndex()
    docs = {
        "doc-near": "客户报价单需要填写行程日期、人数与费用明细",
        "doc-mid": "订单案例复盘需要核对客户投诉事件",
        "doc-far": "今天天气晴朗，适合去海边散步并拍照留念",
    }
    for doc_id, text in docs.items():
        index.add(doc_id, text, {"id": doc_id})

    results = index.search("客户报价单怎么填写费用明细", top_k=3)
    assert len(results) == 3
    scores = [score for _doc_id, score, _meta in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0][0] == "doc-near"
    for doc_id, score, meta in results:
        assert isinstance(doc_id, str)
        assert isinstance(score, float)
        assert isinstance(meta, dict)
        assert score == pytest.approx(
            _cosine(vector_index.embed("客户报价单怎么填写费用明细"), vector_index.embed(docs[doc_id])),
            rel=1e-9,
            abs=1e-12,
        )


def test_search_respects_top_k() -> None:
    vector_index = _vector_index_module()
    index = vector_index.VectorIndex()
    index.add("a", "客户报价单填写")
    index.add("b", "订单案例复盘")
    index.add("c", "知识点讲解")
    assert len(index.search("报价单", top_k=2)) == 2


def test_empty_index_search_returns_empty_list() -> None:
    vector_index = _vector_index_module()
    assert vector_index.VectorIndex().search("任意查询") == []


def test_duplicate_add_does_not_crash() -> None:
    vector_index = _vector_index_module()
    index = vector_index.VectorIndex()
    index.add("dup", "客户报价单填写", {"v": 1})
    index.add("dup", "客户报价单填写", {"v": 2})

    results = index.search("客户报价单", top_k=5)
    assert isinstance(results, list)
    assert all(doc_id == "dup" for doc_id, _score, _meta in results)
    scores = [score for _doc_id, score, _meta in results]
    assert scores == sorted(scores, reverse=True)
