"""线程服务测试（mock LLM，不联网、不花钱）。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.services.thread_service import ThreadService
from tripcraft.storage import Store


class FakeLLM:
    def chat(self, messages, **kwargs):
        return "## 讲解\n\n预算是硬约束，要问清**人均/总价**和区间。\n\n<div class=\"refs\">参考来源：Rubric C2.2</div>"

    def chat_json(self, messages, **kwargs):
        system = messages[0]["content"] if messages else ""
        if "评分专家" in system:
            return {"level": "M3", "score": 75, "reason": "问到人均但没核区间"}
        if "实战出题老师" in system or "出题" in system:
            return {"type": "choice", "stem": "客户说性价比高，你应该？",
                    "options": ["直接做方案", "追问人均/总价与区间", "报最低价", "先加微信"],
                    "answer": "B", "explain": "预算属硬约束"}
        if "实战评判老师" in system or "评判" in system:
            return {"correct": True, "reason": "覆盖了预算三问"}
        return {}


def make():
    p = os.path.join(tempfile.gettempdir(), f"tc_{uuid4().hex}.sqlite")
    store = Store(p)
    store.set_ability("u1", "C2.2", teach=60, real_v=40)
    store.upsert_order("9000000000000001", "u1", "客户 A", "江苏", "正常", 1)
    return ThreadService(store, FakeLLM()), store


def test_context_has_six_sources():
    svc, _ = make()
    ctx = svc.build_context("u1", "C2.2")
    text = ctx.render()
    assert "Rubric" in text
    assert "知识点基座" in text or ctx.knowledge == {}
    assert "画像掌握度" in text
    assert "实战证据" in text
    src = ctx.sources()
    assert any(s.startswith("rubric:") for s in src)
    assert any(s.startswith("thread:") for s in src)
    assert any(s.startswith("quiz:") for s in src)


def test_reply_saves_message_and_evidence():
    svc, store = make()
    r = svc.reply("u1", "C2.2", "预算这块怎么问？")
    assert "预算" in r["content"]
    assert r["evidence"], "回复必须带来源"
    msgs = store.messages("thread:C2.2")
    assert [m["role"] for m in msgs] == ["user", "ai"]


def test_generate_asset_and_list():
    svc, store = make()
    a = svc.generate_asset("u1", "C2.2", "lecture")
    assert a["type"] == "lecture" and a["content"]
    assert store.assets("u1", "C2.2"), "资产应已入库"


def test_pick_question_follows_judged_level():
    svc, _ = make()
    q = svc.pick_question("u1", "C2.2")
    assert q["type"] == "choice"
    assert q["judged_level"] == "M3"
    assert q["difficulty"] == "L3", "M3 应对应 L3 难度（L1–L5 五档）"


def test_submit_answer_updates_mastery():
    svc, store = make()
    q = svc.pick_question("u1", "C2.2")
    r = svc.submit_answer("u1", "C2.2", q, "B")
    assert r["correct"] is True
    assert r["teach"] > 60, "答对应提升教学掌握度"
    assert len(store.attempts("u1", "C2.2")) == 1


def test_submit_wrong_triggers_reteach():
    svc, store = make()
    q = svc.pick_question("u1", "C2.2")
    r = svc.submit_answer("u1", "C2.2", q, "A")
    assert r["correct"] is False
    assert r["reteach"] is True
    assert store.memories("u1"), "答错应写入记忆"