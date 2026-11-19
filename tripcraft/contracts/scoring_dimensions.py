"""67 维评分矩阵 —— 61 技能点 + 6 横切维（P5 技术点）。

口径来源：`.dsh-run/ppt-spec.md` P5。6 个横切维不新增技能点，只把既有 61 个技能点
按跨域视角聚合，便于一张矩阵同时看到「技能点级」与「体验/成本/合规/安全/效率/关系」六个面。

设计约束：
- `ALL_DIMENSION_IDS` 导入即计算：61 个技能点（顺序同 `SKILL_POINTS`）+ 6 个横切维
  = 67 项，顺序稳定、无重复。
- `build_scoring_matrix()` 对 61 个技能点直接取值（缺省 0.0，不抛 KeyError）；
  6 个横切维按 `CROSS_DIMENSION_SOURCES` 显式列出的相关技能点求算术均值，
  没有相关技能点时记 0.0。
- 纯函数：同输入必得同输出，不读时钟/随机数/数据库/网络。
"""

from __future__ import annotations

from .skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID


CROSS_DIMENSIONS: tuple[str, ...] = (
    "X1_EXPERIENCE",
    "X2_COST",
    "X3_COMPLIANCE",
    "X4_SAFETY",
    "X5_EFFICIENCY",
    "X6_RELATION",
)

# 6 个横切维 → 相关技能点（显式 id 列表；跨维允许重叠，因为它们是同一批表现的不同观察面）。
#
# X1 体验：C1 沟通语言域（首呼/提问/安抚/成交/投诉/倾听/回访）+ C4 资源服务域（询价到锁定）。
# X2 成本：C5 报价利润域全部（成本核算、毛利、波动对冲、超预算解释、结算对账）。
# X3 合规：C7 合规效率域全部 + C5.6 保险必选 + C8.3 实操红线 + C8.5 签证免签政策。
# X4 安全：C6 应急解决域全部 + C3.5 特殊人群适配 + C7.4 合同保险付款 + C7.7 行前二次核验。
# X5 效率：C7.1 时限管理 + C3.2 路线合理性 + C3.3 开放时间/交通耗时核验
#          + C4.3 可用性确认 + C4.8 资源锁定 + C5.7 结算对账。
# X6 关系：C1.3 情绪安抚 + C1.4 成交促成 + C1.5 投诉处理 + C1.7 倾听真实诉求
#          + C1.8 回访闭环 + C8.7 跨文化投诉与信任补救。
CROSS_DIMENSION_SOURCES: dict[str, tuple[str, ...]] = {
    "X1_EXPERIENCE": (
        "C1.1", "C1.2", "C1.3", "C1.4", "C1.5", "C1.6", "C1.7", "C1.8",
        "C4.1", "C4.2", "C4.3", "C4.4", "C4.5", "C4.6", "C4.7", "C4.8",
    ),
    "X2_COST": (
        "C5.1", "C5.2", "C5.3", "C5.4", "C5.5", "C5.6", "C5.7", "C5.8",
    ),
    "X3_COMPLIANCE": (
        "C7.1", "C7.2", "C7.3", "C7.4", "C7.5", "C7.6", "C7.7",
        "C5.6", "C8.3", "C8.5",
    ),
    "X4_SAFETY": (
        "C6.1", "C6.2", "C6.3", "C6.4", "C6.5", "C6.6", "C6.7",
        "C3.5", "C7.4", "C7.7",
    ),
    "X5_EFFICIENCY": (
        "C7.1", "C3.2", "C3.3", "C4.3", "C4.8", "C5.7",
    ),
    "X6_RELATION": (
        "C1.3", "C1.4", "C1.5", "C1.7", "C1.8", "C8.7",
    ),
}

# 61 技能点（与 SKILL_POINTS 同序）+ 6 横切维 = 67，导入即计算。
ALL_DIMENSION_IDS: tuple[str, ...] = (
    tuple(sp.id for sp in SKILL_POINTS) + CROSS_DIMENSIONS
)


def _mean_of(ids: tuple[str, ...], scores: dict[str, float]) -> float:
    """相关技能点的算术均值；`ids` 为空（无相关技能点）时返回 0.0。"""
    if not ids:
        return 0.0
    return sum(scores.get(i, 0.0) for i in ids) / len(ids)


def build_scoring_matrix(skill_scores: dict[str, float]) -> dict[str, float]:
    """把 61 技能点得分展开为 67 维评分矩阵。

    - 61 个技能点：直接取 `skill_scores` 的值，缺失记 0.0（不抛 KeyError）。
    - 6 个横切维：相关技能点的算术均值，缺失的相关技能点按 0.0 参与平均；
      无相关技能点时记 0.0。
    返回 67 项，键顺序与 `ALL_DIMENSION_IDS` 一致。
    """
    direct: dict[str, float] = {
        sp.id: float(skill_scores.get(sp.id, 0.0)) for sp in SKILL_POINTS
    }
    matrix: dict[str, float] = dict(direct)
    for cross_id in CROSS_DIMENSIONS:
        matrix[cross_id] = _mean_of(CROSS_DIMENSION_SOURCES[cross_id], direct)
    return matrix


def _validate() -> None:
    assert len(SKILL_POINTS) == 61, f"技能点数量应为 61，实际 {len(SKILL_POINTS)}"
    assert len(CROSS_DIMENSIONS) == 6, f"横切维数量应为 6，实际 {len(CROSS_DIMENSIONS)}"
    assert len(ALL_DIMENSION_IDS) == 67, f"维度总数应为 67，实际 {len(ALL_DIMENSION_IDS)}"
    assert len(set(ALL_DIMENSION_IDS)) == 67, "维度 ID 重复"
    assert set(CROSS_DIMENSION_SOURCES) == set(CROSS_DIMENSIONS), "横切维映射与常量不一致"
    unknown = sorted(
        set().union(*(set(ids) for ids in CROSS_DIMENSION_SOURCES.values()))
        - set(SKILL_POINTS_BY_ID)
    )
    assert not unknown, f"横切维映射引用了不存在的技能点：{unknown}"
    empty = [cid for cid in CROSS_DIMENSIONS if not CROSS_DIMENSION_SOURCES[cid]]
    assert not empty, f"横切维无相关技能点：{empty}"


_validate()
