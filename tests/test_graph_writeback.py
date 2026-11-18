"""P2 评分回写图谱测试：能力表落库、短板 top-3、图谱掌握度与无图谱降级。"""

from __future__ import annotations

import os
import tempfile
from uuid import uuid4

import pytest

from tripcraft.contracts.enums import mastery_of
from tripcraft.services.graph_writeback import GraphWriteback
from tripcraft.storage.db import Store


@pytest.fixture
def store():
    s = Store(os.path.join(tempfile.gettempdir(), f"gw_{uuid4().hex}.sqlite"))
    yield s
    s.close()


# ---------------------------------------------------------------- record

def test_record_writes_ability(store):
    wb = GraphWriteback(store)
    out = wb.record("u1", "C1.1", 82.0)
    assert out["skill_point_id"] == "C1.1"
    assert out["score"] == 82.0
    assert out["mastery"] == "M4"
    assert out["graph_node"] == "C1.1"          # 无图谱时回退技能点 id
    row = store.abilities("u1")["C1.1"]
    assert row["real_v"] == 82.0
    assert row["real_source"] == "practice"


def test_record_honours_source(store):
    wb = GraphWriteback(store)
    wb.record("u1", "C6.1", 70, source="quiz")
    assert store.abilities("u1")["C6.1"]["real_source"] == "quiz"


@pytest.mark.parametrize(("score", "band"), [
    (59.9, "M1"), (60.0, "M2"), (70.0, "M3"), (80.0, "M4"), (90.0, "M5"),
])
def test_record_mastery_bands(store, score, band):
    wb = GraphWriteback(store)
    assert mastery_of(score).value == band
    assert wb.record("u1", "C2.1", score)["mastery"] == band


# ---------------------------------------------------------------- weak_top3

def test_weak_top3_lowest_first_and_tie_by_id(store):
    wb = GraphWriteback(store)
    for sp, score in (("C1.1", 90), ("C1.2", 40), ("C1.3", 70),
                      ("C1.4", 40), ("C1.5", 60)):
        wb.record("u1", sp, score)
    # 升序：40(C1.2)/40(C1.4)/60(C1.5)；同分按 id
    assert wb.weak_top3("u1") == ["C1.2", "C1.4", "C1.5"]


def test_weak_top3_returns_actual_count(store):
    wb = GraphWriteback(store)
    wb.record("u1", "C2.2", 66)
    wb.record("u1", "C2.1", 55)
    assert wb.weak_top3("u1") == ["C2.1", "C2.2"]
    assert wb.weak_top3("nobody") == []


def test_weak_top3_capped_at_three(store):
    wb = GraphWriteback(store)
    for i, score in enumerate((10, 20, 30, 40, 50)):
        wb.record("u1", f"C3.{i + 1}", score)
    assert wb.weak_top3("u1") == ["C3.1", "C3.2", "C3.3"]


# ---------------------------------------------------------------- graph_mastery

def test_graph_mastery_without_graph(store):
    wb = GraphWriteback(store)
    assert wb.graph_mastery("u1") == {}
    wb.record("u1", "C3.1", 77)
    assert wb.graph_mastery("u1") == {"C3.1": 77.0}
    assert wb.overlay("u1") == {"C3.1": 77.0}


class _Node:
    def __init__(self, node_id: str, kind: str = "skill") -> None:
        self.id = node_id
        self.kind = kind
        self.label = node_id
        self.source = "test"


class _StubGraph:
    def __init__(self) -> None:
        self.nodes = [_Node("skill:C4.1"), _Node("skill:C4.2"),
                      _Node("domain:D1", "domain")]

    def query(self, *, kind: str | None = None):
        return [n for n in self.nodes if kind is None or n.kind == kind]


def test_graph_records_node_mastery(store):
    graph = _StubGraph()
    wb = GraphWriteback(store, graph)
    out = wb.record("u1", "C4.1", 88)
    assert out["graph_node"] == "skill:C4.1"    # 命中真实节点 id
    assert out["mastery"] == "M4"
    assert next(n for n in graph.nodes if n.id == "skill:C4.1").mastery == 88.0
    assert wb.graph_mastery("u1") == {"C4.1": 88.0}


class _FrozenNode:
    """模拟 P1 的 frozen dataclass 节点：写入属性会抛 AttributeError。"""

    __slots__ = ("id", "kind")

    def __init__(self, node_id: str) -> None:
        self.id = node_id
        self.kind = "skill"


class _FrozenGraph:
    def __init__(self) -> None:
        self.nodes = [_FrozenNode("C5.1")]

    def query(self, *, kind: str | None = None):
        return list(self.nodes)


def test_frozen_graph_falls_back_to_overlay(store):
    wb = GraphWriteback(store, _FrozenGraph())
    wb.record("u1", "C5.1", 45)
    assert wb.graph_mastery("u1") == {"C5.1": 45.0}
    assert wb.overlay("u1") == {"C5.1": 45.0}


def test_invalid_graph_is_ignored(store):
    wb = GraphWriteback(store, graph=object())
    wb.record("u1", "C7.1", 73)
    assert wb.graph_mastery("u1") == {"C7.1": 73.0}


# ---------------------------------------------------------------- 无 graph 全链路

def test_full_path_without_graph(store):
    wb = GraphWriteback(store)
    for sp, score in (("C8.1", 85), ("C8.2", 35), ("C8.3", 55), ("C8.4", 95)):
        wb.record("u1", sp, score)
    assert wb.weak_top3("u1") == ["C8.2", "C8.3", "C8.1"]
    mastery = wb.graph_mastery("u1")
    assert len(mastery) == 4
    assert mastery["C8.2"] == 35.0
