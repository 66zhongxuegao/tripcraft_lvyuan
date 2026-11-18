"""P10 短板 top-3：AbilityProfile.weak_top 与 learner_brief 目标技能点的一致性。"""

from tripcraft.contracts.profile import AbilityProfile
from tripcraft.contracts.skill_points import SKILL_POINTS
from tripcraft.services.learner_brief import build_brief


def _abilities(values: dict[str, float] | None = None) -> dict:
    """按技能点值构造 build_brief 的入参（teach 侧，real_v 留空 = 已评估）。"""
    values = values or {}
    return {sp.id: {"teach": values.get(sp.id, 80.0), "real_v": 0.0} for sp in SKILL_POINTS}


# ---------------- AbilityProfile.weak_top ----------------

def test_weak_top_caps_at_three():
    profile = AbilityProfile({"C1.1": 10.0, "C1.2": 20.0, "C2.1": 30.0, "C2.2": 40.0})
    assert profile.weak_top() == ["C1.1", "C1.2", "C2.1"]
    assert len(profile.weak_top(3)) == 3


def test_weak_top_returns_all_when_fewer_than_n():
    profile = AbilityProfile({"C1.1": 70.0, "C2.1": 20.0})
    assert profile.weak_top(3) == ["C2.1", "C1.1"]
    assert profile.weak_top(10) == ["C2.1", "C1.1"]


def test_low_scores_come_first():
    profile = AbilityProfile({"C1.1": 90.0, "C1.2": 45.0, "C1.3": 61.0})
    assert profile.weak_top(3) == ["C1.2", "C1.3", "C1.1"]


def test_ties_are_ordered_by_skill_point_id():
    profile = AbilityProfile({"C2.1": 50.0, "C1.2": 50.0, "C1.1": 50.0})
    expected = ["C1.1", "C1.2", "C2.1"]
    assert profile.weak_top(3) == expected
    assert profile.weak_top(3) == expected, "同分排序必须稳定"


def test_empty_profile_has_no_weak_points():
    assert AbilityProfile().weak_top() == []
    assert AbilityProfile({}).weak_top(3) == []
    assert AbilityProfile({"C1.1": 0.0}).weak_top(0) == []


# ---------------- learner_brief 目标与 weak_top 一致 ----------------

def test_brief_targets_match_weak_top():
    values = {"C3.2": 41.0, "C5.1": 47.0, "C7.3": 52.0}
    brief = build_brief(_abilities(values))
    expected = AbilityProfile({sp.id: 80.0 for sp in SKILL_POINTS} | values).weak_top(3)
    assert tuple(expected) == ("C3.2", "C5.1", "C7.3")
    assert brief.target_skill_points == tuple(expected)
    assert len(brief.target_skill_points) <= 3


def test_brief_targets_match_weak_top_on_empty_profile():
    brief = build_brief({})
    expected = AbilityProfile({sp.id: 0.0 for sp in SKILL_POINTS}).weak_top(3)
    assert brief.target_skill_points == tuple(expected)
    assert len(brief.target_skill_points) == 3


def test_brief_keeps_carried_over_priority():
    values = {"C3.2": 41.0, "C5.1": 47.0, "C7.3": 52.0}
    carried = ["C1.8", "C2.7"]
    brief = build_brief(_abilities(values), carried_over=carried)
    assert brief.target_skill_points[:2] == tuple(carried)
    assert "C3.2" in brief.target_skill_points
    assert brief.carried_over == tuple(carried)
