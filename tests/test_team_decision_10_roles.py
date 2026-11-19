"""P3 十类角色 + ARBITER：十票同批、权重和为 1、风控否决、离线 provider 分派。

契约来源：``.dsh-run/ppt-spec.md`` P3 段。离线，不联网。
覆盖：
1. ``TEAM_ROLES`` 恰 10 项、id 集合固定、每个 id 对应 ``practice.team.<id>``；
2. ``WEIGHTS`` 覆盖全部 id、全为正、和 ≈ 1.0；
3. ``decide()`` 一次跑 10 个 AgentTask：10 票、一层批次、size=10；
4. 风控「不接受」仍一票否决；
5. ``llm=None`` 路径可用（10 票全接受、score=1.0）；
6. 离线 provider（``scenario_service.ScenarioLLM``）命中全部 10 个角色的提示词。
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

import pytest

from tripcraft.services.practice_service import PracticeService
from tripcraft.services.scenario_service import ScenarioLLM, default_case_id, get_case
from tripcraft.services.team_decision import (
    ACCEPT_AT,
    CONDITIONAL_AT,
    RISK_AGENT,
    ROLE_DIMENSIONS,
    STANCES,
    TEAM_ROLES,
    WEIGHTS,
    TeamDecisionService,
    _system_prompt,
)
from tripcraft.storage import Store

ORDER = "9000000000000001"
INCIDENT = "inc-vehicle-1"
CONDITION = "换车费 400 由车队承担"
REQUIRED_IDS = (
    "customer", "planner", "dmo", "fleet", "guide",
    "driver", "hotel", "platform", "risk", "director",
)

ROLE_IDS = tuple(task_id for task_id, _agent_id, _role in TEAM_ROLES)
ROLES = tuple(role for _task_id, _agent_id, role in TEAM_ROLES)


class FakeLLM:
    """按 system 里的「角色名」分派立场；可选 Barrier 证明并发执行。"""

    def __init__(self, stances: dict, barrier: threading.Barrier | None = None) -> None:
        self.stances = stances
        self.barrier = barrier
        self.calls: list[str] = []

    def chat_json(self, messages, **kwargs):
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        self.calls.append(system)
        if self.barrier is not None:
            self.barrier.wait()      # 并发度不足时这里会超时并抛 BrokenBarrierError
        for role in ROLES:
            if f"「{role}」" in system:
                return dict(self.stances[role])
        raise AssertionError(f"system 缺少角色名：{system[:120]}")


def _accept_all() -> dict:
    return {role: {"stance": "接受", "reason": "同意"} for role in ROLES}


def make(stances: dict | None = None, *, llm: bool = True,
         barrier: threading.Barrier | None = None, model=None):
    store = Store(os.path.join(tempfile.gettempdir(), f"td10_{uuid4().hex}.sqlite"))
    practice = PracticeService(store)
    store.upsert_order(ORDER, "u1", "客户 A", "江苏", "正常", 5)
    store.add_incident(INCIDENT, ORDER, "VEHICLE_BREAKDOWN", "S11", "车辆故障",
                       "dm-司机", "dm-司机", "司机", "车辆抛锚，需要换车",
                       ["C6.1"], "vehicle_breakdown")
    if model is None and llm:
        model = FakeLLM(stances or _accept_all(), barrier)
    return TeamDecisionService(store, practice=practice, llm=model), store


# ---------- 1. 角色表与权重 ----------

def test_team_roles_is_ten_with_expected_ids():
    assert isinstance(TEAM_ROLES, tuple)
    assert len(TEAM_ROLES) == 10
    assert ROLE_IDS == REQUIRED_IDS
    assert all(agent_id == f"practice.team.{task_id}"
               for task_id, agent_id, _role in TEAM_ROLES)
    assert len(set(ROLES)) == 10, f"角色名必须唯一：{ROLES}"


def test_role_names_do_not_contain_each_other():
    """角色名互不为子串：否则按名字分派的模型会给两票同一个立场。"""
    for role in ROLES:
        for other in ROLES:
            if role != other:
                assert role not in other, f"角色名 {role!r} 是 {other!r} 的子串"


def test_weights_cover_all_ids_and_sum_to_one():
    assert set(WEIGHTS) == set(ROLE_IDS)
    assert all(weight > 0 for weight in WEIGHTS.values())
    assert sum(WEIGHTS.values()) == pytest.approx(1.0, abs=1e-9)


# ---------- 2. decide()：10 票同批 ----------

def test_decide_returns_ten_votes_in_one_batch():
    svc, _store = make()
    out = svc.decide(ORDER, INCIDENT, "就近换车，行程不变")

    assert len(out["votes"]) == 10
    assert [vote["role"] for vote in out["votes"]] == list(ROLES)
    assert [vote["agent"] for vote in out["votes"]] == [f"practice.team.{rid}" for rid in ROLE_IDS]
    assert all(vote["ok"] for vote in out["votes"])
    assert len(out["orchestra"]["trace"]) == 10
    assert len(out["orchestra"]["batches"]) == 1
    assert out["orchestra"]["batches"][0]["size"] == 10
    assert out["orchestra"]["batches"][0]["parallel"] is True
    assert out["orchestra"]["parallel"] is True
    assert out["verdict"] == "接受"
    assert out["rules"]["score"] == pytest.approx(1.0)
    # 返回结构不变
    assert set(out) == {"decision_id", "order_id", "incident_id", "verdict", "conditions",
                        "votes", "rules", "orchestra", "evidence_id"}
    assert set(out["rules"]) == {"veto", "veto_by", "score", "weights", "thresholds"}
    assert out["rules"]["thresholds"] == {"accept": ACCEPT_AT, "conditional": CONDITIONAL_AT}


def test_ten_roles_really_run_in_parallel():
    barrier = threading.Barrier(len(TEAM_ROLES), timeout=5)
    svc, _store = make(barrier=barrier)
    out = svc.decide(ORDER, INCIDENT, "就近换车")

    assert [vote["ok"] for vote in out["votes"]] == [True] * len(TEAM_ROLES)
    assert out["orchestra"]["batches"][0]["size"] == len(TEAM_ROLES)


# ---------- 3. 风控一票否决 ----------

def test_risk_reject_vetoes_all_ten():
    stances = _accept_all()
    stances["风控合规"] = {"stance": "不接受", "reason": "车辆无营运资质"}
    svc, _store = make(stances)
    out = svc.decide(ORDER, INCIDENT, "换一辆车继续行程")

    assert out["verdict"] == "驳回"
    assert out["rules"]["veto"] is True
    assert out["rules"]["veto_by"] == RISK_AGENT
    assert all(vote["stance"] == "接受" for vote in out["votes"] if vote["role"] != "风控合规")
    assert len(out["votes"]) == 10


# ---------- 4. llm=None 路径 ----------

def test_without_llm_returns_ten_deterministic_accepts():
    svc, _store = make(llm=False)
    out = svc.decide(ORDER, INCIDENT, "就近换车")

    assert len(out["votes"]) == 10
    assert out["verdict"] == "接受"
    assert out["rules"]["score"] == pytest.approx(1.0)
    assert all(vote["stance"] == "接受" for vote in out["votes"])
    assert all("未配置模型" in vote["reason"] for vote in out["votes"])
    assert len(out["orchestra"]["batches"]) == 1
    assert out["orchestra"]["batches"][0]["size"] == 10


# ---------- 5. 离线 provider 命中 10 个角色 ----------

def _offline_provider() -> ScenarioLLM:
    case_dir = Path(__file__).resolve().parents[1] / "data" / "scenario" / "standard_case.json"
    assert case_dir.exists(), f"缺少标准案例资料: {case_dir}"
    return ScenarioLLM(get_case(default_case_id()))


def test_offline_provider_dispatches_all_ten_roles():
    provider = _offline_provider()
    for task_id, agent_id, role in TEAM_ROLES:
        system = _system_prompt(role, agent_id, ROLE_DIMENSIONS[task_id])
        assert "团队决策" in system
        assert role in system and agent_id in system
        data = provider.chat_json([
            {"role": "system", "content": system},
            {"role": "user", "content": f"订单号：{ORDER}\n事件：车辆故障（VEHICLE_BREAKDOWN）"},
        ])
        assert isinstance(data, dict), f"{role} 未返回 JSON 对象"
        assert data["stance"] in STANCES, f"{role} 立场无效: {data['stance']!r}"
    assert provider.audit()["by_handler"]["_team_decision"] == 10


def test_offline_provider_full_decide_runs_ten_roles():
    svc, _store = make(model=_offline_provider())
    out = svc.decide(ORDER, INCIDENT, "就近换车，行程不变")

    assert len(out["votes"]) == 10
    assert all(vote["ok"] for vote in out["votes"])
    assert out["orchestra"]["batches"][0]["size"] == 10
    # 资源方可行性口径的四个角色给「有条件接受」（权重 .15+.12+.10+.08=.45）→ 0.6*.45+1*.55
    assert out["rules"]["score"] == pytest.approx(0.82)
    assert out["verdict"] == "有条件接受"
    assert CONDITION in out["conditions"]
    assert out["rules"]["veto"] is False
