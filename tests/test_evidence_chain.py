"""资源方数据 → 证据链 → 评分 Agent 的贯通测试（离线，不联网）。

回答两个问题：
1. 学员在资源方群里的对话，会不会进证据链？（会，且落点按群类型对齐 13 步）
2. 评分 Agent 看不看得到资源方的客观口径？（看得到，但只作核对参照，不算学员证据）
"""

import os
import tempfile
from uuid import uuid4

from fastapi.testclient import TestClient

import tripcraft.api.app as app_mod
from tripcraft.agents.llm import LLMError
from tripcraft.agents.scorer import ScoringAgent
from tripcraft.services.practice_service import GROUP_STEP, PracticeService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.storage import Store

ORDER = "9000000000000004"      # 浙江 · 阶段 4


class CaptureLLM:
    """不联网的假模型：只记录它收到的提示词。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        return "收到"

    def chat_json(self, messages, **kwargs):
        self.calls.append(messages)
        return {"scores": []}


def _temp_db() -> str:
    path = os.path.join(tempfile.gettempdir(), f"ev_{uuid4().hex}.sqlite")
    os.environ["TRIPCRAFT_DB"] = path
    return path


def _client(monkeypatch):
    """临时库 + 无可用模型（走模板兜底），确保离线可跑。"""

    class NoKey:
        def __init__(self, *a, **k):
            raise LLMError("测试环境故意不接模型")

    monkeypatch.setattr(app_mod, "DeepSeekClient", NoKey)
    return TestClient(app_mod.create_app())


def _add(c, order_id, *kinds):
    """按真实顺序加联系人（新规则：没加联系人的群不能发言）。"""
    for k in kinds:
        r = c.post("/practice/im/contacts", json={"order_id": order_id, "kind": k})
        assert r.status_code == 200, r.text


def _room(c, kind):
    """新模型：没有自动建的"酒店沟通群"，只有加了好友之后的单聊。"""
    groups = c.get("/practice/im/sessions", params={"order_id": ORDER}).json()
    return next(g for g in groups if g["code"] == f"dm-{kind}")


def test_group_chat_becomes_evidence(monkeypatch):
    path = _temp_db()
    c = _client(monkeypatch)
    groups = c.get("/practice/im/sessions", params={"order_id": ORDER}).json()
    assert [g["code"] for g in groups] == ["hub"]      # 只给一个资源大群，别的群自己拉
    _add(c, ORDER, "地接社", "酒店")
    hotel = _room(c, "酒店")
    assert hotel["name"] and hotel["kind"] == "酒店"
    c.post(f"/practice/im/sessions/{hotel['session_id']}/messages",
           json={"sender": "我", "role": "me", "content": "这三天四星房什么价？"})

    ev = Store(path).evidence(ORDER)
    kinds = [(e["kind"], e["step"]) for e in ev]
    assert ("im", "S4") in kinds                     # 酒店群 → S4 资源询价
    last = ev[-1]
    assert "开元销售陈" in last["text"] or "酒店" in last["text"]
    assert "我：" in last["text"] and "540" in last["text"]   # 学员原话 + 资源方口径

    # 非学员消息（系统/对方）不进证据，避免自说自话
    before = len(Store(path).evidence(ORDER))
    c.post(f"/practice/im/sessions/{hotel['session_id']}/messages",
           json={"sender": "酒店·李", "role": "other", "content": "好的"})
    assert len(Store(path).evidence(ORDER)) == before


def test_group_step_map_covers_the_new_session_kinds(monkeypatch):
    """聊天的 13 步落点要覆盖新模型的会话类型（大群 / 单聊 / 自建群）。"""
    path = _temp_db()
    c = _client(monkeypatch)
    _add(c, ORDER, "地接社", "酒店", "客户")
    groups = c.get("/practice/im/sessions", params={"order_id": ORDER}).json()
    codes = {g["code"] for g in groups}
    assert "hub" in codes and "dm-酒店" in codes and "dm-客户" in codes
    for code in codes:
        assert GROUP_STEP[code].startswith("S"), code


def test_toolbox_quote_uses_same_facts_as_group(monkeypatch):
    path = _temp_db()
    _client(monkeypatch)
    store = Store(path)
    svc = SupplierService(store)
    via_ask = svc.ask(ORDER, "酒店", "四星什么价？")
    assert via_ask["quote"]["summary"] == svc.facts(ORDER, "酒店")["summary"]
    assert "540" in via_ask["content"]


def test_scoring_agent_receives_resource_facts():
    llm = CaptureLLM()
    agent = ScoringAgent(llm)
    from tripcraft.contracts.rubric import RUBRICS
    agent.score("【call】学员：您好", [RUBRICS["C1.1"]], facts="酒店：四星 540/间/晚（可用性 紧张）")
    payload = llm.calls[0][1]["content"]
    assert "resource_facts" in payload and "540" in payload
    assert "不是学员证据" in payload or "不能单独作为给分依据" in payload


def test_score_order_passes_facts_into_prompt(monkeypatch):
    path = _temp_db()
    c = _client(monkeypatch)
    _add(c, ORDER, "地接社", "酒店")
    hotel = _room(c, "酒店")
    c.post(f"/practice/im/sessions/{hotel['session_id']}/messages",
           json={"sender": "我", "role": "me", "content": "四星和用车什么价？"})

    store = Store(path)
    practice = PracticeService(store)
    # 本单目标技能点要先被覆盖才进评分：A 型补交付物证据，B 型补触发 + 反应
    for sp_id in practice.build_plan(ORDER):
        t = store.target(ORDER, sp_id)
        if not t:
            continue
        if t["checkpoint"] == "B":
            practice.mark_trigger(ORDER, sp_id, t["step"])
            practice.mark_reacted(ORDER, sp_id)
        else:
            practice.record_evidence(ORDER, "行程方案", f"覆盖 {sp_id}", step=t["step"])

    facts = practice.supplier_facts_text(ORDER)
    assert "酒店：" in facts and "540" in facts       # 本单资源方口径

    llm = CaptureLLM()
    practice.score_order(ORDER, llm)
    assert llm.calls                                  # 确实把材料送进了评分模型
    payload = llm.calls[0][1]["content"]
    assert "resource_facts" in payload and "540" in payload


def test_incident_shows_up_in_scoring_facts(monkeypatch):
    path = _temp_db()
    _client(monkeypatch)
    store = Store(path)
    practice = PracticeService(store)
    from tripcraft.services.director_service import DirectorService
    from tripcraft.services.supplier_service import SupplierService
    sup = SupplierService(store, practice=practice)
    sup.add_contact(ORDER, "地接社")
    sup.add_contact(ORDER, "导游")          # 司导单聊得先在，事件才有地方落
    fired = DirectorService(store, practice=practice, llm=None).emit(ORDER, "pre_trip")
    assert fired and fired["injected"], "已经加了导游，车辆故障事件应该注入"
    facts = practice.supplier_facts_text(ORDER)
    assert "事件·车辆故障" in facts and "换车" in facts
