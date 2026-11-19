"""六帽审查：6 个独立 Agent + 蓝帽仲裁的分布式编排测试。"""

from __future__ import annotations

import os
import tempfile
import threading
from uuid import uuid4

from tripcraft.agents.review import SixHatsReview
from tripcraft.services.thread_service import ThreadService
from tripcraft.storage import Store

HAT_KEYS = {
    "六帽审查中的白帽": "白帽",
    "六帽审查中的黑帽": "黑帽",
    "六帽审查中的绿帽": "绿帽",
    "六帽审查中的黄帽": "黄帽",
    "六帽审查中的红帽": "红帽",
    "六帽审查中的蓝帽": "蓝帽",
}
HAT_ORDER = ["white", "black", "green", "yellow", "red", "blue"]


def system_of(messages) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")


def hat_of(system: str) -> str:
    # 只认各帽 system prompt 的首句；蓝帽 digest 里会出现别的帽名，不能按裸帽名匹配。
    for key, hat in HAT_KEYS.items():
        if key in system:
            return hat
    return ""


class HatLLM:
    """按 system 里的帽名返回不同结论；线程安全。"""

    def __init__(self, verdicts: dict | None = None, notes: dict | None = None) -> None:
        self.verdicts = dict(verdicts or {})
        self.notes = dict(notes or {})
        self.calls: list[str] = []
        self.systems: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def chat(self, messages, **kwargs):
        return "## 讲义\n\n预算要问清人均/总价和区间。"

    def chat_json(self, messages, **kwargs):
        system = system_of(messages)
        hat = hat_of(system)
        with self._lock:
            self.calls.append(hat)
            self.systems.append((hat, system))
        return {"verdict": self.verdicts.get(hat, "通过"),
                "note": self.notes.get(hat, f"{hat}结论")}


def test_six_hats_run_as_one_parallel_batch_then_blue():
    llm = HatLLM(notes={"白帽": "事实无误", "蓝帽": "综合通过"})
    out = SixHatsReview(llm).review("待审查材料", "参考资料")

    orchestra = out["orchestra"]
    trace = orchestra["trace"]
    assert [e["task_id"] for e in trace] == HAT_ORDER
    assert [e["agent"] for e in trace] == [f"review.{hid}" for hid in HAT_ORDER]
    assert len(trace) == 6

    # 批次：五帽同批，蓝帽单独第二批
    assert orchestra["batches"] == (
        ("white", "black", "green", "yellow", "red"), ("blue",))
    assert [e["meta"]["batch"] for e in trace] == [0, 0, 0, 0, 0, 1]
    assert all(e["ok"] for e in trace)

    # 蓝帽 task 显式依赖五帽，蓝帽系统提示里带着五帽 digest
    plan = SixHatsReview.plan()
    blue = next(task for task in plan.tasks if task.id == "blue")
    assert blue.agent == "review.blue"
    assert blue.depends_on == ("white", "black", "green", "yellow", "red")
    blue_system = next(system for hat, system in llm.systems if hat == "蓝帽")
    assert "白帽·事实核查：通过，事实无误" in blue_system, "蓝帽必须从黑板读到五帽结论"
    assert "红帽·个性适配：通过，红帽结论" in blue_system
    assert out["hats"][0]["note"] == "事实无误"

    assert [h["id"] for h in out["hats"]] == HAT_ORDER
    assert len(out["hats"]) == 6
    assert out["parallel"] is True and orchestra["parallel"] is True
    assert orchestra["run_id"]


def test_white_or_black_veto_overrides_blue_pass():
    for veto in ("白帽", "黑帽"):
        llm = HatLLM(verdicts={veto: "不通过", "蓝帽": "合格"})
        out = SixHatsReview(llm).review("待审查材料", "参考资料")
        assert out["critical_fail"] is True, f"{veto}不通过必须算硬门槛"
        assert out["verdict"] == "需修改", f"即使蓝帽说合格，{veto}不通过也必须需修改"
        assert out["hats"][5]["verdict"] == "合格", "蓝帽自己的结论保持原样"


def test_all_five_pass_and_blue_pass_yields_qualifying():
    llm = HatLLM(verdicts={"蓝帽": "合格"})
    out = SixHatsReview(llm).review("待审查材料", "参考资料")
    assert out["critical_fail"] is False
    assert out["verdict"] == "合格"


class BarrierLLM:
    """五顶帽子必须在同一批同时到达 Barrier；串行会超时失败。"""

    def __init__(self) -> None:
        self.barrier = threading.Barrier(5, timeout=5)
        self.calls: list[str] = []
        self.broken: list[str] = []
        self._lock = threading.Lock()

    def chat_json(self, messages, **kwargs):
        system = system_of(messages)
        hat = hat_of(system)
        with self._lock:
            self.calls.append(hat)
        if hat == "蓝帽":
            return {"verdict": "合格", "note": "蓝帽综合通过"}
        try:
            self.barrier.wait()
        except threading.BrokenBarrierError:
            with self._lock:
                self.broken.append(hat)
            raise
        return {"verdict": "通过", "note": "五帽同时到达"}


def test_five_hats_really_run_concurrently():
    llm = BarrierLLM()
    out = SixHatsReview(llm).review("待审查材料", "参考资料")
    assert llm.broken == [], "五顶帽子必须同批并行；串行会让 Barrier 超时（BrokenBarrier）"
    assert len(llm.calls) == 6
    assert out["verdict"] == "合格"
    assert out["orchestra"]["batches"] == (
        ("white", "black", "green", "yellow", "red"), ("blue",))


class FlakyLLM(HatLLM):
    """绿帽调用抛异常、红帽返回非 JSON 对象：两顶都要降级成「通过」。"""

    def chat_json(self, messages, **kwargs):
        system = system_of(messages)
        hat = hat_of(system)
        with self._lock:
            self.calls.append(hat)
        if hat == "绿帽":
            raise RuntimeError("green hat down")
        if hat == "红帽":
            return ["这不是 JSON 对象"]
        return {"verdict": "通过", "note": f"{hat}结论"}


def test_hat_exception_degrades_to_pass_and_review_still_returns():
    out = SixHatsReview(FlakyLLM()).review("待审查材料", "参考资料")
    by_id = {h["id"]: h for h in out["hats"]}

    assert by_id["green"]["verdict"] == "通过"
    assert by_id["green"]["note"] == ""
    assert by_id["red"]["verdict"] == "通过"
    assert by_id["white"]["verdict"] == "通过"

    assert out["critical_fail"] is False
    assert out["verdict"] == "合格"
    assert len(out["orchestra"]["trace"]) == 6
    assert all(event["ok"] for event in out["orchestra"]["trace"])


def test_generate_asset_exposes_review_orchestra():
    store = Store(os.path.join(tempfile.gettempdir(), f"hats_{uuid4().hex}.sqlite"))
    svc = ThreadService(store, HatLLM(verdicts={"蓝帽": "合格"}))
    asset = svc.generate_asset("u1", "C2.2", "lecture")

    review = asset["review"]
    assert len(review["hats"]) == 6
    assert review["verdict"] == "合格"
    orchestra = review["orchestra"]
    assert orchestra is not None
    assert orchestra["parallel"] is True
    assert [event["agent"] for event in orchestra["trace"]] == [
        f"review.{hid}" for hid in HAT_ORDER]
    assert [item["id"] for item in asset["pipeline"]][-6:] == HAT_ORDER
