"""P10 短板 top-3 / P11 校准集一致性 —— 独立验收（ver-06，只测契约，不改实现）。

契约来源：.dsh-run/ppt-spec.md:113-128

P10  tripcraft/contracts/profile.py
    class AbilityProfile:
        def weak_top(self, n: int = 3) -> list[str]   # 低分优先，稳定排序（同分按 id）

P11  tripcraft/services/calibration.py
    def load_calibration() -> list[dict]
    def agreement(ratings_a: list[float], ratings_b: list[float]) -> dict
        # {"n": int, "exact": float, "within_5": float, "cohen_kappa": float}
        # 连续值先按 5 分档离散化再算 kappa
    def evaluate(records: list[dict]) -> dict
        # 每条 {"a": float, "b": float}，返回 agreement 结果 + "ok": bool（kappa >= 0.6）

契约没有规定 AbilityProfile 的构造口径，因此这里按「能力表」构造：
优先用构造参数名里带 ability/score 的字段；没有则退回 set_ability()。
两者都拿不到能力表，就直接失败并把真实签名写进断言消息 —— 交回报告用。

评分尺度：工程内能力值/评分统一 0-100（AbilityParam 已夹紧 0-100），P11 的
``within_5`` 即「相差不超过 5 分」，故 agreement 用例一律给 0-100 分，且取值跨
5 个档位（≥1/5 分差之外），这样 kappa 才真正被检验，不会因同档退化。
"""

from __future__ import annotations

import inspect

import pytest

try:                                    # 契约未落地时给出指名道姓的失败，而不是收集期崩溃
    from tripcraft.contracts.profile import AbilityProfile
except ImportError as exc:              # pragma: no cover - 落地后走不到
    AbilityProfile = None
    _PROFILE_IMPORT_ERROR = exc
else:
    _PROFILE_IMPORT_ERROR = None

try:
    from tripcraft.services.calibration import agreement, evaluate, load_calibration
except ImportError as exc:              # pragma: no cover - 落地后走不到
    agreement = evaluate = load_calibration = None
    _CALIB_IMPORT_ERROR = exc
else:
    _CALIB_IMPORT_ERROR = None


# 5 个真实技能点 id（AbilityParam.__post_init__ 会校验 id 存在）
SP_IDS = ("C1.1", "C1.2", "C1.3", "C1.4", "C1.5")

# 契约样例：5 个技能点分数 {70, 50, 90, 60, 80}
SCORES = {"C1.1": 70.0, "C1.2": 50.0, "C1.3": 90.0, "C1.4": 60.0, "C1.5": 80.0}
LOWEST_THREE = ["C1.2", "C1.4", "C1.1"]             # 50, 60, 70 升序


# ---------------- P10：AbilityProfile.weak_top ----------------

def make_profile(scores: dict[str, float]):
    """按能力表构造 AbilityProfile（构造口径契约未定，见模块 docstring）。"""
    assert AbilityProfile is not None, (
        "P10 未落地：tripcraft/contracts/profile.py 里没有 AbilityProfile"
        f"（import 失败：{_PROFILE_IMPORT_ERROR}）"
    )
    sig = inspect.signature(AbilityProfile)
    kwargs: dict[str, object] = {}
    for name, param in sig.parameters.items():
        if param.kind in (param.VAR_KEYWORD, param.VAR_POSITIONAL):
            continue
        low = name.lower()
        if "abilit" in low or "score" in low or low in {"params", "values", "points"}:
            kwargs[name] = dict(scores)
        elif low in {"user_id", "learner_id", "uid"} and param.default is param.empty:
            kwargs[name] = "u-verify"
    if kwargs:
        return AbilityProfile(**kwargs)
    assert hasattr(AbilityProfile, "set_ability"), (
        f"AbilityProfile 既无能力表构造参数也无 set_ability()，签名：{sig}"
    )
    profile = AbilityProfile()
    for sp_id, value in scores.items():
        profile.set_ability(sp_id, value)
    return profile


def test_weak_top_3_returns_lowest_three_ascending():
    got = make_profile(SCORES).weak_top(3)
    assert isinstance(got, list), f"weak_top 应返回 list，实际 {type(got)}"
    assert got == LOWEST_THREE, f"应为 50/60/70 三个 id 升序，实际 {got}"


def test_weak_top_default_n_is_three():
    got = make_profile(SCORES).weak_top()
    assert got == LOWEST_THREE, f"默认 n 应为 3，实际 {got}"


def test_weak_top_ties_break_by_id():
    """同分按 id 升序，与插入顺序无关。"""
    scores = {"C1.3": 60.0, "C1.5": 60.0, "C1.1": 60.0, "C1.2": 95.0}
    got = make_profile(scores).weak_top(3)
    assert got == ["C1.1", "C1.3", "C1.5"], f"同分应按 id 排序，实际 {got}"


def test_weak_top_empty_profile_returns_empty_list():
    got = make_profile({}).weak_top(3)
    assert got == [], f"空画像应返回 []，实际 {got}"


def test_weak_top_n_1_and_n_5_boundaries():
    profile = make_profile(SCORES)
    assert profile.weak_top(1) == ["C1.2"], "n=1 应只返回最低分"
    assert profile.weak_top(5) == ["C1.2", "C1.4", "C1.1", "C1.5", "C1.3"], "n=5 应覆盖全部并升序"


# ---------------- P11：校准集与双评一致性 ----------------

def _require_calibration() -> None:
    assert agreement is not None, (
        "P11 未落地：tripcraft/services/calibration.py 不存在或未导出"
        f" load_calibration/agreement/evaluate（import 失败：{_CALIB_IMPORT_ERROR}）"
    )


KAPPA_KEYS = ("n", "exact", "within_5", "cohen_kappa")


def test_agreement_identical_ratings_gives_kappa_one():
    _require_calibration()
    a = [95.0, 75.0, 55.0, 35.0, 15.0, 90.0, 70.0, 40.0]   # 0-100 且跨 5 档
    result = agreement(a, list(a))
    missing = [k for k in KAPPA_KEYS if k not in result]
    assert not missing, f"agreement 缺字段 {missing}，实际 {result}"
    assert result["n"] == len(a)
    assert result["exact"] == 1.0
    assert result["within_5"] == 1.0
    assert abs(result["cohen_kappa"] - 1.0) < 1e-6, result


def test_agreement_opposite_ratings_gives_negative_kappa():
    """完全相反（a 与 100-a 对调，两评分者边际分布相同）：一致率 0，kappa 必须为负。"""
    _require_calibration()
    a = [95.0, 90.0, 15.0, 10.0, 95.0, 90.0, 10.0, 15.0]
    b = [100.0 - x for x in a]                # 95↔5、90↔10、15↔85、10↔90
    result = agreement(a, b)
    assert result["exact"] == 0.0, result
    assert result["within_5"] == 0.0, result
    assert result["cohen_kappa"] < 0, f"完全相反 kappa 应为负，实际 {result}"


def test_agreement_mismatched_length_raises_value_error():
    _require_calibration()
    with pytest.raises(ValueError):
        agreement([5.0, 4.0], [5.0])


def test_evaluate_returns_ok_field_and_flags_consistent_ratings():
    _require_calibration()
    records = [{"a": 95.0, "b": 95.0}, {"a": 75.0, "b": 75.0},
               {"a": 55.0, "b": 55.0}, {"a": 35.0, "b": 35.0}, {"a": 15.0, "b": 15.0}]
    out = evaluate(records)
    missing = [k for k in KAPPA_KEYS if k not in out]
    assert not missing, f"evaluate 应含 agreement 字段，缺 {missing}，实际 {out}"
    assert "ok" in out, f"evaluate 应返回 ok 字段，实际 {out}"
    assert out["ok"] is True, f"一致评分应 ok=True，实际 {out}"
    assert abs(out["cohen_kappa"] - 1.0) < 1e-6, out


def test_evaluate_ok_false_when_kappa_below_gate():
    _require_calibration()
    records = [{"a": 95.0, "b": 5.0}, {"a": 5.0, "b": 95.0},
               {"a": 95.0, "b": 5.0}, {"a": 5.0, "b": 95.0}]
    out = evaluate(records)
    assert out["cohen_kappa"] < 0.6, out
    assert out["ok"] is False, f"kappa<0.6 应 ok=False，实际 {out}"


def test_load_calibration_returns_list_of_dicts():
    _require_calibration()
    data = load_calibration()
    assert isinstance(data, list), f"应返回 list，实际 {type(data)}"
    assert all(isinstance(row, dict) for row in data), "list[dict] 契约：每项应为 dict"
