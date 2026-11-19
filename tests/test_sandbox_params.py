"""P12 沙盒参数与可复现随机 —— 契约、画像联动、跨进程稳定。"""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from tripcraft.contracts.profile import AbilityProfile, LearnerProfile
from tripcraft.contracts.skill_points import SKILL_POINTS
from tripcraft.services.sandbox_params import (
    DIFFICULTY_LEVELS,
    STRESS_KEYS,
    SandboxParams,
    default_params,
    from_profile,
    normalize_difficulty,
    rng,
    sample,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_IDS = [sp.id for sp in SKILL_POINTS[:8]]
LEVEL_INDEX = {level: i for i, level in enumerate(DIFFICULTY_LEVELS)}


# ---------------------------------------------------------------- default_params

def test_default_params_covers_all_levels_with_four_knobs():
    assert set(DIFFICULTY_LEVELS) == {"L1", "L2", "L3", "L4", "L5"}
    for level in DIFFICULTY_LEVELS:
        params = default_params(level)
        assert isinstance(params, SandboxParams)
        assert params.difficulty == level
        assert set(STRESS_KEYS) <= set(params.stress)
        for key in STRESS_KEYS:
            assert 0.0 <= params.stress[key] <= 1.0, (level, key, params.stress[key])


def test_default_params_defaults_to_l1_seed_zero():
    params = default_params()
    assert params.difficulty == "L1"
    assert params.seed == 0
    assert params == default_params("L1", seed=0)


def test_stress_strictly_increases_with_difficulty():
    rows = [default_params(level).stress for level in DIFFICULTY_LEVELS]
    for key in STRESS_KEYS:
        vals = [row[key] for row in rows]
        assert vals == sorted(vals), (key, vals)
        assert len(set(vals)) == len(vals), (key, vals)


def test_difficulty_accepts_l5_string():
    params = default_params("L5", seed=3)
    assert params.difficulty == "L5"
    assert params.stress["time_pressure"] > default_params("L4").stress["time_pressure"]
    assert normalize_difficulty("l5") == "L5"
    manual = SandboxParams(seed=1, difficulty="L5", stress={"time_pressure": 0.5})
    assert manual.difficulty == "L5"


def test_unknown_difficulty_falls_back_instead_of_raising():
    assert normalize_difficulty("nightmare") == "L1"
    assert normalize_difficulty(6) == "L5"
    assert default_params("L9", seed=2).difficulty == "L5"


def test_manual_construction_clamps_stress_and_coerces_seed():
    params = SandboxParams(seed="5", difficulty="l4", stress={"time_pressure": 2, "info_gap": -1})
    assert params.seed == 5
    assert params.difficulty == "L4"
    assert params.stress["time_pressure"] == 1.0
    assert params.stress["info_gap"] == 0.0


# ---------------------------------------------------------------- rng / sample

def test_rng_same_seed_same_sequence():
    first, second = rng(42), rng(42)
    assert isinstance(first, random.Random)
    assert [first.random() for _ in range(5)] == [second.random() for _ in range(5)]
    assert rng(42).random() != rng(43).random()


def test_sample_is_stable_for_same_seed_and_key():
    params = default_params("L3", seed=7)
    value = sample(params, "customer_name")
    assert sample(params, "customer_name") == value
    assert sample(default_params("L5", seed=7), "customer_name") == value, "sample 只由 seed+key 决定"
    assert 0.0 <= value < 1.0


def test_sample_differs_by_key_and_by_seed():
    params = default_params("L3", seed=7)
    by_key = [sample(params, key) for key in ("customer_name", "city", "budget", "companions")]
    assert len(set(by_key)) == len(by_key), by_key
    by_seed = [sample(default_params("L3", seed=seed), "customer_name") for seed in range(10)]
    assert len(set(by_seed)) == len(by_seed), by_seed


def test_sample_is_stable_across_processes():
    code = (
        "from tripcraft.services.sandbox_params import default_params, sample;"
        "print(repr(sample(default_params('L5', seed=12345), 'customer_name')))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    child = float(proc.stdout.strip())
    assert child == sample(default_params("L5", seed=12345), "customer_name")


# ---------------------------------------------------------------- from_profile

def test_from_profile_more_weak_points_means_higher_difficulty_and_stress():
    strong = AbilityProfile({sid: 92.0 for sid in SKILL_IDS})
    partly_weak = AbilityProfile({**{sid: 92.0 for sid in SKILL_IDS[:-2]},
                                  SKILL_IDS[-2]: 40.0, SKILL_IDS[-1]: 55.0})
    all_weak = AbilityProfile({sid: 45.0 for sid in SKILL_IDS})

    p_strong = from_profile(strong)
    p_partly = from_profile(partly_weak)
    p_all = from_profile(all_weak)

    assert LEVEL_INDEX[p_strong.difficulty] < LEVEL_INDEX[p_partly.difficulty]
    assert LEVEL_INDEX[p_partly.difficulty] < LEVEL_INDEX[p_all.difficulty]
    for key in STRESS_KEYS:
        assert p_strong.stress[key] < p_partly.stress[key] <= p_all.stress[key]


def test_from_profile_accepts_actual_profile_shapes_without_crashing():
    learner = LearnerProfile(user_id="u1")
    learner.set_ability(SKILL_IDS[0], 55.0)
    shapes = [
        AbilityProfile({SKILL_IDS[0]: 60.0}),
        learner,
        {SKILL_IDS[0]: 45.0, SKILL_IDS[1]: 95.0},
        {"abilities": {SKILL_IDS[0]: 45.0, SKILL_IDS[1]: 95.0}},
        {"params": {SKILL_IDS[0]: 45.0}},
        SimpleNamespace(abilities={SKILL_IDS[0]: 45.0},
                        weak_top=lambda n: [SKILL_IDS[0]][:n]),
        None,
    ]
    for profile in shapes:
        params = from_profile(profile, seed=9)
        assert isinstance(params, SandboxParams)
        assert params.seed == 9
        assert params.difficulty in DIFFICULTY_LEVELS
        assert set(STRESS_KEYS) <= set(params.stress)
        for key in STRESS_KEYS:
            assert 0.0 <= params.stress[key] <= 1.0


def test_from_profile_falls_back_to_weak_top_and_weak_tags():
    one_weak = SimpleNamespace(weak_top=lambda n: [SKILL_IDS[0]])
    three_weak = SimpleNamespace(weak_top=lambda n: list(SKILL_IDS[:3]))
    p_one = from_profile(one_weak)
    p_three = from_profile(three_weak)
    assert LEVEL_INDEX[p_one.difficulty] < LEVEL_INDEX[p_three.difficulty]
    for key in STRESS_KEYS:
        assert 0.0 <= p_one.stress[key] < p_three.stress[key] <= 1.0

    p_tags = from_profile({"weak_tags": list(SKILL_IDS[:3])})
    assert p_tags.difficulty == p_three.difficulty


def test_from_profile_empty_profile_falls_back_to_l1():
    for profile in (AbilityProfile({}), LearnerProfile(user_id="empty")):
        params = from_profile(profile)
        assert params.difficulty == "L1"
        assert all(0.0 <= params.stress[key] <= 1.0 for key in STRESS_KEYS)


def test_from_profile_never_downgrades_declared_difficulty():
    strong_values = {sid: 95.0 for sid in SKILL_IDS[:5]}
    assert from_profile({**strong_values, "difficulty": "L4"}).difficulty == "L4"
    learner = LearnerProfile(user_id="u2", level="L3")
    for sid, value in strong_values.items():
        learner.set_ability(sid, value)
    assert from_profile(learner).difficulty == "L3"
