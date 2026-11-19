"""P4（五层难度 L1–L5）/ P5（67 维评分矩阵）独立交叉验收 —— ver-03。

契约来源：`.dsh-run/ppt-spec.md` P4 / P5。

P4：
- `DifficultyLevel` 5 个成员（L1–L5），`DIFFICULTY_NAMES["L5"] == "极限"`；
- `DifficultyLevel("L5")` 可按 value 构造；
- `learner_brief.build_brief()` 在 weakest（最弱主考技能点）= 95 分时给 L5
  （实际可观察接口：`LearnerBrief.difficulty` / `difficulty_of()`）。

P5：
- `ALL_DIMENSION_IDS` 共 67 项；
- 前 61 项与 `SKILL_POINTS` 的 id 一一对应（同序、无重复）；
- 6 个横切维存在；
- `build_scoring_matrix({})` 不崩、返回 67 项；
- 给定部分分数时，技能点直通、横切维按声明源求均值。

本文件只读实现，不改实现。
"""

from __future__ import annotations

import pytest

from tripcraft.contracts.enums import DIFFICULTY_NAMES, DifficultyLevel
from tripcraft.contracts.scoring_dimensions import (
    ALL_DIMENSION_IDS,
    CROSS_DIMENSION_SOURCES,
    CROSS_DIMENSIONS,
    build_scoring_matrix,
)
from tripcraft.contracts.skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID
from tripcraft.services.learner_brief import build_brief

CROSS_EXPECTED = (
    "X1_EXPERIENCE",
    "X2_COST",
    "X3_COMPLIANCE",
    "X4_SAFETY",
    "X5_EFFICIENCY",
    "X6_RELATION",
)


# ---------------------------------------------------------------- P4 五层难度

def test_difficulty_level_has_five_members() -> None:
    assert len(list(DifficultyLevel)) == 5
    assert [m.value for m in DifficultyLevel] == ["L1", "L2", "L3", "L4", "L5"]
    assert len(DIFFICULTY_NAMES) == 5


def test_l5_name_is_jixian() -> None:
    assert DIFFICULTY_NAMES["L5"] == "极限"
    assert DIFFICULTY_NAMES[DifficultyLevel.L5] == "极限"


def test_difficulty_level_lookup_by_value() -> None:
    assert DifficultyLevel("L5") is DifficultyLevel.L5
    assert str(DifficultyLevel.L5) == "L5"


def _abilities_all(value: float) -> dict[str, dict]:
    """61 个技能点全部已评估且同分，保证最弱主考技能点 = value。"""
    return {sp.id: {"teach": value, "real_v": 0.0} for sp in SKILL_POINTS}


def test_learner_brief_weakest_95_gives_l5() -> None:
    brief = build_brief(_abilities_all(95.0))
    assert brief.branch == "加压"
    assert brief.difficulty is DifficultyLevel.L5, (
        f"weakest=95 应给 L5，实际 {brief.difficulty}（内部 level={brief.level}）"
    )
    assert brief.to_dict()["difficulty"] == "L5"


# ---------------------------------------------------------------- P5 67 维

def test_all_dimension_ids_length_67() -> None:
    assert len(SKILL_POINTS) == 61
    assert len(ALL_DIMENSION_IDS) == 67
    assert len(set(ALL_DIMENSION_IDS)) == 67


def test_first_61_match_skill_points_in_order() -> None:
    assert ALL_DIMENSION_IDS[:61] == tuple(sp.id for sp in SKILL_POINTS)
    for sp in SKILL_POINTS:
        assert ALL_DIMENSION_IDS.count(sp.id) == 1, f"{sp.id} 应恰好出现一次"


def test_six_cross_dimensions_present() -> None:
    assert len(CROSS_DIMENSIONS) == 6
    assert CROSS_DIMENSIONS == CROSS_EXPECTED
    assert ALL_DIMENSION_IDS[61:] == CROSS_EXPECTED
    for cid in CROSS_EXPECTED:
        assert cid in ALL_DIMENSION_IDS
        ids = CROSS_DIMENSION_SOURCES[cid]
        assert ids, f"{cid} 无相关技能点"
        assert set(ids) <= set(SKILL_POINTS_BY_ID), f"{cid} 引用了不存在的技能点"


def test_build_matrix_empty_returns_67_without_crash() -> None:
    matrix = build_scoring_matrix({})
    assert len(matrix) == 67
    assert tuple(matrix) == ALL_DIMENSION_IDS
    assert all(v == 0.0 for v in matrix.values())


def test_build_matrix_partial_scores_correct() -> None:
    scores = {"C1.1": 91.0, "C5.3": 78.5, "C6.2": 60.0}
    matrix = build_scoring_matrix(dict(scores))
    assert len(matrix) == 67
    # 61 技能点直通
    for sp_id, score in scores.items():
        assert matrix[sp_id] == score
    assert matrix["C2.1"] == 0.0
    # 6 横切维 = 声明源技能点的算术均值（缺省按 0 参与）
    for cid in CROSS_EXPECTED:
        ids = CROSS_DIMENSION_SOURCES[cid]
        expected = sum(scores.get(i, 0.0) for i in ids) / len(ids)
        assert matrix[cid] == pytest.approx(expected), f"{cid} 聚合值不符"


def test_build_matrix_full_marks_aggregate_to_100() -> None:
    scores = {sp.id: 100.0 for sp in SKILL_POINTS}
    matrix = build_scoring_matrix(scores)
    assert len(matrix) == 67
    assert all(v == pytest.approx(100.0) for v in matrix.values())
