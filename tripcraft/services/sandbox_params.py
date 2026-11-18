"""沙盒参数与可复现随机 —— 难度档 → 压力旋钮，seed + key → 稳定随机数（P12）。

口径（P12 契约、PRD 第 7 / 20 章）：
- 一个沙盒 = ``seed`` + ``difficulty``（L1–L5）+ 四个 0-1 压力旋钮；
- 同 seed / 同 key 的随机值**跨进程**稳定：用 hashlib 派生种子，不用内置 hash；
- 画像越弱（弱项越多）→ 难度档越高、压力旋钮越高。

难度档用纯字符串表驱动，不依赖 ``DifficultyLevel`` 枚举：L5 由别处并行补进枚举，
本模块对 "L5" 直接查表；遇到表外难度（如未来 L6）按数字夹到最近档，不抛异常。
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

DIFFICULTY_LEVELS: tuple[str, ...] = ("L1", "L2", "L3", "L4", "L5")

# 四个压力旋钮，全部 0-1（0=最松，1=最紧）
STRESS_KEYS: tuple[str, ...] = (
    "time_pressure",
    "budget_pressure",
    "info_gap",
    "event_rate",
)

# 难度档 → 压力旋钮基准值（每个键随 L1→L5 严格递增）
STRESS_TABLE: dict[str, dict[str, float]] = {
    "L1": {"time_pressure": 0.15, "budget_pressure": 0.20, "info_gap": 0.10, "event_rate": 0.10},
    "L2": {"time_pressure": 0.35, "budget_pressure": 0.40, "info_gap": 0.30, "event_rate": 0.30},
    "L3": {"time_pressure": 0.55, "budget_pressure": 0.55, "info_gap": 0.50, "event_rate": 0.45},
    "L4": {"time_pressure": 0.75, "budget_pressure": 0.70, "info_gap": 0.70, "event_rate": 0.65},
    "L5": {"time_pressure": 0.90, "budget_pressure": 0.85, "info_gap": 0.90, "event_rate": 0.80},
}

# 弱项门槛：能力值 < 70 视为弱项（与 contracts/profile 的 M1+M2 口径一致）
WEAK_THRESHOLD = 70.0
# 弱项个数计满 5 个即视为「最弱画像」，用于弱项绝对数量的归一化
WEAK_SATURATION = 5


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def normalize_difficulty(difficulty: object) -> str:
    """把 "l5" / 5 / DifficultyLevel.L4 之类统一成表内键 "L1".."L5"。"""
    raw = getattr(difficulty, "value", difficulty)
    if isinstance(raw, bool):
        raw = int(raw)
    key = f"L{raw}" if isinstance(raw, int) else str(raw).strip().upper()
    if key in STRESS_TABLE:
        return key
    digits = "".join(ch for ch in key if ch.isdigit())
    if digits:
        n = max(1, min(len(DIFFICULTY_LEVELS), int(digits)))
        return DIFFICULTY_LEVELS[n - 1]
    return DIFFICULTY_LEVELS[0]


@dataclass(frozen=True)
class SandboxParams:
    """一次沙盒运行的确定性参数：seed + 难度 + 压力旋钮。"""

    seed: int
    difficulty: str
    stress: dict[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(self, "difficulty", normalize_difficulty(self.difficulty))
        object.__setattr__(
            self, "stress", {str(k): _clamp01(v) for k, v in self.stress.items()}
        )


def default_params(difficulty: str = "L1", seed: int = 0) -> SandboxParams:
    """按难度档取表内基准压力（不依赖任何画像）。"""
    key = normalize_difficulty(difficulty)
    return SandboxParams(seed=seed, difficulty=key, stress=dict(STRESS_TABLE[key]))


# ---------------------------------------------------------------- 画像 → 参数

def _ability_values(profile: object) -> dict[str, float]:
    """从画像里抽 {技能点: 0-100}，兼容 AbilityProfile / LearnerProfile / dict / 鸭子类型。"""
    if profile is None:
        return {}

    raw: dict | None = None
    if isinstance(profile, dict):
        for name in ("abilities", "params"):
            if isinstance(profile.get(name), dict):
                raw = profile[name]
                break
        if raw is None:
            raw = {
                k: v for k, v in profile.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
    else:
        for name in ("params", "abilities"):
            cand = getattr(profile, name, None)
            if isinstance(cand, dict):
                raw = cand
                break
        if raw is None:
            fn = getattr(profile, "values", None)
            if callable(fn):
                got = fn()
                if isinstance(got, dict):
                    raw = got

    values: dict[str, float] = {}
    for point_id, value in (raw or {}).items():
        try:
            num = float(getattr(value, "value", value))
        except (TypeError, ValueError):
            continue
        values[str(point_id)] = max(0.0, min(100.0, num))
    return values


def _weak_severity(values: dict[str, float], weak_count: int | None = None) -> float:
    """弱项严重度 0-1：有力值按「占比 + 个数」算；只有 weak_top/weak_tags 时按个数算。"""
    if values:
        weak = sum(1 for v in values.values() if v < WEAK_THRESHOLD)
        ratio = weak / len(values)
        count_score = min(weak / WEAK_SATURATION, 1.0)
        return 0.5 * ratio + 0.5 * count_score
    if weak_count:
        return min(weak_count / WEAK_SATURATION, 1.0)
    return 0.0


def _declared_weak_count(profile: object) -> int | None:
    """没有能力明细时，退而用 weak_top() / weak_tags 的弱项个数。"""
    fn = getattr(profile, "weak_top", None)
    if callable(fn):
        got: object = None
        for args in ((WEAK_SATURATION,), ()):
            try:
                got = fn(*args)
                break
            except TypeError:
                continue
        if isinstance(got, (list, tuple)):
            return len(got)
    tags = profile.get("weak_tags") if isinstance(profile, dict) else getattr(profile, "weak_tags", None)
    if isinstance(tags, (list, tuple)):
        return len(tags)
    return None


def _declared_level(profile: object) -> str | None:
    """画像自带难度（只认 L1–L5 直系写法）；作为下限，不把画像降难。"""
    for name in ("difficulty", "level"):
        cand = profile.get(name) if isinstance(profile, dict) else getattr(profile, name, None)
        if cand is None:
            continue
        key = normalize_difficulty(cand)
        if key in STRESS_TABLE:
            return key
    return None


def from_profile(profile: object, seed: int = 0) -> SandboxParams:
    """按画像的弱项严重度定难度与压力；空画像/未知结构回落 L1，不抛异常。"""
    values = _ability_values(profile)
    weak_count = None if values else _declared_weak_count(profile)
    severity = _weak_severity(values, weak_count)

    computed = min(len(DIFFICULTY_LEVELS) - 1, int(severity * len(DIFFICULTY_LEVELS)))
    declared = _declared_level(profile)
    if declared is not None:
        computed = max(computed, DIFFICULTY_LEVELS.index(declared))
    difficulty = DIFFICULTY_LEVELS[computed]

    # 弱项越严重，同一档内的旋钮再往上抬一点（基准值 > 0，故单调不降）
    factor = 0.9 + 0.2 * severity
    stress = {k: round(_clamp01(STRESS_TABLE[difficulty][k] * factor), 4) for k in STRESS_KEYS}
    return SandboxParams(seed=seed, difficulty=difficulty, stress=stress)


# ---------------------------------------------------------------- 可复现随机

def rng(seed: int) -> random.Random:
    """只返回 Random(seed)：同一 seed 序列可复现。"""
    return random.Random(seed)


def _stable_seed(seed: int, key: str) -> int:
    """seed + key → 64 位整数种子；sha256 派生，跨进程稳定。"""
    material = f"{int(seed)}\x1f{key}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def sample(params: SandboxParams, key: str) -> float:
    """0-1 稳定随机值：同 params.seed + key 必同值，与进程无关。"""
    return rng(_stable_seed(params.seed, str(key))).random()
