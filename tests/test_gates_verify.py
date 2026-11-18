"""独立交叉验证：P8 沙盒检查点 + P9 发布门控与材料版本。

契约来源：`.dsh-run/ppt-spec.md` P8（第 96-105 行）、P9（第 107-111 行）。
本文件只做验收断言，不改实现。

P8（tripcraft/engine/checkpoints.py）：
  - CP1/CP2/CP3 三个检查点，step 分别绑定 StepId 的 S1/S6/S11；
  - checkpoints_for_step("S1") 命中 CP1；
  - evaluate 在证据命中全部关键词时通过，缺项时列出 missed（顺序保持）；
  - evaluate 遇到未知 checkpoint_id 抛 ValueError。

P9（tripcraft/services/asset_gate.py + tripcraft/storage/db.py）：
  - review 白帽/黑帽任一「不通过」→ evaluate passed=False、critical_fail=True；
  - 不通过的 publish 不落库，version 为 0；
  - 两个通过 review 连续 publish → version 1、2；
  - asset_versions(asset_id) 返回 2 条且内容对应；
  - db 层 add_asset_version 递增版本号（asset_version 表）。
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest

from tripcraft.contracts.enums import StepId
from tripcraft.engine.checkpoints import (
    CHECKPOINTS,
    Checkpoint,
    checkpoints_for_step,
    evaluate,
)
from tripcraft.storage.db import Store

# 期望值：id -> (step 值, 名称)
EXPECTED_CP = {
    "CP1": ("S1", "接单与需求核验"),
    "CP2": ("S6", "方案与报价核验"),
    "CP3": ("S11", "行后结算核验"),
}

HAT_NAMES = {
    "white": "白帽·事实核查",
    "black": "黑帽·逻辑审计",
    "green": "绿帽·创意转化",
    "yellow": "黄帽·激励引导",
    "red": "红帽·个性适配",
    "blue": "蓝帽·质量总控",
}
HAT_IDS = ("white", "black", "green", "yellow", "red", "blue")


# ======================================================================
# P8：沙盒检查点
# ======================================================================

def test_checkpoints_ids_and_steps() -> None:
    """CP1/CP2/CP3 的 id、名称与 step（S1/S6/S11）必须与契约一致。"""
    assert isinstance(CHECKPOINTS, tuple), "CHECKPOINTS 必须是元组（契约：tuple[Checkpoint, ...]）"
    assert len(CHECKPOINTS) == 3, f"检查点数量应为 3，实际 {len(CHECKPOINTS)}"
    assert all(isinstance(cp, Checkpoint) for cp in CHECKPOINTS), "CHECKPOINTS 元素必须是 Checkpoint"

    got = {cp.id: (cp.step.value, cp.name) for cp in CHECKPOINTS}
    assert got == EXPECTED_CP, f"检查点 id/step/name 不符：{got} != {EXPECTED_CP}"

    # S1/S6/S11 必须来自 contracts.enums.StepId（契约第 105 行）
    for cp in CHECKPOINTS:
        assert isinstance(cp.step, StepId), f"{cp.id}.step 必须是 StepId，实际 {type(cp.step)!r}"
    assert {cp.id: cp.step for cp in CHECKPOINTS} == {
        "CP1": StepId.S1_GRAB,
        "CP2": StepId.S6_QUOTATION,
        "CP3": StepId.S11_SETTLEMENT,
    }

    # 每个检查点都有非空的中文关键词元组
    for cp in CHECKPOINTS:
        assert isinstance(cp.requirement, tuple) and cp.requirement, f"{cp.id}.requirement 不能为空"


@pytest.mark.parametrize("step, expected_ids", [
    ("S1", ["CP1"]),
    ("S6", ["CP2"]),
    ("S11", ["CP3"]),
    ("S2", []),
    ("S12", []),
])
def test_checkpoints_for_step_by_value(step: str, expected_ids: list[str]) -> None:
    """checkpoints_for_step 接受步骤值字符串，命中绑定该步骤的检查点。"""
    got = [cp.id for cp in checkpoints_for_step(step)]
    assert got == expected_ids, f"checkpoints_for_step({step!r}) = {got}，应为 {expected_ids}"


def test_checkpoints_for_step_accepts_stepid() -> None:
    """checkpoints_for_step 同时接受 StepId 枚举。"""
    assert [cp.id for cp in checkpoints_for_step(StepId.S6_QUOTATION)] == ["CP2"]
    assert [cp.id for cp in checkpoints_for_step(StepId.S2_FIRST_CALL)] == []


def test_evaluate_all_keywords_present_passes() -> None:
    """证据文本命中全部关键词 → passed True，missing 为空。"""
    evidence = ["客户目的地：京都；出行人数 6 人；预算 8 万；已完成首呼"]
    out = evaluate("CP1", evidence)
    assert out["checkpoint"] == "CP1"
    assert out["passed"] is True, f"关键词齐全却未通过，missing={out.get('missing')}"
    assert out["missing"] == []


@pytest.mark.parametrize("cp_id", ["CP1", "CP2", "CP3"])
def test_evaluate_each_checkpoint_passes_with_own_requirements(cp_id: str) -> None:
    """三个检查点各自的要求关键词齐全时都应通过。"""
    cp = next(c for c in CHECKPOINTS if c.id == cp_id)
    out = evaluate(cp_id, ["\n".join(cp.requirement)])
    assert out["passed"] is True, f"{cp_id} 应为通过，missing={out.get('missing')}"
    assert out["missing"] == []


def test_evaluate_keywords_split_across_evidence_items() -> None:
    """关键词分散在多条证据里，仍按合并后的证据文本判定。"""
    out = evaluate("CP2", ["分项报价已出", "成本核算完成", "保险已投保", "毛利 12%"])
    assert out["passed"] is True, f"多段证据应合并判定，missing={out.get('missing')}"


def test_evaluate_missing_lists_unmet_keywords_in_order() -> None:
    """缺项时列出未命中的关键词（保持 requirement 顺序），passed False。"""
    out = evaluate("CP1", ["目的地：大阪", "出行人数：4 人"])
    assert out["checkpoint"] == "CP1"
    assert out["passed"] is False
    assert out["missing"] == ["预算", "首呼"], f"missing 不符：{out['missing']}"


def test_evaluate_unknown_checkpoint_raises_value_error() -> None:
    """未知 checkpoint_id 必须抛 ValueError，而不是返回通过。"""
    with pytest.raises(ValueError):
        evaluate("CP9", ["任意证据"])
    with pytest.raises(ValueError):
        evaluate("", ["任意证据"])


# ======================================================================
# P9：发布门控 + 材料版本
# ======================================================================

def _load_asset_gate():
    """P9 未实现时给出明确失败点（file:line 在 traceback 里可见）。"""
    try:
        from tripcraft.services.asset_gate import AssetGate
    except ImportError as exc:  # pragma: no cover - 未实现时的诊断路径
        pytest.fail(f"P9 未实现：tripcraft/services/asset_gate.py 缺失或不可导入（{exc}）")
    return AssetGate


def _review(white: str = "通过", black: str = "通过") -> dict:
    """构造与 `tripcraft/agents/review.py::SixHatsReview.review` 同形的 review 字典。"""
    verdicts = {"white": white, "black": black, "green": "通过",
                "yellow": "通过", "red": "通过", "blue": "合格"}
    critical = white == "不通过" or black == "不通过"
    return {
        "verdict": "需修改" if critical else "合格",
        "critical_fail": critical,
        "hats": [
            {"id": hid, "name": HAT_NAMES[hid],
             "verdict": ("合格" if (hid == "blue" and verdicts[hid] == "合格") else verdicts[hid]),
             "note": ""}
            for hid in HAT_IDS
        ],
        "parallel": True,
    }


@pytest.fixture
def store():
    """临时 sqlite Store（不碰演示库）。"""
    path = os.path.join(
        tempfile.gettempdir(), f"tripcraft-gates-verify-{uuid.uuid4().hex}.sqlite")
    st = Store(path)
    try:
        yield st
    finally:
        st.close()
        try:
            os.remove(path)
        except OSError:
            pass


def _require_versioning(store: Store) -> None:
    if not hasattr(store, "add_asset_version") or not hasattr(store, "asset_versions"):
        pytest.fail("P9 未实现：storage/db.py 缺 add_asset_version / asset_versions")


def test_db_add_asset_version_increments(store: Store) -> None:
    """db 层：add_asset_version 每次加 1，asset_versions 按版本返回历史。"""
    _require_versioning(store)
    assert store.add_asset_version("asset_x", "材料一") == 1
    assert store.add_asset_version("asset_x", "材料二") == 2

    versions = store.asset_versions("asset_x")
    assert isinstance(versions, list) and len(versions) == 2, f"版本历史应为 2 条：{versions}"
    assert [v["version"] for v in versions] == [1, 2]
    assert [v["content"] for v in versions] == ["材料一", "材料二"]
    assert all({"asset_id", "version", "content", "created_at"} <= set(v) for v in versions)
    assert store.asset_versions("asset_unknown") == []


@pytest.mark.parametrize("white, black", [("不通过", "通过"), ("通过", "不通过")])
def test_asset_gate_evaluate_blocks_on_either_critical_hat(store: Store,
                                                           white: str, black: str) -> None:
    """白帽或黑帽任一「不通过」→ passed False 且 critical_fail True。"""
    AssetGate = _load_asset_gate()
    out = AssetGate(store).evaluate(_review(white=white, black=black))
    assert out["passed"] is False, f"白={white} 黑={black} 应被硬门槛拦下"
    assert out["critical_fail"] is True, f"critical_fail 应为 True：{out}"
    assert isinstance(out["reason"], str) and out["reason"], "不通过时必须给出理由"


def test_asset_gate_evaluate_passes_when_critical_hats_pass(store: Store) -> None:
    """白/黑都通过 → passed True、critical_fail False。"""
    AssetGate = _load_asset_gate()
    out = AssetGate(store).evaluate(_review())
    assert out["passed"] is True, f"应通过：{out}"
    assert out["critical_fail"] is False
    assert isinstance(out["reason"], str)


def test_asset_gate_publish_blocked_does_not_persist(store: Store) -> None:
    """白帽不通过 → publish 返回 passed False、version 0，且不落库。"""
    AssetGate = _load_asset_gate()
    _require_versioning(store)
    out = AssetGate(store).publish(
        "u_ver", "C1.1", "report", "未通过审查的材料", _review(white="不通过"))
    assert out["passed"] is False, f"应被拦下：{out}"
    assert out["version"] == 0, f"未发布版本必须为 0：{out}"
    assert out["versions"] == [], f"未发布时不得有版本历史：{out}"
    if out.get("asset_id"):
        assert store.asset_versions(out["asset_id"]) == [], "未通过的发布不得写版本历史"
    assert store.assets("u_ver") == [], "未通过的发布不得写 asset 表"
    assert store._all("SELECT asset_id, version FROM asset_version") == [], \
        "未通过的发布不得在任何 asset_version 行留下快照"


def test_asset_gate_publish_twice_creates_version_1_and_2(store: Store) -> None:
    """两个通过 review 连续 publish → version 1、2；asset_versions 返回 2 条且内容对应。"""
    AssetGate = _load_asset_gate()
    _require_versioning(store)
    gate = AssetGate(store)

    first = gate.publish("u_ver", "C1.1", "report", "材料 v1", _review())
    assert first["passed"] is True, f"第一次发布应通过：{first}"
    assert first["version"] == 1, f"首次发布版本应为 1：{first}"
    aid = first["asset_id"]

    second = gate.publish("u_ver", "C1.1", "report", "材料 v2", _review())
    assert second["passed"] is True, f"第二次发布应通过：{second}"
    assert second["version"] == 2, f"第二次发布版本应为 2：{second}"
    assert second["asset_id"] == aid, "同一份材料的两次发布应挂在同一 asset_id 下"

    versions = store.asset_versions(aid)
    assert len(versions) == 2, f"asset_versions 应返回 2 条：{versions}"
    assert [v["version"] for v in versions] == [1, 2]
    assert [v["content"] for v in versions] == ["材料 v1", "材料 v2"]
