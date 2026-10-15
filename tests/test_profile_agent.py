"""画像 Agent：初始画像测评 + 动态刷新（D-066）。

离线可跑：把 DeepSeekClient 换成抛 LLMError 的替身，画像 Agent 走确定性模板兜底。
"""

import os
import tempfile
from uuid import uuid4

from fastapi.testclient import TestClient

from tripcraft.agents import profiler as P
from tripcraft.agents.llm import LLMError
from tripcraft.api import app as app_mod


def _client(monkeypatch) -> TestClient:
    path = os.path.join(tempfile.gettempdir(), f"pf_{uuid4().hex}.sqlite")
    os.environ["TRIPCRAFT_DB"] = path

    class NoKey:
        def __init__(self, *a, **k):
            raise LLMError("测试环境故意不接模型")

    monkeypatch.setattr(app_mod, "DeepSeekClient", NoKey)
    return TestClient(app_mod.create_app())


def _answers(level_by_dim: dict[str, int] | None = None) -> list[dict]:
    """按「每个维度想要几档」构造一份完整作答。"""
    level_by_dim = level_by_dim or {}
    out = []
    for q in P.QUIZ:
        want = level_by_dim.get(q["dim"], 3)
        opt = min(q["options"], key=lambda o: abs(o["level"] - want))   # 没有该档就取最接近的
        out.append({"qid": q["id"], "key": opt["key"]})
    return out


# ---------------- 纯函数：题面与打分 ----------------

def test_quiz_public_hides_levels():
    qs = P.questions_public()
    assert len(qs) == len(P.QUIZ) == 12
    assert {q["dim"] for q in qs} == set(P.DIM_ORDER), "8 个维度都要覆盖到"
    for q in qs:
        assert q["options"]
        assert all("level" not in o for o in q["options"]), "权重不能下发到前端"


def test_score_answers_is_deterministic_and_bounded():
    a = _answers({"C1": 4, "C4": 0, "C8": 0})
    s1 = P.score_answers(a)
    assert s1 == P.score_answers(a), "同一份作答必须可复算"
    assert set(s1) == set(P.DIM_ORDER)
    assert s1["C1"] == 95.0, "顶格封顶 95，不给满分"
    assert s1["C4"] == 20.0, "全不会也给 20 保底"
    # 未知题号 / 未知选项一律忽略，不炸
    assert P.score_answers([{"qid": "NOPE", "key": "z"}]) == P.score_answers([])


def test_dim_comments_accepts_both_shapes():
    assert P.dim_comments([{"dim": "C1", "comment": "x"}]) == {"C1": "x"}
    # 模型有时把整句写进 key
    assert P.dim_comments({"C2 需求洞察：教学75 vs 实战0": ""}) == {"C2": "教学75 vs 实战0"}


# ---------------- 接口：初始画像 ----------------

def test_initial_assessment_only_for_new_users(monkeypatch):
    c = _client(monkeypatch)
    uid = "u-" + uuid4().hex[:8]

    assert c.get(f"/profiles/{uid}/intake").json()["can_assess"] is True

    r = c.post("/profile/assessment", json={"user_id": uid, "answers": _answers({"C1": 3})})
    assert r.status_code == 200
    body = r.json()
    assert body["scores"]["C1"] == 75.0
    assert body["report"]["summary"], "兜底模板也要有定性描述"
    assert len(body["report"]["suggestions"]) >= 3

    after = c.get(f"/profiles/{uid}/intake").json()
    assert after["can_assess"] is False and after["has_report"] is True

    again = c.post("/profile/assessment", json={"user_id": uid, "answers": _answers({})})
    assert again.status_code == 409, "已有画像数据的不再开放初始画像"


def test_assessment_requires_all_questions(monkeypatch):
    c = _client(monkeypatch)
    uid = "u-" + uuid4().hex[:8]
    r = c.post("/profile/assessment", json={"user_id": uid, "answers": _answers({})[:5]})
    assert r.status_code == 400


def test_assessment_writes_teach_for_every_skill_point(monkeypatch):
    c = _client(monkeypatch)
    uid = "u-" + uuid4().hex[:8]
    c.post("/profile/assessment", json={"user_id": uid, "answers": _answers({"C3": 4})})

    m = c.get("/learn/map", params={"user_id": uid}).json()
    pts = [p for d in m["dimensions"] for p in d["points"]]
    assert len(pts) == 61
    assert all(p["teach"] > 0 for p in pts), "每个技能点都要拿到基线，画像不能有空洞"
    assert all(p["real"] == 0 for p in pts), "初始画像只写教学侧，实战侧留空"
    c3 = next(d for d in m["dimensions"] if d["id"] == "C3")
    assert c3["teach"] == 95.0


def test_suggestions_point_to_a_real_skill_point(monkeypatch):
    c = _client(monkeypatch)
    uid = "u-" + uuid4().hex[:8]
    rep = c.post("/profile/assessment",
                 json={"user_id": uid, "answers": _answers({"C8": 0})}).json()["report"]
    ids = {p["id"] for d in c.get("/learn/map", params={"user_id": uid}).json()["dimensions"]
           for p in d["points"]}
    assert rep["focus"][0] == "C8", "最弱的一维要排在最前"
    for s in rep["suggestions"]:
        assert s["skill_point_id"] in ids
        assert s["why"] and s["how"], "每条建议都要说清为什么、怎么练"


# ---------------- 接口：更新画像 ----------------

def test_refresh_needs_data_then_marks_kind(monkeypatch):
    c = _client(monkeypatch)
    uid = "u-" + uuid4().hex[:8]
    assert c.post(f"/profiles/{uid}/refresh").status_code == 409

    c.post("/profile/assessment", json={"user_id": uid, "answers": _answers({"C6": 0})})
    rep = c.post(f"/profiles/{uid}/refresh").json()["report"]
    assert rep["kind"] == "refresh"
    assert len(rep["suggestions"]) >= 3
    assert len(rep["dimensions"]) == 8, "8 维都要有点评"


def test_report_endpoint_returns_latest(monkeypatch):
    c = _client(monkeypatch)
    uid = "u-" + uuid4().hex[:8]
    assert c.get(f"/profiles/{uid}/report").json()["report"] == {}
    c.post("/profile/assessment", json={"user_id": uid, "answers": _answers({})})
    assert c.get(f"/profiles/{uid}/report").json()["report"]["kind"] == "initial"
    c.post(f"/profiles/{uid}/refresh")
    assert c.get(f"/profiles/{uid}/report").json()["report"]["kind"] == "refresh"
