"""P12 独立验收：沙盒参数与可复现随机（ver-07）。

契约来源：`.dsh-run/ppt-spec.md` 的 P12 一节。

被测接口（全部按契约调用，不读实现私有名）：
    SandboxParams(seed, difficulty, stress)
    default_params(difficulty="L1", seed=0) -> SandboxParams
    from_profile(profile, seed=0) -> SandboxParams
    rng(seed) -> random.Random
    sample(params, key) -> float（0-1，同 seed/key 同值）

只断言契约行为：L1–L5 的 stress 单调、0-1；同 seed 同值；不同 seed 不同值；
from_profile 对空画像 / 真画像 / 鸭子类型都不崩。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import random

import pytest

from tripcraft.contracts.profile import AbilityProfile
from tripcraft.services.sandbox_params import (
    SandboxParams,
    default_params,
    from_profile,
    rng,
    sample,
)

LEVELS = ("L1", "L2", "L3", "L4", "L5")


def _assert_stress_valid(params: SandboxParams) -> None:
    assert isinstance(params.stress, dict) and params.stress, "stress 必须是非空 dict"
    for key, value in params.stress.items():
        assert isinstance(key, str), f"stress 键必须是字符串: {key!r}"
        assert 0.0 <= float(value) <= 1.0, f"{key}={value!r} 超出 0-1"


def test_default_params_covers_l1_to_l5_and_stress_in_unit_range():
    for level in LEVELS:
        params = default_params(level)
        assert isinstance(params, SandboxParams)
        assert params.difficulty == level
        assert isinstance(params.seed, int)
        _assert_stress_valid(params)

    # 契约签名默认值：difficulty="L1", seed=0
    base = default_params()
    assert base.difficulty == "L1" and base.seed == 0

    # 契约写的是 @dataclass(frozen=True)
    with pytest.raises(FrozenInstanceError):
        base.seed = 1  # type: ignore[misc]


def test_stress_monotonic_from_l1_to_l5():
    """难度档升高时每个旋钮不降，且相邻两档至少有一个旋钮真的变大。"""
    previous: dict[str, float] | None = None
    for level in LEVELS:
        stress = {k: float(v) for k, v in default_params(level).stress.items()}
        if previous is not None:
            for key, value in stress.items():
                assert key in previous, f"L1–L5 的 stress 键集合必须一致，缺少 {key}"
                assert value >= previous[key], (
                    f"{level} 的 {key}={value} 低于上一档 {previous[key]}，stress 不单调"
                )
            assert any(stress[k] > previous[k] for k in stress), (
                f"{level} 相对上一档所有旋钮都没变，难度档没有起作用"
            )
        previous = stress


def test_same_seed_and_key_are_stable():
    key = "customer.name"
    for seed in (0, 7, 20261119):
        first = sample(default_params("L3", seed=seed), key)
        # 重新构造 params（不同对象）后仍必须同值
        second = sample(default_params("L3", seed=seed), key)
        assert first == second, f"seed={seed} 同 key 两次取值不一致: {first} != {second}"
        assert 0.0 <= first <= 1.0, f"sample 返回越界: {first}"


def test_different_seeds_produce_different_values():
    key = "customer.name"
    values = {seed: sample(default_params("L3", seed=seed), key) for seed in (1, 2, 3, 4, 5)}
    assert len(set(values.values())) > 1, f"不同 seed 得到相同随机值: {values}"


def test_rng_is_reproducible_random_instance():
    a = rng(123)
    b = rng(123)
    assert isinstance(a, random.Random), "rng 必须返回 random.Random"
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]
    # 与 random.Random(seed) 的原生序列一致：契约写的是「只返回 Random(seed)」
    assert rng(123).random() == random.Random(123).random()


def test_from_profile_does_not_crash_on_empty_or_real_profiles():
    empty_variants = [None, {}, AbilityProfile()]
    for profile in empty_variants:
        params = from_profile(profile)
        assert isinstance(params, SandboxParams)
        assert params.difficulty in LEVELS
        assert params.seed == 0
        _assert_stress_valid(params)

    real = AbilityProfile({"C1.1": 12.0, "C2.1": 30.0, "C3.1": 88.0})
    params = from_profile(real, seed=42)
    assert params.seed == 42
    assert params.difficulty in LEVELS
    _assert_stress_valid(params)


def test_from_profile_accepts_weak_top_duck_type():
    """契约写「按 weak_top/difficulty 生成」，只暴露 weak_top 的对象也不能崩。"""

    class WeakTopOnly:
        def weak_top(self, n: int = 3) -> list[str]:
            return ["C1.1", "C2.1", "C3.1"]

    params = from_profile(WeakTopOnly(), seed=3)
    assert isinstance(params, SandboxParams)
    assert params.difficulty in LEVELS
    _assert_stress_valid(params)


def test_weaker_profile_yields_higher_or_equal_difficulty_and_stress():
    strong = AbilityProfile({sp_id: 95.0 for sp_id in ("C1.1", "C2.1", "C3.1", "C4.1")})
    weak = AbilityProfile({sp_id: 10.0 for sp_id in ("C1.1", "C2.1", "C3.1", "C4.1")})

    strong_params = from_profile(strong, seed=11)
    weak_params = from_profile(weak, seed=11)

    assert LEVELS.index(weak_params.difficulty) >= LEVELS.index(strong_params.difficulty), (
        f"弱画像难度 {weak_params.difficulty} 低于强画像 {strong_params.difficulty}"
    )
    for key, value in strong_params.stress.items():
        assert weak_params.stress[key] >= value, (
            f"弱画像 {key}={weak_params.stress[key]} 低于强画像 {value}"
        )


def test_sample_rejects_nothing_and_uses_key_namespace():
    params = default_params("L5", seed=99)
    keys = ("a", "b", "c", "order_id", "金额")
    values = [sample(params, key) for key in keys]
    assert all(0.0 <= v <= 1.0 for v in values)
    assert len(set(values)) == len(values), f"不同 key 不应全部同值: {dict(zip(keys, values))}"
