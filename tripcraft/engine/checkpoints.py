"""沙盒检查点 —— 关键节点的「需求核验」清单（PPT 技术点 P8）。

口径来源：PRD 第 8 章门控、第 19 章考点、第 11 章交付物。
设计原则：核验是**确定性**判定，不交给生成式模型；每个检查点绑定一个
`StepId`，用 2-4 个中文关键词描述该节点必须落到证据里的内容，
证据文本命中全部关键词才算通过。检查点不产生副作用，只读 evidence。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.enums import StepId


@dataclass(frozen=True)
class Checkpoint:
    """一个检查点：id + 名称 + 绑定步骤 + 需求关键词元组。"""

    id: str
    name: str
    step: StepId
    requirement: tuple[str, ...]


CHECKPOINTS: tuple[Checkpoint, ...] = (
    Checkpoint(
        id="CP1",
        name="接单与需求核验",
        step=StepId.S1_GRAB,
        requirement=("目的地", "人数", "预算", "首呼"),
    ),
    Checkpoint(
        id="CP2",
        name="方案与报价核验",
        step=StepId.S6_QUOTATION,
        requirement=("报价", "成本", "保险", "毛利"),
    ),
    Checkpoint(
        id="CP3",
        name="行后结算核验",
        step=StepId.S11_SETTLEMENT,
        requirement=("结算", "对账", "尾款"),
    ),
)

_BY_ID: dict[str, Checkpoint] = {cp.id: cp for cp in CHECKPOINTS}


def checkpoints_for_step(step: StepId | str) -> list[Checkpoint]:
    """返回绑定到该步骤的检查点；`step` 接受 `StepId` 或其值字符串（如 "S1"）。"""
    value = step.value if isinstance(step, StepId) else str(step)
    return [cp for cp in CHECKPOINTS if cp.step.value == value]


def evaluate(checkpoint_id: str, evidence: list[str]) -> dict:
    """按关键词判定证据是否满足该检查点。

    返回 {"checkpoint": id, "passed": bool, "missing": [未命中的关键词]}；
    `checkpoint_id` 不存在时抛 ValueError。
    """
    checkpoint = _BY_ID.get(checkpoint_id)
    if checkpoint is None:
        raise ValueError(
            f"未知检查点 {checkpoint_id!r}，可选：{', '.join(_BY_ID)}"
        )
    text = "\n".join(evidence)
    missing = [kw for kw in checkpoint.requirement if kw not in text]
    return {"checkpoint": checkpoint.id, "passed": not missing, "missing": missing}
