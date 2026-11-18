"""发布门控与材料版本测试（临时库，不联网、不花钱）。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.services.asset_gate import AssetGate
from tripcraft.storage import Store

HATS = (
    ("white", "白帽·事实核查"),
    ("black", "黑帽·逻辑审计"),
    ("green", "绿帽·创意转化"),
    ("yellow", "黄帽·激励引导"),
    ("red", "红帽·个性适配"),
)


def make_store() -> Store:
    """每个测试一个临时库文件，互不污染，也不碰开发库。"""
    p = os.path.join(tempfile.gettempdir(), f"tc_gate_{uuid4().hex}.sqlite")
    return Store(p)


def review(*, white: str = "通过", black: str = "通过", verdict: str = "合格",
           critical_fail: bool = False) -> dict:
    """构造与 agents/review.py 返回结构一致的六帽审查结果。"""
    hats = [{"id": hid, "name": name, "verdict": white if hid == "white" else black if hid == "black" else "通过",
             "note": f"{name}意见"} for hid, name in HATS]
    hats.append({"id": "blue", "name": "蓝帽·质量总控", "verdict": verdict, "note": "蓝帽综合意见"})
    return {"verdict": verdict, "critical_fail": critical_fail, "hats": hats,
            "orchestra": {}, "parallel": True}


def test_pass_publish_versions_increment():
    store = make_store()
    gate = AssetGate(store)

    first = gate.publish("u1", "C2.2", "lecture", "第一版正文", review())
    second = gate.publish("u1", "C2.2", "lecture", "第二版正文", review())

    assert first["passed"] is True and first["version"] == 1
    assert second["passed"] is True and second["version"] == 2
    assert first["asset_id"] == second["asset_id"] != ""
    assert [v["version"] for v in second["versions"]] == [1, 2]
    assert store.asset(first["asset_id"])["content"] == "第二版正文"
    assert len(store.assets("u1", "C2.2")) == 1, "同一资产重复发布不新增 asset 行"


def test_reject_does_not_write():
    store = make_store()
    gate = AssetGate(store)

    r = gate.publish("u1", "C2.2", "lecture", "未过审正文", review(white="不通过", verdict="需修改"))

    assert r["passed"] is False and r["version"] == 0 and r["asset_id"] == ""
    assert store.assets("u1") == [], "未通过不得写 asset"
    assert store.asset_versions("asset_u1_C2.2_lecture") == [], "未通过不得写 asset_version"


def test_version_history_keeps_each_content():
    store = make_store()
    gate = AssetGate(store)

    gate.publish("u1", "C2.2", "lecture", "版本一原文", review())
    r = gate.publish("u1", "C2.2", "lecture", "版本二原文", review())

    versions = store.asset_versions(r["asset_id"])
    assert [v["version"] for v in versions] == [1, 2]
    assert [v["content"] for v in versions] == ["版本一原文", "版本二原文"]
    assert all(v["created_at"] for v in versions), "版本历史要留时间戳"


def test_add_asset_version_starts_at_one_and_increments():
    store = make_store()

    assert store.add_asset_version("asset_x", "甲") == 1
    assert store.add_asset_version("asset_x", "乙") == 2
    assert [v["version"] for v in store.asset_versions("asset_x")] == [1, 2]
    assert [v["content"] for v in store.asset_versions("asset_x")] == ["甲", "乙"]


def test_evaluate_critical_fail_branch():
    gate = AssetGate(make_store())

    ok = gate.evaluate(review())
    assert ok["passed"] is True and ok["critical_fail"] is False

    bad_black = gate.evaluate(review(black="不通过", verdict="需修改"))
    assert bad_black["passed"] is False and bad_black["critical_fail"] is True
    assert "黑帽" in bad_black["reason"]

    flagged = gate.evaluate(review(critical_fail=True))
    assert flagged["passed"] is False and flagged["critical_fail"] is True

    blue_reject = gate.evaluate(review(verdict="需修改"))
    assert blue_reject["passed"] is False and blue_reject["critical_fail"] is False
