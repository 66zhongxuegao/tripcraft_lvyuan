"""评分回写图谱 —— 把实战/学习评分落到能力表，并回写知识图谱节点掌握度。

口径（PPT 技术点 P2）：一次 `record()` 做三件事：
1. 走现有 `Store.set_ability(user_id, sp, real_v=score, source=...)` 写能力表；
2. 返回该技能点的掌握度档位（`contracts.enums.mastery_of`，M1–M5）；
3. 若注入了 P1 的 `SkillGraph`，把分数写进对应技能节点的掌握度；节点不可写时
   在 `GraphWriteback` 内部维护 overlay（用户 → 技能点 → 分数），保证可查、可复算。

P1 的 `tripcraft/knowledge/graph.py` 可能尚未落地，所以本模块**不在顶层 import**
知识图谱包：`_as_graph()` 在实例化时延迟导入并校验，模块缺失就退回纯 overlay，
不会因 P1 未完成而崩溃。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts.enums import mastery_of

SKILL_KIND = "skill"


def _as_graph(graph: Any | None) -> Any | None:
    """延迟导入 P1 的 SkillGraph 做类型校验；模块未落地时按鸭子类型接受。

    - graph 为 None → None；
    - 能 import 到 SkillGraph 且是实例 → 原样返回；
    - import 不到（P1 并行开发中）→ 只要能 `query(kind="skill")` 就按图谱用；
    - 其余非法对象 → None（退回纯 overlay）。
    """
    if graph is None:
        return None
    try:
        from ..knowledge.graph import SkillGraph  # 延迟导入：P1 可能尚未落地
    except Exception:
        SkillGraph = None  # type: ignore[assignment,misc]
    if SkillGraph is not None and isinstance(graph, SkillGraph):
        return graph
    if callable(getattr(graph, "query", None)):
        return graph
    return None


def _ability_score(row: dict) -> float:
    """能力行 → 分数：实战分优先（能上手才算数），没实战分再看教学分。"""
    real = float(row.get("real_v") or 0.0)
    if real > 0:
        return real
    return float(row.get("teach") or 0.0)


@dataclass
class GraphWriteback:
    """评分回写：能力表是唯一事实源，图谱/overlay 是它的可视图。"""

    store: Any
    graph: Any | None = None
    _overlay: dict[str, dict[str, float]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.graph = _as_graph(self.graph)

    # ------------------------------------------------------------------ 回写
    def record(self, user_id: str, skill_point_id: str, score: float,
               source: str = "practice") -> dict:
        """写入一次评分，返回 {skill_point_id, score, mastery, graph_node}。"""
        value = float(score)
        self.store.set_ability(user_id, skill_point_id, real_v=value, source=source)
        node_id = self._write_back(user_id, {skill_point_id: value}).get(skill_point_id)
        return {
            "skill_point_id": skill_point_id,
            "score": value,
            "mastery": mastery_of(value).value,
            "graph_node": node_id or skill_point_id,
        }

    # ------------------------------------------------------------------ 查询
    def weak_top3(self, user_id: str) -> list[str]:
        """分数升序取最多 3 个技能点；同分按技能点 id 升序，稳定可复算。"""
        scores = self._scores(user_id)
        ranked = sorted(scores.items(), key=lambda item: (item[1], item[0]))
        return [sp for sp, _ in ranked[:3]]

    def graph_mastery(self, user_id: str) -> dict[str, float]:
        """技能点 → 分数；有图谱时同步写节点掌握度（不可写则进 overlay）。"""
        scores = self._scores(user_id)
        self._write_back(user_id, scores)
        return scores

    def overlay(self, user_id: str) -> dict[str, float]:
        """本类内部的掌握度镜像（图谱节点不可写时的落点）。"""
        return dict(self._overlay.get(user_id, {}))

    # ------------------------------------------------------------------ 内部
    def _scores(self, user_id: str) -> dict[str, float]:
        rows = self.store.abilities(user_id) or {}
        return {sp: _ability_score(row) for sp, row in rows.items()}

    def _skill_nodes(self) -> dict[str, Any]:
        """技能点 id → 图谱节点；节点 id 可能是完整的 `skill:C1.1`。"""
        if self.graph is None:
            return {}
        try:
            nodes = self.graph.query(kind=SKILL_KIND) or []
        except Exception:
            return {}
        index: dict[str, Any] = {}
        for node in nodes:
            node_id = str(getattr(node, "id", "") or "")
            if not node_id:
                continue
            index.setdefault(node_id, node)
            tail = node_id.rsplit(":", 1)[-1]
            index.setdefault(tail, node)
        return index

    def _write_back(self, user_id: str, scores: dict[str, float]) -> dict[str, str]:
        """分数写进 overlay；有图谱时再尝试写节点属性，返回 sp → 节点 id。"""
        self._overlay.setdefault(user_id, {}).update(scores)
        index = self._skill_nodes()
        node_ids: dict[str, str] = {}
        for sp, value in scores.items():
            node = index.get(sp)
            if node is None:
                continue
            node_ids[sp] = str(getattr(node, "id", sp))
            try:
                setattr(node, "mastery", float(value))
            except Exception:
                continue  # P1 节点是 frozen dataclass → 以 overlay 为准
        return node_ids
