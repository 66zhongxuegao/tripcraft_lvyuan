"""P1/P2 契约独立验收（ver-01 交叉验证）。

契约来源：`.dsh-run/ppt-spec.md` 第 12–49 行。本文件只断言对外契约，
不读实现内部结构；实现缺失或与契约不符时测试失败，报告里给出 file:line。

P1 `tripcraft/knowledge/graph.py`：
    5 域 + 8 维 + 61 技能点节点；边含 contains（域→维→技能点）与 related（同维相邻）；
    trace() 带 contracts/ 溯源；dump/load 往返；query(kind="skill") == 61；build 两次一致。
P2 `tripcraft/services/graph_writeback.py`：
    record 落 Store；weak_top3 ≤3 且分数升序；graph_mastery 非空；无 graph 参数可用。
"""

from __future__ import annotations

import importlib
import os
import re
import tempfile
import uuid
from collections import Counter

import pytest

from tripcraft.contracts.enums import mastery_of
from tripcraft.contracts.skill_points import SKILL_POINTS

# 契约：每个节点/边的 source 形如 contracts/skill_points.py:12
SOURCE_RE = re.compile(r"^contracts/[A-Za-z0-9_./-]+:\d+$")


def _module(name: str):
    """导入契约模块；缺失/导入失败时给出一条明确的失败信息，而不是静默跳过。"""
    try:
        return importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - 实现未就绪时要把原因写进测试报告
        pytest.fail(f"契约模块缺失或导入失败：{name}（{type(exc).__name__}: {exc}）")


def _graph_api():
    """tripcraft/knowledge/graph.py 的契约成员。"""
    mod = _module("tripcraft.knowledge.graph")
    missing = [
        attr for attr in ("NODE_KINDS", "EDGE_KINDS", "Node", "Edge", "SkillGraph",
                          "build_graph", "dump_graph", "load_graph")
        if not hasattr(mod, attr)
    ]
    assert not missing, f"tripcraft/knowledge/graph.py 缺契约成员：{missing}"
    return mod


def _writeback_api():
    mod = _module("tripcraft.services.graph_writeback")
    assert hasattr(mod, "GraphWriteback"), "tripcraft/services/graph_writeback.py 缺 GraphWriteback"
    return mod


@pytest.fixture()
def store():
    """临时 Store：沿用 tests/ 既有口径，库文件放系统临时目录，用完关闭并删除。"""
    from tripcraft.storage.db import Store

    path = os.path.join(tempfile.gettempdir(), f"graph-verify-{uuid.uuid4().hex}.sqlite")
    s = Store(path)
    try:
        yield s
    finally:
        s.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass


# ---------------------------------------------------------------------- P1 图谱


def test_graph_nodes_edges_and_sources():
    mod = _graph_api()
    assert mod.NODE_KINDS == ("domain", "dimension", "skill")
    assert mod.EDGE_KINDS == ("contains", "prereq", "related")

    graph = mod.build_graph()
    assert isinstance(graph.nodes, tuple), "SkillGraph.nodes 应为 tuple"
    assert isinstance(graph.edges, tuple), "SkillGraph.edges 应为 tuple"

    counts = Counter(n.kind for n in graph.nodes)
    assert counts == {"domain": 5, "dimension": 8, "skill": 61}, dict(counts)
    assert len(graph.nodes) == 5 + 8 + 61
    assert len(graph.edges) > 61, f"边数应 > 61，实际 {len(graph.edges)}"

    for node in graph.nodes:
        assert SOURCE_RE.match(node.source), f"节点 {node.id} 的 source 不符契约：{node.source!r}"
    ids = {n.id for n in graph.nodes}
    for edge in graph.edges:
        assert edge.kind in mod.EDGE_KINDS, f"边类型不符契约：{edge.kind!r}"
        assert SOURCE_RE.match(edge.source), (
            f"边 {edge.src}->{edge.dst} 的 source 不符契约：{edge.source!r}"
        )
        assert edge.src in ids and edge.dst in ids, f"边端点不存在：{edge.src}->{edge.dst}"

    domain_ids = {n.id for n in graph.nodes if n.kind == "domain"}
    dim_ids = {n.id for n in graph.nodes if n.kind == "dimension"}
    skill_ids = {n.id for n in graph.nodes if n.kind == "skill"}
    contains = [(e.src, e.dst) for e in graph.edges if e.kind == "contains"]
    assert contains, "契约要求 contains 边（域→维→技能点）"
    assert {dst for src, dst in contains if src in domain_ids} == dim_ids, (
        "并非每个维节点都有域父节点（contains）"
    )
    assert {dst for src, dst in contains if src in dim_ids} == skill_ids, (
        "并非每个技能点节点都有维父节点（contains）"
    )

    related = [(e.src, e.dst) for e in graph.edges if e.kind == "related"]
    assert related, "契约要求 related 边（同维技能点相邻）"
    parent = {dst: src for src, dst in contains if src in dim_ids}
    for src, dst in related:
        assert src in skill_ids and dst in skill_ids, f"related 边端点不是技能点：{src}->{dst}"
        assert parent.get(src) == parent.get(dst), f"related 边跨维：{src}->{dst}"


def test_trace_query_dump_load_and_repeatable_build():
    mod = _graph_api()
    graph = mod.build_graph()

    # query(kind="skill") 恰好 61
    skills = graph.query(kind="skill")
    assert len(skills) == 61, f"query(kind='skill') 应返回 61，实际 {len(skills)}"
    assert all(n.kind == "skill" for n in skills)

    # trace 非空且含 contracts/ 溯源
    node = graph.nodes[0]
    trace = graph.trace(node.id)
    assert isinstance(trace, list) and trace, f"trace({node.id!r}) 应为非空列表"
    assert any("contracts/" in str(item) for item in trace), (
        f"trace({node.id!r}) 未带 contracts/ 溯源：{trace!r}"
    )

    # neighbors 返回 Node 列表（接口契约）
    dim = next(n for n in graph.nodes if n.kind == "dimension")
    neighbors = graph.neighbors(dim.id)
    assert isinstance(neighbors, list) and neighbors, f"neighbors({dim.id!r}) 应为非空列表"
    assert all(isinstance(n, mod.Node) for n in neighbors)

    # dump/load round-trip（显式临时路径，不写仓库默认路径）
    path = os.path.join(tempfile.gettempdir(), f"graph-verify-{uuid.uuid4().hex}.json")
    try:
        dumped = mod.dump_graph(path)
        assert isinstance(dumped, mod.SkillGraph)
        assert os.path.exists(path), "dump_graph 未落盘"
        loaded = mod.load_graph(path)
        assert loaded.to_json() == graph.to_json(), "dump/load 往返不一致"
        assert mod.SkillGraph.from_json(graph.to_json()).to_json() == graph.to_json(), (
            "to_json/from_json 往返不一致"
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    # build 两次结果一致
    assert mod.build_graph().to_json() == graph.to_json(), "build_graph 两次结果不一致"


# ---------------------------------------------------------------------- P2 回写


def test_record_without_graph_persists_and_reports_mastery(store):
    wb = _writeback_api()
    writer = wb.GraphWriteback(store)  # 契约：graph 参数可省
    out = writer.record("ver01-user", "C1.1", 88.0)

    assert isinstance(out, dict), f"record 应返回 dict，实际 {type(out)!r}"
    for key in ("skill_point_id", "score", "mastery", "graph_node"):
        assert key in out, f"record 返回缺契约字段 {key!r}：{out!r}"
    assert out["skill_point_id"] == "C1.1"
    assert float(out["score"]) == 88.0
    assert out["mastery"] == mastery_of(88.0).value, (
        f"mastery 应为 {mastery_of(88.0).value}（mastery_of 规则），实际 {out['mastery']!r}"
    )
    assert out["graph_node"], "record 返回的 graph_node 为空"

    row = store.abilities("ver01-user").get("C1.1")
    assert row is not None, "record 未写入 Store 能力表"
    assert 88.0 in (float(row.get("teach") or 0), float(row.get("real_v") or 0)), (
        f"record 未把分数写进 Store：{row!r}"
    )


def test_record_accepts_explicit_graph(store):
    graph_mod = _graph_api()
    wb = _writeback_api()
    writer = wb.GraphWriteback(store, graph=graph_mod.build_graph())
    out = writer.record("ver01-user", "C1.1", 60.0, source="practice")
    assert out["mastery"] == mastery_of(60.0).value
    assert out["graph_node"]


def test_weak_top3_ascending_and_graph_mastery_non_empty(store):
    wb = _writeback_api()
    writer = wb.GraphWriteback(store)

    user = "ver01-weak"
    scores = {sp.id: 91.0 - i for i, sp in enumerate(SKILL_POINTS)}
    for sp_id, score in scores.items():
        writer.record(user, sp_id, score)

    top = writer.weak_top3(user)
    assert isinstance(top, list), f"weak_top3 应返回 list，实际 {type(top)!r}"
    assert len(top) <= 3, f"weak_top3 最多 3 个，实际 {top!r}"
    assert len(top) == 3, f"61 个技能点全部有分时应返回 3 个，实际 {top!r}"

    expected = [sp.id for sp in reversed(SKILL_POINTS[-3:])]
    assert top == expected, f"weak_top3 未按分数升序：期望 {expected}，实际 {top!r}"

    mastery = writer.graph_mastery(user)
    assert isinstance(mastery, dict) and mastery, f"graph_mastery 应为非空 dict，实际 {mastery!r}"
    assert all(isinstance(v, (int, float)) for v in mastery.values()), (
        f"graph_mastery 值应为数值：{mastery!r}"
    )
