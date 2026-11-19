"""P5 67 维评分矩阵契约测试（61 技能点 + 6 横切维）。

覆盖：维度总数、61 技能点全覆盖且无重复、6 横切维存在、矩阵 67 项、
缺省输入不崩、横切聚合规则可复现（同输入同输出）。
"""

from __future__ import annotations

import pytest

from tripcraft.contracts.scoring_dimensions import (
    ALL_DIMENSION_IDS,
    CROSS_DIMENSION_SOURCES,
    CROSS_DIMENSIONS,
    _mean_of,
    build_scoring_matrix,
)
from tripcraft.contracts.skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID


def test_all_dimension_ids_len_67() -> None:
    assert len(ALL_DIMENSION_IDS) == 67


def test_61_skill_point_ids_covered_in_order_without_duplicate() -> None:
    sp_ids = tuple(sp.id for sp in SKILL_POINTS)
    assert len(sp_ids) == 61
    assert ALL_DIMENSION_IDS[:61] == sp_ids
    assert len(set(ALL_DIMENSION_IDS)) == 67
    # 61 个技能点 id 全部出现且各出现一次
    for sp_id in sp_ids:
        assert sp_id in ALL_DIMENSION_IDS
        assert ALL_DIMENSION_IDS.count(sp_id) == 1


def test_six_cross_dimensions_present_in_stable_tail() -> None:
    assert len(CROSS_DIMENSIONS) == 6
    assert CROSS_DIMENSIONS == (
        "X1_EXPERIENCE",
        "X2_COST",
        "X3_COMPLIANCE",
        "X4_SAFETY",
        "X5_EFFICIENCY",
        "X6_RELATION",
    )
    assert ALL_DIMENSION_IDS[61:] == CROSS_DIMENSIONS
    for cross_id in CROSS_DIMENSIONS:
        assert ALL_DIMENSION_IDS.count(cross_id) == 1


def test_cross_sources_reference_existing_skill_points() -> None:
    assert set(CROSS_DIMENSION_SOURCES) == set(CROSS_DIMENSIONS)
    for cross_id in CROSS_DIMENSIONS:
        ids = CROSS_DIMENSION_SOURCES[cross_id]
        assert ids, f"{cross_id} 无相关技能点"
        assert set(ids) <= set(SKILL_POINTS_BY_ID), f"{cross_id} 引用不存在的技能点"


def test_matrix_returns_67_items_in_stable_order() -> None:
    scores = {sp.id: float(i) for i, sp in enumerate(SKILL_POINTS)}
    matrix = build_scoring_matrix(scores)
    assert len(matrix) == 67
    assert tuple(matrix) == ALL_DIMENSION_IDS


def test_direct_skill_point_scores_passed_through() -> None:
    matrix = build_scoring_matrix({"C1.1": 88.0, "C7.2": 42.5})
    assert matrix["C1.1"] == 88.0
    assert matrix["C7.2"] == 42.5


def test_missing_input_defaults_to_zero_without_keyerror() -> None:
    empty = build_scoring_matrix({})
    assert len(empty) == 67
    assert all(v == 0.0 for v in empty.values())

    partial = build_scoring_matrix({"C5.1": 60.0})
    assert len(partial) == 67
    assert partial["C5.1"] == 60.0
    assert partial["C5.2"] == 0.0
    assert partial["C8.7"] == 0.0


def test_cross_dimension_is_mean_of_declared_sources() -> None:
    scores = {sp.id: float((i * 7) % 101) for i, sp in enumerate(SKILL_POINTS)}
    matrix = build_scoring_matrix(scores)
    for cross_id in CROSS_DIMENSIONS:
        ids = CROSS_DIMENSION_SOURCES[cross_id]
        expected = sum(scores[i] for i in ids) / len(ids)
        assert matrix[cross_id] == pytest.approx(expected), cross_id


def test_aggregation_reproducible_same_input_same_output() -> None:
    scores = {sp.id: float((i * 3) % 97) for i, sp in enumerate(SKILL_POINTS)}
    first = build_scoring_matrix(dict(scores))
    # 逆序插入键：输入顺序不影响结果，输出顺序恒为 ALL_DIMENSION_IDS
    shuffled = {k: scores[k] for k in reversed(list(scores))}
    second = build_scoring_matrix(shuffled)
    assert first == second
    assert list(first) == list(ALL_DIMENSION_IDS)
    assert list(second) == list(ALL_DIMENSION_IDS)


def test_no_related_skill_points_yields_zero() -> None:
    # 无相关技能点（空 id 列表）→ 0.0，且不因缺失键崩溃
    assert _mean_of((), {"C1.1": 90.0}) == 0.0
    # 相关技能点全部缺省 → 均值也是 0.0
    assert _mean_of(("C1.1", "C4.1"), {}) == 0.0
