"""P4 五层难度：DifficultyLevel L1-L5、名字齐全、learner_brief 档位映射与序列化 round-trip。"""

import json

from tripcraft.contracts.enums import DIFFICULTY_NAMES, DifficultyLevel
from tripcraft.contracts.skill_points import SKILL_POINTS
from tripcraft.services.learner_brief import build_brief, difficulty_of


def abilities_all(value: float) -> dict:
    return {sp.id: {"teach": value, "real_v": 0.0} for sp in SKILL_POINTS}


def test_five_members_and_values():
    assert len(DifficultyLevel) == 5
    assert [m.value for m in DifficultyLevel] == ["L1", "L2", "L3", "L4", "L5"]
    assert DifficultyLevel.L5.value == "L5"


def test_difficulty_names_complete():
    assert set(DIFFICULTY_NAMES) == set(DifficultyLevel)
    assert DIFFICULTY_NAMES[DifficultyLevel.L5] == "极限"
    # L1-L4 既有名字不变（只加 L5，不改旧语义）
    assert [DIFFICULTY_NAMES[DifficultyLevel(f"L{i}")] for i in range(1, 5)] == [
        "入门", "进阶", "熟练", "高压",
    ]


def test_band_mapping_reaches_l5_at_90_plus():
    """整单档位 → 五层难度：<60→L1、60-69→L2、70-79→L3、80-89→L4、90+→L5。"""
    cases = [
        (45, 0, DifficultyLevel.L1, "补救"),
        (65, 1, DifficultyLevel.L2, "加压"),
        (85, 3, DifficultyLevel.L4, "加压"),
        (95, 4, DifficultyLevel.L5, "加压"),
    ]
    for weakest, level, want, branch in cases:
        b = build_brief(abilities_all(weakest))
        assert b.level == level, (weakest, b.level)
        assert b.branch == branch, (weakest, b.branch)
        assert b.difficulty is want, (weakest, b.difficulty)
        assert b.to_dict()["difficulty"] == want.value


def test_lowest_band_does_not_overflow_to_l0():
    """最弱 <60 走补救，钳到 L1，不能出 L0 / 越界。"""
    b = build_brief(abilities_all(0))
    assert b.level == 0 and b.branch == "补救"
    assert b.difficulty is DifficultyLevel.L1
    assert difficulty_of(-3) is DifficultyLevel.L1


def test_min_5_path_at_full_score():
    """min(5, …) 顶格：满分 → level 5 → 仍封顶 L5，不抛 IndexError。"""
    b = build_brief(abilities_all(100))
    assert b.level == 5
    assert b.difficulty is DifficultyLevel.L5
    assert difficulty_of(5) is DifficultyLevel.L5


def test_serialization_round_trip():
    assert DifficultyLevel("L5") is DifficultyLevel.L5
    assert str(DifficultyLevel.L5) == "L5"
    dumped = json.dumps(DifficultyLevel.L5)
    assert dumped == '"L5"'
    assert DifficultyLevel(json.loads(dumped)) is DifficultyLevel.L5
