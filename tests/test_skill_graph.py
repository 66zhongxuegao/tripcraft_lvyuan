"""P1 技能图谱契约测试（5 域 + 8 维 + 61 技能点）。

覆盖：节点/边数量与结构、source 可回查、JSON round-trip、trace 溯源、
query(kind=) 过滤、build_graph 可重复。全程不联网、不写真实数据库。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tripcraft.contracts.enums import DIMENSION_NAMES, Dimension
from tripcraft.contracts.skill_points import SKILL_POINTS
from tripcraft.knowledge.graph import (
    DEFAULT_GRAPH_PATH,
    EDGE_KINDS,
    NODE_KINDS,
    Edge,
    Node,
    SkillGraph,
    build_graph,
    dump_graph,
    load_graph,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_RE = re.compile(r"^contracts/skill_points\.py:(\d+)$")


def _skill_point_dimension() -> dict[str, str]:
    return {sp.id: sp.dimension.value for sp in SKILL_POINTS}


def _skill_point_order() -> dict[str, int]:
    return {sp.id: index for index, sp in enumerate(SKILL_POINTS)}


def _dedupe(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def test_node_counts_5_8_61() -> None:
    graph = build_graph()
    assert len(graph.nodes) == 5 + 8 + 61 == 74
    assert len(graph.query(kind="domain")) == 5
    assert len(graph.query(kind="dimension")) == 8
    assert len(graph.query(kind="skill")) == 61
    assert {node.kind for node in graph.nodes} == set(NODE_KINDS)


def test_edge_counts_contains_and_related() -> None:
    graph = build_graph()
    assert len(graph.edges) == 122
    assert len(graph.edges) > 61
    contains = [edge for edge in graph.edges if edge.kind == "contains"]
    related = [edge for edge in graph.edges if edge.kind == "related"]
    assert len(contains) == 8 + 61
    assert len(related) == 61 - 8
    assert {edge.kind for edge in graph.edges} <= set(EDGE_KINDS)
    assert all(edge.kind != "prereq" for edge in graph.edges)


def test_contains_edges_form_domain_dimension_skill_chain() -> None:
    graph = build_graph()
    nodes = {node.id: node for node in graph.nodes}
    skill_dimension = _skill_point_dimension()

    # 每个维度恰好有 1 个域父节点。
    for dimension in Dimension:
        parents = [
            edge.src
            for edge in graph.edges
            if edge.kind == "contains" and edge.dst == dimension.value
        ]
        assert len(parents) == 1, f"{dimension} 的域父节点数不是 1: {parents}"
        assert nodes[parents[0]].kind == "domain"
        assert nodes[dimension.value].kind == "dimension"

    # 每个技能点恰好有 1 个维度父节点，且与契约中的 Dimension 一致。
    for skill_point in SKILL_POINTS:
        parents = [
            edge.src
            for edge in graph.edges
            if edge.kind == "contains" and edge.dst == skill_point.id
        ]
        assert parents == [skill_dimension[skill_point.id]], skill_point.id
        assert nodes[skill_point.id].kind == "skill"
        assert nodes[skill_point.id].label == skill_point.name

    # 5 个域节点：id 由技能点前缀 C1..C5 生成，标签取对应维度名。
    domain_labels = {
        prefix: DIMENSION_NAMES[Dimension(prefix)]
        for prefix in ("C1", "C2", "C3", "C4", "C5")
    }
    for prefix, label in domain_labels.items():
        domain = nodes[f"domain:{prefix}"]
        assert domain.kind == "domain"
        assert domain.label == label

    # 每个维度至少 1 个技能点（8 维全覆盖）。
    for dimension in Dimension:
        children = [
            edge.dst
            for edge in graph.edges
            if edge.kind == "contains" and edge.src == dimension.value
        ]
        assert children, f"{dimension} 没有技能点子节点"


def test_related_edges_connect_adjacent_same_dimension_skill_points() -> None:
    graph = build_graph()
    skill_dimension = _skill_point_dimension()
    order = _skill_point_order()
    related = [edge for edge in graph.edges if edge.kind == "related"]

    assert len(related) == len(SKILL_POINTS) - len(Dimension)
    for edge in related:
        assert skill_dimension[edge.src] == skill_dimension[edge.dst]
        assert order[edge.dst] == order[edge.src] + 1
        assert edge.src.startswith(Dimension(skill_dimension[edge.src]).value + ".")


def test_every_source_points_to_existing_line_in_skill_points_file() -> None:
    source_path = PROJECT_ROOT / "tripcraft" / "contracts" / "skill_points.py"
    assert source_path.is_file(), f"缺数据源文件: {source_path}"
    source_lines = source_path.read_text(encoding="utf-8").splitlines()

    graph = build_graph()
    for artifact in (*graph.nodes, *graph.edges):
        match = SOURCE_RE.match(artifact.source)
        assert match is not None, f"source 格式不符: {artifact.source!r}"
        lineno = int(match.group(1))
        assert 1 <= lineno <= len(source_lines), f"行号越界: {artifact.source}"
        assert source_lines[lineno - 1].strip(), f"行号指向空行: {artifact.source}"


def test_dump_load_json_round_trip(tmp_path: Path) -> None:
    graph = build_graph()
    path = tmp_path / "nested" / "knowledge-graph.json"
    saved = dump_graph(path)
    assert saved == graph
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["nodes"]) == 74
    assert len(data["edges"]) == 122

    loaded = load_graph(path)
    assert loaded.nodes == graph.nodes
    assert loaded.edges == graph.edges
    assert loaded.to_json() == graph.to_json()
    # to_json() 的字典还能再次 from_json 还原。
    assert SkillGraph.from_json(loaded.to_json()) == graph


def test_dump_load_default_path() -> None:
    graph = build_graph()
    dumped = dump_graph()
    assert dumped == graph
    assert DEFAULT_GRAPH_PATH.is_file()
    assert DEFAULT_GRAPH_PATH.name == "knowledge-graph.json"
    assert DEFAULT_GRAPH_PATH.parent.name == ".dsh-run"
    assert load_graph() == graph


def test_trace_returns_own_and_connected_edge_sources_without_duplicates() -> None:
    graph = build_graph()
    node_source = {node.id: node.source for node in graph.nodes}
    sources = graph.trace("C1.1")

    expected = [node_source["C1.1"]]
    for edge in graph.edges:
        if "C1.1" in (edge.src, edge.dst):
            expected.append(edge.source)
    expected = _dedupe(expected)

    assert sources == expected
    assert sources
    assert sources[0] == node_source["C1.1"]
    assert len(sources) == len(set(sources))


def test_trace_non_empty_for_every_node() -> None:
    graph = build_graph()
    for node in graph.nodes:
        assert graph.trace(node.id), f"{node.id} 的溯源为空"


def test_query_filters_by_kind() -> None:
    graph = build_graph()
    assert len(graph.query()) == 74
    assert [node.id for node in graph.query(kind="skill")] == [sp.id for sp in SKILL_POINTS]
    assert {node.id for node in graph.query(kind="dimension")} == {
        dimension.value for dimension in Dimension
    }
    assert len(graph.query(kind="domain")) == 5
    with pytest.raises(ValueError):
        graph.query(kind="not-a-kind")


def test_neighbors_links_dimension_and_adjacent_skills() -> None:
    graph = build_graph()
    neighbor_ids = {node.id for node in graph.neighbors("C1.1")}
    # 维度父节点 + 同维相邻技能点。
    assert neighbor_ids == {"C1", "C1.2"}


def test_build_graph_is_deterministic() -> None:
    assert build_graph() == build_graph()
    first = build_graph().to_json()
    second = build_graph().to_json()
    assert first == second


def test_to_json_is_plain_json_serializable() -> None:
    payload = build_graph().to_json()
    assert set(payload) == {"nodes", "edges"}
    assert all(set(item) == {"id", "kind", "label", "source"} for item in payload["nodes"])
    assert all(set(item) == {"src", "dst", "kind", "source"} for item in payload["edges"])
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_nodes_and_edges_are_frozen_dataclasses() -> None:
    graph = build_graph()
    node = Node(id="x", kind="skill", label="x", source="contracts/skill_points.py:1")
    edge = Edge(src="a", dst="b", kind="contains", source="contracts/skill_points.py:1")
    with pytest.raises(AttributeError):
        node.label = "y"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        edge.kind = "related"  # type: ignore[misc]
    assert isinstance(graph.nodes[0], Node)
    assert isinstance(graph.edges[0], Edge)
