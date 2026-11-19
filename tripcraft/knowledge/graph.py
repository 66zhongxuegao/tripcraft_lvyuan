"""技能图谱 —— 域 / 维度 / 技能点三层结构，可 JSON 落盘与溯源。

数据源只有两处：

- ``contracts.skill_points.SKILL_POINTS``：61 个技能点（含所属 ``Dimension``）；
- ``contracts.enums.Dimension``：8 个能力维度（C1..C8）。

图结构（节点 5 + 8 + 61，边 = contains + related）：

- ``domain``：5 个能力域。域 id 按技能点 id 前缀 C1..C5 生成（``domain:C1`` .. ``domain:C5``），
  域标签取 ``DIMENSION_NAMES`` 中 C1..C5 对应维度名（PRD 口径的五大能力域）。
  C6/C7/C8 是后加的专项维度（应急 / 合规 / 入境游），按业务归属挂到五大域：
  C8 跨文化沟通 → C1 沟通信任；C6 应急解决 → C4 资源整合（替补资源与行中处置）；
  C7 合规效率 → C5 报价利润（报价→录单→结算的履约链）。
- ``dimension``：8 个维度节点，id 即 ``Dimension.value``（``C1`` .. ``C8``）。
- ``skill``：61 个技能点节点，id 即技能点 id（``C1.1`` .. ``C8.7``）。

边：

- ``contains``：域→维（8 条）、维→技能点（61 条）；
- ``related``：同维度内按技能点 id 相邻（每个维度 n-1 条，共 53 条）；
- ``prereq`` 在 ``EDGE_KINDS`` 中预留，本版本不生成。

溯源：每个节点/边都带 ``source``，形如 ``contracts/skill_points.py:31``，行号从
``contracts/skill_points.py`` 的实际内容解析（技能点定义行），保证可回查。

``build_graph()`` 是纯构造：无随机数、无时间、无网络，重复调用结果完全一致。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from tripcraft.contracts import skill_points as _skill_points_module
from tripcraft.contracts.enums import DIMENSION_NAMES, Dimension
from tripcraft.contracts.skill_points import SKILL_POINTS

NODE_KINDS: tuple[str, ...] = ("domain", "dimension", "skill")
EDGE_KINDS: tuple[str, ...] = ("contains", "prereq", "related")

# 节点/边的 source 统一用的展示路径（相对项目根）。
SOURCE_FILE: str = "contracts/skill_points.py"

# 五大能力域：域 id → 域标签来源维度（C1..C5）与所含维度。
DOMAIN_PREFIXES: tuple[str, ...] = ("C1", "C2", "C3", "C4", "C5")
DOMAIN_DIMENSIONS: dict[str, tuple[Dimension, ...]] = {
    "domain:C1": (Dimension.C1_COMMUNICATION, Dimension.C8_CROSS_CULTURE),
    "domain:C2": (Dimension.C2_REQUIREMENT,),
    "domain:C3": (Dimension.C3_ITINERARY,),
    "domain:C4": (Dimension.C4_RESOURCE, Dimension.C6_EMERGENCY),
    "domain:C5": (Dimension.C5_QUOTATION, Dimension.C7_COMPLIANCE),
}
DIMENSION_DOMAIN: dict[Dimension, str] = {
    dimension: domain_id
    for domain_id, dimensions in DOMAIN_DIMENSIONS.items()
    for dimension in dimensions
}

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_GRAPH_PATH: Path = _PROJECT_ROOT / ".dsh-run" / "knowledge-graph.json"

_SKILL_POINT_LINE_RE = re.compile(r'^\s*SkillPoint\("([^"]+)"')


@dataclass(frozen=True)
class Node:
    """图谱节点：id / 类别 / 展示名 / 溯源。"""

    id: str
    kind: str
    label: str
    source: str


@dataclass(frozen=True)
class Edge:
    """图谱有向边：源 / 目标 / 关系类别 / 溯源。"""

    src: str
    dst: str
    kind: str
    source: str


@dataclass(frozen=True)
class SkillGraph:
    """不可变技能图谱；所有查询都不改内部状态。"""

    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()

    def _node_index(self) -> dict[str, Node]:
        return {node.id: node for node in self.nodes}

    def neighbors(self, node_id: str) -> list[Node]:
        """返回通过任意一条边与 ``node_id`` 直接相连的节点（按边顺序去重）。"""
        index = self._node_index()
        if node_id not in index:
            raise KeyError(f"图谱中不存在节点: {node_id}")
        seen: set[str] = set()
        result: list[Node] = []
        for edge in self.edges:
            if edge.src == node_id:
                other = edge.dst
            elif edge.dst == node_id:
                other = edge.src
            else:
                continue
            if other in seen:
                continue
            seen.add(other)
            result.append(index[other])
        return result

    def trace(self, node_id: str) -> list[str]:
        """返回该节点自身 source 与相连边 source 的去重列表（节点 source 在前）。"""
        index = self._node_index()
        node = index.get(node_id)
        if node is None:
            raise KeyError(f"图谱中不存在节点: {node_id}")
        sources: list[str] = [node.source]
        for edge in self.edges:
            if node_id in (edge.src, edge.dst) and edge.source not in sources:
                sources.append(edge.source)
        return sources

    def query(self, *, kind: str | None = None) -> list[Node]:
        """按节点类别过滤；``kind=None`` 返回全部节点。"""
        if kind is not None and kind not in NODE_KINDS:
            raise ValueError(f"未知节点类别: {kind!r}，可选 {NODE_KINDS}")
        return [node for node in self.nodes if kind is None or node.kind == kind]

    def to_json(self) -> dict:
        """转成可 JSON 序列化的字典（节点/边顺序稳定）。"""
        return {
            "nodes": [
                {"id": node.id, "kind": node.kind, "label": node.label, "source": node.source}
                for node in self.nodes
            ],
            "edges": [
                {"src": edge.src, "dst": edge.dst, "kind": edge.kind, "source": edge.source}
                for edge in self.edges
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> "SkillGraph":
        """从 :meth:`to_json` 的字典还原图谱（节点/边完全一致）。"""
        return cls(
            nodes=tuple(Node(**item) for item in data["nodes"]),
            edges=tuple(Edge(**item) for item in data["edges"]),
        )


def _skill_point_lines() -> dict[str, int]:
    """解析 ``contracts/skill_points.py``，返回技能点 id → 定义行号（1 起）。"""
    source_path = Path(_skill_points_module.__file__).resolve()
    lines: dict[str, int] = {}
    for lineno, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), start=1):
        match = _SKILL_POINT_LINE_RE.match(line)
        if match is not None:
            lines[match.group(1)] = lineno
    missing = [sp.id for sp in SKILL_POINTS if sp.id not in lines]
    if missing:
        raise RuntimeError(f"技能点定义行解析失败，缺少: {missing}")
    return lines


def _source_of(skill_point_id: str, lines: dict[str, int]) -> str:
    return f"{SOURCE_FILE}:{lines[skill_point_id]}"


def _skills_by_dimension() -> dict[Dimension, list]:
    grouped: dict[Dimension, list] = {dimension: [] for dimension in Dimension}
    for skill_point in SKILL_POINTS:
        grouped[skill_point.dimension].append(skill_point)
    return grouped


def build_graph() -> SkillGraph:
    """从 ``SKILL_POINTS`` 与 ``Dimension`` 构建 5 + 8 + 61 节点技能图谱。"""
    lines = _skill_point_lines()
    by_dimension = _skills_by_dimension()
    for dimension, skill_points in by_dimension.items():
        if not skill_points:
            raise RuntimeError(f"维度 {dimension} 没有技能点，无法生成图谱")

    nodes: list[Node] = []
    edges: list[Edge] = []

    # 域节点：id 按 C1..C5 前缀生成，标签取 C1..C5 对应维度名。
    for prefix in DOMAIN_PREFIXES:
        domain_id = f"domain:{prefix}"
        nodes.append(
            Node(
                id=domain_id,
                kind="domain",
                label=DIMENSION_NAMES[Dimension(prefix)],
                source=_source_of(by_dimension[DOMAIN_DIMENSIONS[domain_id][0]][0].id, lines),
            )
        )

    # 维度节点：id 即 Dimension.value。
    for dimension in Dimension:
        first_skill_point = by_dimension[dimension][0]
        nodes.append(
            Node(
                id=dimension.value,
                kind="dimension",
                label=f"{dimension.value} {DIMENSION_NAMES[dimension]}",
                source=_source_of(first_skill_point.id, lines),
            )
        )

    # 技能点节点。
    for skill_point in SKILL_POINTS:
        nodes.append(
            Node(
                id=skill_point.id,
                kind="skill",
                label=skill_point.name,
                source=_source_of(skill_point.id, lines),
            )
        )

    # contains：域 → 维。
    for dimension in Dimension:
        edges.append(
            Edge(
                src=DIMENSION_DOMAIN[dimension],
                dst=dimension.value,
                kind="contains",
                source=_source_of(by_dimension[dimension][0].id, lines),
            )
        )

    # contains：维 → 技能点。
    for dimension in Dimension:
        for skill_point in by_dimension[dimension]:
            edges.append(
                Edge(
                    src=dimension.value,
                    dst=skill_point.id,
                    kind="contains",
                    source=_source_of(skill_point.id, lines),
                )
            )

    # related：同维度内按技能点 id 相邻。
    for dimension in Dimension:
        skill_points = by_dimension[dimension]
        for previous, following in zip(skill_points, skill_points[1:]):
            edges.append(
                Edge(
                    src=previous.id,
                    dst=following.id,
                    kind="related",
                    source=_source_of(following.id, lines),
                )
            )

    return SkillGraph(nodes=tuple(nodes), edges=tuple(edges))


def dump_graph(path: str | Path | None = None) -> SkillGraph:
    """构建图谱并写入 JSON（默认 ``.dsh-run/knowledge-graph.json``，自动建目录）。"""
    target = Path(path) if path is not None else DEFAULT_GRAPH_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    graph = build_graph()
    target.write_text(
        json.dumps(graph.to_json(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return graph


def load_graph(path: str | Path | None = None) -> SkillGraph:
    """从 JSON 读回图谱（默认 ``.dsh-run/knowledge-graph.json``）。"""
    target = Path(path) if path is not None else DEFAULT_GRAPH_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    return SkillGraph.from_json(data)
