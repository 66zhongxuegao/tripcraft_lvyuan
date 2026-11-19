"""P8 沙盒检查点的回归测试。"""

import pytest

from tripcraft.contracts.enums import StepId
from tripcraft.engine.checkpoints import CHECKPOINTS, Checkpoint, checkpoints_for_step, evaluate


# ---------------------------------------------------------------- 定义合法性

def test_checkpoint_ids_and_names():
    assert [cp.id for cp in CHECKPOINTS] == ["CP1", "CP2", "CP3"]
    assert [cp.name for cp in CHECKPOINTS] == ["接单与需求核验", "方案与报价核验", "行后结算核验"]
    assert all(isinstance(cp, Checkpoint) for cp in CHECKPOINTS)


def test_checkpoint_steps_are_stepid_members():
    assert [cp.step for cp in CHECKPOINTS] == [
        StepId.S1_GRAB,
        StepId.S6_QUOTATION,
        StepId.S11_SETTLEMENT,
    ]
    step_values = {s.value for s in StepId}
    for cp in CHECKPOINTS:
        assert isinstance(cp.step, StepId), f"{cp.id} 的 step 必须是 StepId 成员"
        assert cp.step.value in step_values, f"{cp.id} 的 step 值 {cp.step.value} 不在 StepId 中"


def test_checkpoint_requirements_are_short_chinese_keywords():
    for cp in CHECKPOINTS:
        assert isinstance(cp.requirement, tuple)
        assert 2 <= len(cp.requirement) <= 4, f"{cp.id} 关键词数量应为 2-4"
        for keyword in cp.requirement:
            assert isinstance(keyword, str) and keyword, f"{cp.id} 含空关键词"
            assert any("\u4e00" <= ch <= "\u9fff" for ch in keyword), (
                f"{cp.id} 关键词 {keyword!r} 应为中文"
            )


# ---------------------------------------------------------------- checkpoints_for_step

def test_checkpoints_for_step_hit_by_enum():
    assert checkpoints_for_step(StepId.S1_GRAB) == [CHECKPOINTS[0]]
    assert checkpoints_for_step(StepId.S6_QUOTATION) == [CHECKPOINTS[1]]
    assert checkpoints_for_step(StepId.S11_SETTLEMENT) == [CHECKPOINTS[2]]


def test_checkpoints_for_step_hit_by_value_string():
    assert checkpoints_for_step("S1") == [CHECKPOINTS[0]]
    assert checkpoints_for_step("S6") == [CHECKPOINTS[1]]
    assert checkpoints_for_step("S11") == [CHECKPOINTS[2]]
    assert checkpoints_for_step("S1")[0].id == "CP1"


def test_checkpoints_for_step_miss_returns_empty_list():
    assert checkpoints_for_step(StepId.S2_FIRST_CALL) == []
    assert checkpoints_for_step("S12") == []
    assert checkpoints_for_step("S99") == []


# ---------------------------------------------------------------- evaluate

def test_evaluate_passed_cp1():
    result = evaluate(
        "CP1",
        ["客户目的地：云南", "出行人数 6 人", "预算 3 万元", "已完成首呼并形成计划"],
    )
    assert result == {"checkpoint": "CP1", "passed": True, "missing": []}


def test_evaluate_passed_cp2():
    result = evaluate("CP2", ["分项报价单已出", "成本 12000", "报价含保险", "毛利率 12%"])
    assert result["checkpoint"] == "CP2"
    assert result["passed"] is True
    assert result["missing"] == []


def test_evaluate_passed_cp3_across_separate_evidence_items():
    # 关键词分散在多条证据里，拼接后判定
    result = evaluate("CP3", ["结算核对表", "对账无差异", "尾款已结清"])
    assert result == {"checkpoint": "CP3", "passed": True, "missing": []}


def test_evaluate_missing_keywords_cp2():
    result = evaluate("CP2", ["报价单已出", "成本明细齐全"])
    assert result["checkpoint"] == "CP2"
    assert result["passed"] is False
    assert result["missing"] == ["保险", "毛利"]


def test_evaluate_missing_keywords_cp1():
    result = evaluate("CP1", ["目的地：云南", "首呼完成"])
    assert result["passed"] is False
    assert result["missing"] == ["人数", "预算"]


def test_evaluate_empty_evidence_fails_with_all_missing():
    result = evaluate("CP3", [])
    assert result["passed"] is False
    assert result["missing"] == list(CHECKPOINTS[2].requirement)


@pytest.mark.parametrize("bad_id", ["CP9", "cp1", "", "S1"])
def test_evaluate_unknown_checkpoint_raises_value_error(bad_id):
    with pytest.raises(ValueError):
        evaluate(bad_id, ["报价", "成本", "保险", "毛利"])
