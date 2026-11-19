"""知识图谱包：域 / 维度 / 技能点三层结构（P1）。"""

from __future__ import annotations

from .graph import (
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

__all__ = [
    "DEFAULT_GRAPH_PATH",
    "EDGE_KINDS",
    "NODE_KINDS",
    "Edge",
    "Node",
    "SkillGraph",
    "build_graph",
    "dump_graph",
    "load_graph",
]
