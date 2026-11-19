"""P7 确定性向量索引测试：同文本同向量、相近 > 不相关、排序、空输入、清空。"""

from __future__ import annotations

import math

import pytest

from tripcraft.services.vector_index import VectorIndex, embed

DIM = 256


def _cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def test_embed_same_text_same_vector():
    text = "旅行定制师要掌握需求分析"
    assert embed(text) == embed(text)
    assert embed(text, 64) == embed(text, 64)


def test_embed_deterministic_across_processes():
    # 黄金值由本实现一次性记录。若用内置 hash()（受 PYTHONHASHSEED 随机化），
    # 换一个进程就无法命中这些分箱位置。
    # "travel planner" -> "travelplanner"：23 个 2/3-gram，碰撞后落在 18 个箱，
    # 权重平方和 35，故每个箱的值 = 权重 / sqrt(35)。
    bins = {
        2: 1, 7: 2, 8: 1, 16: 1, 17: 1, 19: 1, 23: 3, 24: 1, 29: 2,
        33: 1, 34: 1, 37: 1, 46: 1, 47: 2, 51: 1, 52: 1, 55: 1, 59: 1,
    }
    expected = [0.0] * 64
    for index, weight in bins.items():
        expected[index] = weight / math.sqrt(35.0)
    assert embed("travel planner", 64) == pytest.approx(expected, abs=1e-12)


def test_embed_l2_normalized_and_dim():
    vec = embed("定制旅行方案与报价")
    assert len(vec) == DIM
    assert math.sqrt(sum(x * x for x in vec)) == pytest.approx(1.0, abs=1e-12)
    assert all(x >= 0.0 for x in vec)
    assert len(embed("定制", 16)) == 16


def test_embed_empty_text_is_zero_vector():
    assert embed("") == [0.0] * DIM
    assert embed(" \n\t ") == [0.0] * DIM
    # 单字符文本没有 2/3-gram，退化为整串一个特征，不能是零向量。
    assert any(value > 0.0 for value in embed("旅", 8))


def test_embed_rejects_non_positive_dim():
    with pytest.raises(ValueError):
        embed("任意文本", 0)
    with pytest.raises(ValueError):
        VectorIndex(dim=-1)


def test_similar_text_scores_higher_than_unrelated():
    base = "定制师需要根据客户预算设计行程"
    near = "定制师需要依据客户预算设计行程"
    far = "汇率换算与外币结算流程"
    assert _cosine(embed(base), embed(near)) > _cosine(embed(base), embed(far))


def _build_index(dim: int = 128) -> VectorIndex:
    idx = VectorIndex(dim=dim)
    idx.add("d1", "定制师需要根据客户预算设计行程", {"kind": "plan"})
    idx.add("d2", "汇率换算与外币结算流程", {"kind": "fx"})
    idx.add("d3", "客户预算有限时如何调整酒店档次")
    return idx


def test_search_returns_sorted_tuples():
    idx = _build_index()
    results = idx.search("客户预算设计行程", top_k=3)
    assert len(results) == 3
    scores = [score for _, score, _ in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0][0] == "d1"
    doc_id, score, meta = results[0]
    assert isinstance(doc_id, str)
    assert isinstance(score, float)
    assert isinstance(meta, dict)
    assert meta == {"kind": "plan"}
    assert results[1][0] == "d3"


def test_search_top_k_limits():
    idx = _build_index()
    assert len(idx.search("客户预算", top_k=2)) == 2
    assert idx.search("客户预算", top_k=0) == []
    assert idx.search("客户预算", top_k=-1) == []
    assert len(idx.search("客户预算", top_k=99)) == 3


def test_search_empty_index_returns_empty():
    assert VectorIndex().search("任意查询") == []


def test_search_empty_or_blank_query_returns_empty():
    idx = _build_index()
    assert idx.search("") == []
    assert idx.search("   ") == []


def test_search_is_repeatable():
    idx = _build_index()
    first = idx.search("客户预算")
    assert first == idx.search("客户预算")
    assert first == _build_index().search("客户预算")


def test_add_appends_and_clear_empties_index():
    idx = VectorIndex()
    assert len(idx) == 0
    idx.add("a", "旅行定制")
    idx.add("b", "签证办理")
    assert len(idx) == 2
    assert idx.search("旅行定制", top_k=1)[0][0] == "a"
    assert idx.search("签证办理", top_k=1)[0][0] == "b"
    idx.clear()
    assert len(idx) == 0
    assert idx.search("旅行定制") == []
    idx.add("c", "重新加入")
    assert [doc_id for doc_id, _, _ in idx.search("重新加入", top_k=1)] == ["c"]


def test_add_meta_defaults_to_empty_dict():
    idx = VectorIndex()
    idx.add("x", "无元数据")
    assert idx.search("无元数据", top_k=1)[0][2] == {}


def test_duplicate_doc_id_keeps_both_entries():
    idx = VectorIndex()
    idx.add("same", "第一次加入的描述")
    idx.add("same", "第二次加入的描述")
    assert len(idx.search("加入的描述", top_k=5)) == 2
