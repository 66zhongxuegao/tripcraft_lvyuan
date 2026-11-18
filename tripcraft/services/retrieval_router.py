"""三库检索路由 —— 按任务语义把检索导向教材库 / SOP 库 / 订单案例库。

契约见 `.dsh-run/ppt-spec.md` 的 P6：

- 三个库与中文名固定为 ``LIBRARIES`` / ``LIBRARY_NAMES``；
- ``route(task)`` 关键词路由：报价/单据/流程/门控等→``sop``；订单/案例/客户/事件等→``order``；
  其余（含空任务、未知任务）→``textbook``；
- ``retrieve(task, sp, query, top_k)`` 复用 ``services/retrieval.py`` 的 Retriever，
  给每条命中补上库标与可读场景上下文；retriever 抛错或无命中时返回空列表，不向上抛。

本模块只在 ``retrieve`` 内延迟 import 具体检索服务，避免模块级循环依赖。
"""

from __future__ import annotations

LIBRARIES: tuple[str, ...] = ("textbook", "sop", "order")
LIBRARY_NAMES: dict[str, str] = {
    "textbook": "教材库",
    "sop": "SOP库",
    "order": "订单案例库",
}
DEFAULT_LIBRARY: str = "textbook"

# 每类至少 2 个关键词；ROUTE_PRIORITY 决定同时命中时的归属：
# 操作类任务（报价/单据/流程/门控）优先落到 SOP 库，其次订单案例，最后教材。
ROUTE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sop": ("报价", "单据", "流程", "门控", "审批", "合规"),
    "order": ("订单", "案例", "客户", "事件", "退款", "投诉"),
    "textbook": ("概念", "定义", "原理", "知识点", "方法", "话术"),
}
ROUTE_PRIORITY: tuple[str, ...] = ("sop", "order", "textbook")


def route(task: str) -> str:
    """按任务描述关键词返回库名；无命中或空任务落到教材库。"""
    text = (task or "").strip()
    if not text:
        return DEFAULT_LIBRARY
    for library in ROUTE_PRIORITY:
        if any(keyword in text for keyword in ROUTE_KEYWORDS[library]):
            return library
    return DEFAULT_LIBRARY


def retrieve(task: str, sp: str, query: str, top_k: int = 6) -> list[dict]:
    """检索技能点 ``sp`` 的知识片段，返回带库标与场景上下文的结果列表。

    每条结果固定四个字段：``text`` / ``source`` / ``library`` / ``scenario``。
    检索器异常、无命中、``sp`` 为空或 ``top_k <= 0`` 时返回 ``[]``。
    """
    if top_k <= 0 or not sp:
        return []

    library = route(task)
    try:
        from .retrieval import get_retriever

        hits = get_retriever().search(sp, query or "", top_k=top_k)
    except Exception:  # noqa: BLE001 —— 契约要求检索失败降级为空列表，不向教学链路抛错
        return []

    task_text = (task or "").strip()
    scenario = f"{LIBRARY_NAMES[library]} · {task_text} · {sp}"
    results: list[dict] = []
    for chunk, _score in hits:
        text = str(getattr(chunk, "text", "") or "").strip()
        if not text:
            continue
        results.append({
            "text": text,
            "source": f"{getattr(chunk, 'sp', sp)}·{getattr(chunk, 'label', '')}",
            "library": library,
            "scenario": scenario,
        })
        if len(results) >= top_k:
            break
    return results
