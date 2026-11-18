"""实训行中事件「团队决策」服务与 API 测试（离线，不联网）。

覆盖：十类角色同批并行、仲裁规则（一票否决 / 加权阈值）、llm=None 确定性路径、
证据与事件落库、POST/GET 端点。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from uuid import uuid4

import pytest

from tripcraft.services.practice_service import PracticeService
from tripcraft.services.team_decision import TEAM_ROLES, TeamDecisionService
from tripcraft.storage import Store

ORDER = "9000000000000001"
INCIDENT = "inc-vehicle-1"

ROLES = tuple(role for _task_id, _agent_id, role in TEAM_ROLES)
CONDITION = "换车费 400 由车队承担"

# 默认立场：资源方可行性（定制师，0.15）与车队可行性（0.10）各给「有条件接受」，
# 条件权重合计 0.25 → 加权分 = 1 - 0.4 * 0.25 = 0.9（保持既有 score 断言不变）。
DEFAULT_STANCES = {role: {"stance": "接受", "reason": "同意"} for role in ROLES}
DEFAULT_STANCES["资源方可行性"] = {"stance": "有条件接受", "reason": "可换车，但要写明费用承担",
                                   "condition": CONDITION}
DEFAULT_STANCES["车队可行性"] = {"stance": "有条件接受", "reason": "可换车，但要写明费用承担",
                                 "condition": CONDITION}

ALL_ACCEPT = {role: {"stance": "接受", "reason": "同意"} for role in ROLES}


class FakeLLM:
    """按 system 里的角色名分派立场；可选 Barrier 证明并发执行。

    只匹配「角色名」的精确形式（提示词里用「」包住）：多个角色共用同一个离线评审
    口径（如「资源方可行性」），子串匹配会互相吃掉立场。
    """

    def __init__(self, stances: dict | None = None, barrier: threading.Barrier | None = None) -> None:
        self.stances = stances or DEFAULT_STANCES
        self.barrier = barrier
        self.calls: list[str] = []

    def chat_json(self, messages, **kwargs):
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        self.calls.append(system)
        if self.barrier is not None:
            self.barrier.wait()          # 串行执行时这里会超时并抛 BrokenBarrierError
        for role in ROLES:
            if f"「{role}」" in system:
                return dict(self.stances[role])
        raise AssertionError(f"system 缺少角色名：{system[:120]}")


def make(stances: dict | None = None, *, llm: bool = True,
         barrier: threading.Barrier | None = None):
    store = Store(os.path.join(tempfile.gettempdir(), f"td_{uuid4().hex}.sqlite"))
    practice = PracticeService(store)
    store.upsert_order(ORDER, "u1", "客户 A", "江苏", "正常", 5)
    store.add_incident(INCIDENT, ORDER, "VEHICLE_BREAKDOWN", "S11", "车辆故障",
                       "dm-司机", "dm-司机", "司机", "车辆抛锚，需要换车",
                       ["C6.1"], "vehicle_breakdown")
    model = FakeLLM(stances, barrier) if llm else None
    return TeamDecisionService(store, practice=practice, llm=model), store


def test_ten_roles_parallel_batch_and_conditional_merged():
    svc, _store = make()
    out = svc.decide(ORDER, INCIDENT, "就近换车，行程不变")

    assert out["verdict"] == "有条件接受"
    assert CONDITION in out["conditions"]
    assert len(out["votes"]) == len(TEAM_ROLES)
    assert [vote["role"] for vote in out["votes"]] == list(ROLES)
    assert len(out["orchestra"]["trace"]) == len(TEAM_ROLES)
    assert len(out["orchestra"]["batches"]) == 1
    assert out["orchestra"]["batches"][0]["size"] == len(TEAM_ROLES)
    supplier = next(v for v in out["votes"] if v["role"] == "资源方可行性")
    assert supplier["stance"] == "有条件接受"
    assert supplier["condition"] == CONDITION


def test_risk_reject_vetoes_everything():
    stances = {**ALL_ACCEPT, "风控合规": {"stance": "不接受", "reason": "车辆无营运资质"}}
    svc, _store = make(stances)
    out = svc.decide(ORDER, INCIDENT, "换一辆车继续行程")

    assert out["verdict"] == "驳回"
    assert out["rules"]["veto"] is True
    assert out["rules"]["veto_by"] == "practice.team.risk"
    # 其余九票全接受也不能翻案
    assert all(vote["stance"] == "接受" for vote in out["votes"] if vote["role"] != "风控合规")


def test_all_accept_and_score_is_one():
    svc, _store = make(ALL_ACCEPT)
    out = svc.decide(ORDER, INCIDENT, "就近换车")

    assert out["verdict"] == "接受"
    assert out["rules"]["score"] == pytest.approx(1.0)
    assert out["conditions"] == []


def test_roles_really_run_in_parallel():
    barrier = threading.Barrier(len(TEAM_ROLES), timeout=5)
    svc, _store = make(barrier=barrier)
    out = svc.decide(ORDER, INCIDENT, "就近换车")

    assert [vote["ok"] for vote in out["votes"]] == [True] * len(TEAM_ROLES)
    assert out["orchestra"]["parallel"] is True
    assert out["rules"]["score"] == pytest.approx(0.9)


def test_without_llm_uses_deterministic_rule():
    svc, _store = make(llm=False)
    out = svc.decide(ORDER, INCIDENT, "就近换车")

    assert out["verdict"] == "接受"
    assert out["rules"]["score"] == pytest.approx(1.0)
    assert all(vote["stance"] == "接受" for vote in out["votes"])
    assert all("未配置模型" in vote["reason"] for vote in out["votes"])


def test_evidence_and_event_are_persisted():
    svc, store = make()
    out = svc.decide(ORDER, INCIDENT, "就近换车")

    incidents = store.incidents(ORDER)
    step = next(i["step"] for i in incidents if i["incident_id"] == INCIDENT)
    evidence = [e for e in store.evidence(ORDER) if e["kind"] == "团队决策"]
    assert len(evidence) == 1
    assert evidence[0]["step"] == step
    assert "车辆故障" in evidence[0]["text"]
    assert out["verdict"] in evidence[0]["text"]
    assert "score=" in evidence[0]["text"]
    for role in ROLES:
        assert role in evidence[0]["text"]
    assert out["evidence_id"] == str(evidence[0]["evidence_id"])

    events = [e for e in store.events(ORDER) if e["type"] == "team_decision"]
    assert len(events) == 1
    payload = json.loads(events[0]["payload"])
    assert payload["decision_id"] == out["decision_id"]
    assert payload["votes"] == out["votes"]


def test_api_post_and_get_decision(auth_client):
    client, headers = auth_client
    ctx = client.app.state.ctx
    user_id = client.get("/auth/session", headers=headers).json()["user_id"]

    order_id = f"api-{uuid4().hex[:10]}"
    incident_id = "inc-api-1"
    ctx.store.upsert_order(order_id, user_id, "客户 A", "江苏", "正常", 5)
    ctx.store.add_incident(incident_id, order_id, "VEHICLE_BREAKDOWN", "S11", "车辆故障",
                           "dm-司机", "dm-司机", "司机", "车辆抛锚，需要换车",
                           ["C6.1"], "vehicle_breakdown")
    ctx.llm_holder["client"] = FakeLLM()

    posted = client.post(
        f"/practice/orders/{order_id}/incidents/{incident_id}/decision",
        json={"plan": "就近换车，行程不变"}, headers=headers)
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["order_id"] == order_id
    assert body["verdict"] == "有条件接受"
    assert body["rules"]["veto"] is False

    got = client.get(
        f"/practice/orders/{order_id}/incidents/{incident_id}/decision", headers=headers)
    assert got.status_code == 200
    assert got.json()["decision_id"] == body["decision_id"]

    # 事件不存在 → 400；订单不存在 → 404；从未决策过的事件 → {"decision": null}
    missing_incident = client.post(
        f"/practice/orders/{order_id}/incidents/inc-missing/decision",
        json={"plan": ""}, headers=headers)
    assert missing_incident.status_code == 400
    missing_order = client.post(
        "/practice/orders/no-such-order/incidents/inc-missing/decision",
        json={"plan": ""}, headers=headers)
    assert missing_order.status_code == 404
    no_decision = client.get(
        f"/practice/orders/{order_id}/incidents/inc-none/decision", headers=headers)
    assert no_decision.json() == {"decision": None}
