"""已有 9 个技术点的独立验收（ver-07）。

依据 `.dsh-run/ppt-spec.md`「已有 9 点证据」一节，逐点按**真实接口**断言：
  1. 六帽：6 条 trace、批次 5+1
  2. 13 步：STEP_ORDER 长度 13、S0/S12 首尾
  3. 12 题画像：profiler 题库长度为 12
  4. 服务端题库：ThreadService 出题落库、判分只信服务端
  5. BIND：LearnerBrief 目标点来自短板
  6. MCP：tools/list 非空
  7. WS：/voice/dictation（含 SERVE_WEB 的 /api 前缀）可连
  8. BM25：retrieval 检索返回非空
  9. catalog：len(AGENT_SPECS) >= 25

任何一条失败都会在断言消息里写明实际值；实现不符时报告 file:line。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 1. 六帽


class _HatLLM:
    """最小 FakeLLM：所有帽子都返回「通过」，不联网。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat_json(self, messages, **kwargs):
        self.calls += 1
        return {"verdict": "通过", "note": "ok"}

    def chat(self, messages, **kwargs):
        return "## 讲义\n\n通过。"
        


def test_01_six_hats_trace_and_batches():
    from tripcraft.agents.review import SixHatsReview

    llm = _HatLLM()
    out = SixHatsReview(llm).review("待审查材料", "参考资料")

    orchestra = out["orchestra"]
    trace = orchestra["trace"]
    assert len(trace) == 6, f"六帽 trace 条数应为 6，实际 {len(trace)}"
    assert [e["task_id"] for e in trace] == ["white", "black", "green", "yellow", "red", "blue"]
    assert [e["agent"] for e in trace] == [f"review.{h}" for h in
                                           ("white", "black", "green", "yellow", "red", "blue")]
    assert orchestra["batches"] == (
        ("white", "black", "green", "yellow", "red"),
        ("blue",),
    ), f"批次应为五帽一批 + 蓝帽一批，实际 {orchestra['batches']!r}"
    assert len(out["hats"]) == 6
    assert all(e["ok"] for e in trace), f"存在失败帽子: {trace}"
    assert llm.calls == 6, f"六顶帽子应各调用模型一次，实际 {llm.calls} 次"


# ---------------------------------------------------------------- 2. 13 步


def test_02_thirteen_steps_s0_to_s12():
    from tripcraft.contracts.enums import STEP_ORDER

    values = [s.value for s in STEP_ORDER]
    assert len(values) == 13, f"STEP_ORDER 长度应为 13，实际 {len(values)}: {values}"
    assert values == [f"S{i}" for i in range(13)], f"13 步顺序不符: {values}"
    assert values[0] == "S0" and values[-1] == "S12"


# ---------------------------------------------------------------- 3. 12 题画像


def test_03_profile_quiz_has_twelve_questions():
    from tripcraft.agents.profiler import QUIZ, questions_public

    assert len(QUIZ) == 12, f"画像题库应为 12 题，实际 {len(QUIZ)}"
    ids = [q["id"] for q in QUIZ]
    assert ids == [f"Q{i}" for i in range(1, 13)], f"题目 ID 不连续: {ids}"
    public = questions_public()
    assert len(public) == 12
    assert all("level" not in opt for q in public for opt in q["options"]), (
        "题面下发不得带 level 权重"
    )


# ---------------------------------------------------------------- 4. 服务端题库


class _QuizLLM:
    """判档 + 出题共用：一次返回同时满足两种调用的字段。"""

    def chat_json(self, messages, **kwargs):
        return {"level": "M3", "score": 70, "reason": "测试",
                "type": "choice", "stem": "客户临时要求加一晚酒店，你怎么处理？",
                "options": ["A 先确认房态再答复", "B 直接答应", "C 让客户自己订", "D 不回复"],
                "answer": "A", "explain": "先确认资源再承诺", "difficulty": "L2"}


def test_04_thread_service_keeps_question_bank_server_side():
    from tripcraft.services.thread_service import (
        QuizQuestionMissing,
        ThreadService,
        strip_quiz_answers,
    )
    from tripcraft.storage import Store

    store = Store(os.path.join(tempfile.gettempdir(), f"ver07_quiz_{uuid4().hex}.sqlite"))
    svc = ThreadService(store, _QuizLLM())

    card = svc.pick_question("ver07_user", "C1.1")
    qid = card.get("question_id") or ""
    assert qid, f"下发的题卡必须带 question_id: {card}"

    # 下发投影剥掉答案
    for key in ("answer", "reference", "rubric_points", "explain"):
        assert key not in card, f"下发题卡泄露 {key}: {card}"
    assert card == strip_quiz_answers(card)

    # 服务端题库（quiz_question 表）能用 question_id 取回完整存档
    row = store.quiz_question(qid)
    assert row is not None, f"question_id={qid} 未落服务端题库"
    assert row.get("user_id") == "ver07_user"
    assert row.get("skill_point_id") == "C1.1"
    stored = json.loads(row.get("payload") or "{}")
    assert stored.get("answer") == "A", f"服务端存档答案丢失: {stored}"
    assert row.get("answer") == "A"

    # 判分只认服务端存档：客户端伪造 answer 键不影响判分
    forged = {"question_id": qid, "answer": "B", "stem": "伪造题干"}
    result = svc.submit_answer("ver07_user", "C1.1", forged, "A")
    assert result["correct"] is True, f"判分读了客户端内容: {result}"

    with pytest.raises(QuizQuestionMissing):
        svc.submit_answer("ver07_user", "C1.1", {}, "A")


# ---------------------------------------------------------------- 5. BIND 目标点来自短板


def test_05_learner_brief_targets_come_from_weak_top():
    from tripcraft.contracts.profile import AbilityProfile
    from tripcraft.contracts.skill_points import SKILL_POINTS
    from tripcraft.services.learner_brief import build_brief

    weak_ids = ["C1.1", "C2.1", "C3.1"]
    abilities = {sp.id: {"teach": 90.0, "real_v": 90.0} for sp in SKILL_POINTS}
    for point_id in weak_ids:
        abilities[point_id] = {"teach": 10.0, "real_v": 5.0}

    brief = build_brief(abilities)
    # 契约口径：目标点与 AbilityProfile.weak_top 同序（按 real_v 优先、低分在前）
    values = {sp.id: abilities[sp.id]["real_v"] for sp in SKILL_POINTS}
    expected = tuple(AbilityProfile(values).weak_top(3))
    assert len(brief.target_skill_points) == 3, brief.target_skill_points
    assert set(brief.target_skill_points) == set(weak_ids), (
        f"目标点应来自短板 {weak_ids}，实际 {brief.target_skill_points}")
    assert tuple(brief.target_skill_points) == expected
    for point_id in brief.target_skill_points:
        assert brief.mastery[point_id] <= 10.0
    assert brief.branch == "补救" and brief.level == 0, (
        f"最弱项 5 分应走补救，实际 {brief.branch}/{brief.level}")


# ---------------------------------------------------------------- 6. MCP


def test_06_mcp_tools_list_non_empty():
    from tripcraft.mcp.server import TOOLS, MCPServer

    resp = MCPServer({}).handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp and "result" in resp, f"tools/list 响应异常: {resp}"
    tools = resp["result"]["tools"]
    assert tools, "MCP tools/list 返回空列表"
    assert len(tools) == len(TOOLS)
    names = {t["name"] for t in tools}
    assert "weather.get" in names, f"缺少基础工具: {sorted(names)}"
    assert all("inputSchema" in t for t in tools)


# ---------------------------------------------------------------- 7. WS /voice/dictation


def test_07_voice_dictation_websocket_route_exists(monkeypatch):
    from fastapi.testclient import TestClient

    from tripcraft.api.app import create_app

    monkeypatch.delenv("SERVE_WEB", raising=False)
    client = TestClient(create_app())

    with client.websocket_connect("/voice/dictation") as ws:
        msg = ws.receive_json()
    assert msg.get("type") == "error" and "未登录" in str(msg.get("message")), (
        f"未登录应被拒绝，实际 {msg}")

    # SERVE_WEB 单端口部署：前端打的 /api 前缀由中间件剥掉后落到同一路由
    monkeypatch.setenv("SERVE_WEB", "1")
    with client.websocket_connect("/api/voice/dictation") as ws:
        msg = ws.receive_json()
    assert msg.get("type") == "error" and "未登录" in str(msg.get("message")), (
        f"/api/voice/dictation 未落到转写路由，实际 {msg}")


# ---------------------------------------------------------------- 8. BM25


def test_08_bm25_retrieval_returns_hits():
    from tripcraft.services.retrieval import Retriever

    knowledge_dir = ROOT / "data" / "knowledge"
    docs = sorted(knowledge_dir.glob("*.json")) if knowledge_dir.is_dir() else []
    if not docs:
        pytest.skip("data/knowledge 无知识数据，BM25 检索无输入")
    doc = json.loads(docs[0].read_text(encoding="utf-8"))
    sp = doc.get("skill_point_id") or ""
    name = doc.get("name") or ""
    assert sp and name, f"知识文件字段缺失: {docs[0]}"

    retriever = Retriever(knowledge_dir)
    hits = retriever.search(sp, name)
    assert hits, f"BM25 对 {sp}/{name!r} 无命中"
    assert any(score > 0 for _chunk, score in hits), f"命中全部 0 分: {hits}"
    rendered = retriever.render(sp, name)
    assert rendered["text"].strip(), "检索结果文本为空"


# ---------------------------------------------------------------- 9. catalog


def test_09_agent_catalog_has_at_least_25_specs():
    from tripcraft.orchestration.catalog import AGENT_SPECS

    assert len(AGENT_SPECS) >= 25, f"AGENT_SPECS 只注册了 {len(AGENT_SPECS)} 个"
    assert "review.white" in AGENT_SPECS
    assert "practice.team.risk" in AGENT_SPECS
