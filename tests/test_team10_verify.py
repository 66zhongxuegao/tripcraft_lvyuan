"""P3 十类角色 + ARBITER 独立交叉验收（ver-02，只读实现）。

契约来源：``.dsh-run/ppt-spec.md`` P3 段。
覆盖：
1. ``TEAM_ROLES`` 恰为 10 项，id 集合 = customer/planner/dmo/fleet/guide/driver/
   hotel/platform/risk/director；
2. ``WEIGHTS`` 覆盖全部 id 且和 ≈ 1.0；
3. 目录 ``practice.team.<id>`` 10 个 AgentSpec 绑定齐全；
4. ``decide()`` 同批 10 票、batches 一层 size=10、trace 10 条；
5. 风控「不接受」→ 驳回 + veto_by=practice.team.risk；
6. ``llm=None`` 确定性路径（全接受、score≈1.0）；
7. ARBITER 阈值仍为 .7/.45；
8. 既有 ``tests/test_practice_team_decision.py`` 的写死 5 票断言已改为
   ``len(TEAM_ROLES)`` 且未删除。
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from tripcraft.orchestration.catalog import AGENT_SPECS
from tripcraft.services.practice_service import PracticeService
from tripcraft.services.team_decision import (
    ACCEPT_AT,
    CONDITIONAL_AT,
    RISK_AGENT,
    TEAM_ROLES,
    WEIGHTS,
    TeamDecisionService,
)
from tripcraft.storage import Store

REQUIRED_IDS = (
    "customer", "planner", "dmo", "fleet", "guide",
    "driver", "hotel", "platform", "risk", "director",
)
ORDER = "9000000000000001"
INCIDENT = "inc-vehicle-1"


# ---------- TEAM_ROLES 条目形状适配（契约只规定「10 项元组 + id 集合」） ----------

def _entry_id(entry) -> str:
    if isinstance(entry, str):
        return entry
    for attr in ("task_id", "id"):
        value = getattr(entry, attr, None)
        if value:
            return str(value)
    return str(entry[0])


def _entry_agent(entry) -> str:
    if isinstance(entry, str):
        return f"practice.team.{entry}"
    for attr in ("agent_id", "agent"):
        value = getattr(entry, attr, None)
        if value:
            return str(value)
    try:
        if len(entry) > 1 and str(entry[1]).startswith("practice.team."):
            return str(entry[1])
    except TypeError:
        pass
    return f"practice.team.{_entry_id(entry)}"


def _entry_role(entry) -> str:
    if isinstance(entry, str):
        return entry
    for attr in ("role", "role_name", "label", "name"):
        value = getattr(entry, attr, None)
        if value:
            return str(value)
    try:
        if len(entry) > 2:
            return str(entry[2])
        if len(entry) == 2 and not str(entry[1]).startswith("practice.team."):
            return str(entry[1])
    except TypeError:
        pass
    return _entry_id(entry)


def _entries() -> list:
    return list(TEAM_ROLES)


def _ids() -> list[str]:
    return [_entry_id(entry) for entry in _entries()]


# ---------- 假模型：按 system 提示词里的「角色名」分派 ----------

class FakeTeamLLM:
    def __init__(self, stances: dict[str, dict]) -> None:
        self.stances = stances
        self.aliases: dict[str, str] = {}
        for entry in _entries():
            role = _entry_role(entry)
            if role in stances:
                self.aliases.setdefault(_entry_agent(entry), role)
                self.aliases.setdefault(_entry_id(entry), role)
        self.calls: list[str] = []

    def chat_json(self, messages, **kwargs):
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        self.calls.append(system)
        # 先精确匹配「角色名」（实现用「」包住角色名），再退回子串匹配；
        # 长名优先，避免「风控」与「风控合规」这类前缀互吃。
        for role in sorted(self.stances, key=len, reverse=True):
            if f"「{role}」" in system or role in system:
                return dict(self.stances[role])
        # 角色名没进提示词时按 agent_id / task_id 兜底识别（同属契约可见的稳定 id）。
        for alias in sorted(self.aliases, key=len, reverse=True):
            if alias and (f"「{alias}」" in system or alias in system):
                return dict(self.stances[self.aliases[alias]])
        raise AssertionError(f"system 提示词缺少任何已知角色名：{system[:160]}")


def _accept_all() -> dict[str, dict]:
    return {_entry_role(entry): {"stance": "接受", "reason": "同意"} for entry in _entries()}


def make(stances: dict[str, dict] | None = None, *, llm: bool = True):
    store = Store(os.path.join(tempfile.gettempdir(), f"td10_{uuid4().hex}.sqlite"))
    practice = PracticeService(store)
    store.upsert_order(ORDER, "u1", "客户 A", "江苏", "正常", 5)
    store.add_incident(INCIDENT, ORDER, "VEHICLE_BREAKDOWN", "S11", "车辆故障",
                       "dm-司机", "dm-司机", "司机", "车辆抛锚，需要换车",
                       ["C6.1"], "vehicle_breakdown")
    model = FakeTeamLLM(stances or _accept_all()) if llm else None
    return TeamDecisionService(store, practice=practice, llm=model), store


# ---------- 1. 角色表 ----------

def test_team_roles_is_ten_with_required_id_set():
    assert isinstance(TEAM_ROLES, tuple), "契约要求 TEAM_ROLES 为元组"
    assert len(TEAM_ROLES) == 10, (
        f"P3 未实现：TEAM_ROLES 只有 {len(TEAM_ROLES)} 项，期望 10 项；"
        "见 tripcraft/services/team_decision.py:31"
    )
    ids = _ids()
    assert len(set(ids)) == 10, f"TEAM_ROLES id 有重复：{ids}"
    assert set(ids) == set(REQUIRED_IDS), (
        f"id 集合不符：实际 {sorted(ids)}，期望 {sorted(REQUIRED_IDS)}"
    )


# ---------- 2. 权重 ----------

def test_weights_cover_ids_and_sum_to_one():
    ids = set(_ids())
    assert set(WEIGHTS) == ids, (
        f"WEIGHTS 键与 TEAM_ROLES id 不一致：多 {sorted(set(WEIGHTS) - ids)}，"
        f"缺 {sorted(ids - set(WEIGHTS))}"
    )
    assert all(weight > 0 for weight in WEIGHTS.values()), "权重必须为正"
    assert sum(WEIGHTS.values()) == pytest.approx(1.0, abs=1e-6), (
        f"权重和 {sum(WEIGHTS.values())} ≠ 1.0"
    )


# ---------- 3. 目录绑定 ----------

def test_catalog_binds_all_ten_practice_team_agents():
    missing = [rid for rid in REQUIRED_IDS if f"practice.team.{rid}" not in AGENT_SPECS]
    assert not missing, (
        f"catalog 缺少 practice.team.* 绑定：{missing}；"
        "见 tripcraft/orchestration/catalog.py:50"
    )
    for rid in REQUIRED_IDS:
        spec = AGENT_SPECS[f"practice.team.{rid}"]
        assert spec.section == "practice", f"{spec.id} 的 section={spec.section!r}，期望 practice"
    for entry in _entries():
        agent_id = _entry_agent(entry)
        assert agent_id in AGENT_SPECS, (
            f"TEAM_ROLES 的 agent {agent_id!r} 未在 catalog 绑定"
        )


# ---------- 4. decide()：10 票同批 ----------

def test_decide_returns_ten_votes_in_one_batch():
    svc, _store = make()
    out = svc.decide(ORDER, INCIDENT, "就近换车，行程不变")

    assert len(out["votes"]) == 10, f"votes 只有 {len(out['votes'])} 条，期望 10"
    assert [vote["role"] for vote in out["votes"]] == [_entry_role(e) for e in _entries()]
    assert all(vote["ok"] for vote in out["votes"]), "10 个角色都应成功返回"
    assert len(out["orchestra"]["trace"]) == 10
    assert len(out["orchestra"]["batches"]) == 1, "10 个角色应同批执行，批次只有一层"
    assert out["orchestra"]["batches"][0]["size"] == 10
    assert out["orchestra"]["batches"][0]["parallel"] is True
    assert out["verdict"] == "接受"
    assert out["rules"]["score"] == pytest.approx(1.0)
    assert out["rules"]["veto"] is False


# ---------- 5. 风控一票否决 ----------

def test_risk_reject_vetoes_all_ten():
    stances = _accept_all()
    risk_role = next((_entry_role(entry) for entry in _entries()
                      if _entry_agent(entry) == RISK_AGENT), None)
    if risk_role is None:
        pytest.fail(f"P3 未实现：TEAM_ROLES 中没有 agent={RISK_AGENT} 的风控角色")
    stances[risk_role] = {"stance": "不接受", "reason": "车辆无营运资质"}
    svc, _store = make(stances)
    out = svc.decide(ORDER, INCIDENT, "换一辆车继续行程")

    assert len(out["votes"]) == 10
    assert out["verdict"] == "驳回"
    assert out["rules"]["veto"] is True
    assert out["rules"]["veto_by"] == "practice.team.risk"
    assert all(vote["stance"] == "接受"
               for vote in out["votes"] if vote["role"] != risk_role), "其余 9 票全接受也不能翻案"


def test_condition_keeps_verdict_conditional_even_if_score_high():
    role_by_id = {_entry_id(entry): _entry_role(entry) for entry in _entries()}
    if "planner" not in role_by_id:
        pytest.fail("P3 未实现：TEAM_ROLES 缺少 planner 角色")
    stances = _accept_all()
    stances[role_by_id["planner"]] = {
        "stance": "有条件接受", "reason": "需写明费用承担", "condition": "换车费 400 由车队承担",
    }
    svc, _store = make(stances)
    out = svc.decide(ORDER, INCIDENT, "就近换车")

    assert len(out["votes"]) == 10
    assert out["rules"]["score"] >= ACCEPT_AT
    assert out["verdict"] == "有条件接受"
    assert "换车费 400 由车队承担" in out["conditions"]


# ---------- 6. llm=None 确定性路径 ----------

def test_without_llm_is_deterministic_ten_accepts():
    svc, _store = make(llm=False)
    out = svc.decide(ORDER, INCIDENT, "就近换车")

    assert len(out["votes"]) == 10
    assert out["verdict"] == "接受"
    assert out["rules"]["score"] == pytest.approx(1.0)
    assert all(vote["stance"] == "接受" for vote in out["votes"])
    assert all("未配置模型" in vote["reason"] for vote in out["votes"])


# ---------- 7. ARBITER 阈值 ----------

def test_arbiter_thresholds_unchanged():
    assert ACCEPT_AT == pytest.approx(0.7)
    assert CONDITIONAL_AT == pytest.approx(0.45)


# ---------- 8. 既有测试已改 5 票断言 ----------

def test_existing_five_vote_assertions_use_len_team_roles():
    path = Path(__file__).with_name("test_practice_team_decision.py")
    text = path.read_text(encoding="utf-8")

    assert re.search(r"\btest_", text), "既有团队决策测试文件被删空"
    assert "len(TEAM_ROLES)" in text, (
        "tests/test_practice_team_decision.py 未改为 len(TEAM_ROLES)"
    )
    hardcoded = [
        pattern for pattern in (
            r'len\(out\["votes"\]\)\s*==\s*5',
            r'len\(out\["orchestra"\]\["trace"\]\)\s*==\s*5',
            r'"size"\]\s*==\s*5',
            r'Barrier\(5',
            r'\[True\]\s*\*\s*5',
        )
        if re.search(pattern, text)
    ]
    assert not hardcoded, f"既有测试仍写死 5 票断言：{hardcoded}"
