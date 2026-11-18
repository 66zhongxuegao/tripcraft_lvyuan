"""P6 三库检索路由的验收测试：路由分类、结果字段、库名映射、空检索、top_k。"""

from __future__ import annotations

import pytest

from tripcraft.services import retrieval as retrieval_mod
from tripcraft.services import retrieval_router as router


# ---------------------------------------------------------------- 路由三类 + 未知

@pytest.mark.parametrize("task", ["客户报价单怎么开", "单据填写流程", "上线门控检查"])
def test_route_sop(task: str) -> None:
    assert router.route(task) == "sop"


@pytest.mark.parametrize("task", ["订单案例复盘", "客户投诉事件", "退款案例"])
def test_route_order(task: str) -> None:
    assert router.route(task) == "order"


@pytest.mark.parametrize("task", ["讲解知识点", "话术原理", "开场方法"])
def test_route_textbook(task: str) -> None:
    assert router.route(task) == "textbook"


@pytest.mark.parametrize("task", ["", "   ", "帮我查下天气", "zzz ???"])
def test_route_unknown_falls_back_to_textbook(task: str) -> None:
    assert router.route(task) == "textbook"


def test_route_keywords_cover_each_library() -> None:
    assert set(router.ROUTE_KEYWORDS) == set(router.LIBRARIES)
    for library in router.LIBRARIES:
        assert len(router.ROUTE_KEYWORDS[library]) >= 2


# ---------------------------------------------------------------- 库名映射

def test_library_names_mapping() -> None:
    assert router.LIBRARIES == ("textbook", "sop", "order")
    assert router.LIBRARY_NAMES == {
        "textbook": "教材库",
        "sop": "SOP库",
        "order": "订单案例库",
    }


# ---------------------------------------------------------------- 检索结果

def test_retrieve_result_fields_and_scenario() -> None:
    task = "报价流程"
    results = router.retrieve(task, "C1.1", "开场")
    assert results, "C1.1 知识点基座应能命中开场相关片段"
    expected_scenario = f"{router.LIBRARY_NAMES['sop']} · {task} · C1.1"
    for item in results:
        assert set(item) == {"text", "source", "library", "scenario"}
        assert isinstance(item["text"], str) and item["text"]
        assert item["library"] == router.route(task) == "sop"
        assert item["scenario"] == expected_scenario
        assert item["source"].startswith("C1.1·") and item["source"].split("·", 1)[1]


def test_retrieve_uses_library_from_task() -> None:
    order_results = router.retrieve("订单案例复盘", "C1.1", "开场")
    assert order_results and all(r["library"] == "order" for r in order_results)
    book_results = router.retrieve("讲解知识点", "C1.1", "开场")
    assert book_results and all(r["library"] == "textbook" for r in book_results)


# ---------------------------------------------------------------- 空检索与异常

def test_retrieve_unknown_skill_point_returns_empty_list() -> None:
    assert router.retrieve("报价流程", "NOT_A_SKILL_POINT", "开场") == []


def test_retrieve_top_k_zero_returns_empty_list() -> None:
    assert router.retrieve("报价流程", "C1.1", "开场", top_k=0) == []


def test_retrieve_empty_sp_returns_empty_list() -> None:
    assert router.retrieve("报价流程", "", "开场") == []


def test_retrieve_swallows_retriever_failure(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("retriever 初始化失败")

    monkeypatch.setattr(retrieval_mod, "get_retriever", _boom)
    assert router.retrieve("报价流程", "C1.1", "开场") == []


# ---------------------------------------------------------------- top_k

def test_top_k_limits_results() -> None:
    two = router.retrieve("报价流程", "C1.1", "", top_k=2)
    one = router.retrieve("报价流程", "C1.1", "", top_k=1)
    assert len(two) == 2
    assert len(one) == 1


def test_top_k_default_is_six() -> None:
    results = router.retrieve("报价流程", "C1.1", "")
    assert 1 <= len(results) <= 6
