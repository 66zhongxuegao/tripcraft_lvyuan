"""Conductor —— Multi-Agent Orchestra 的总指挥。

职责只有四件事：
1. 按依赖**分层**调度角色：同层（互不依赖）并行跑，上游完成后才跑下游；
2. 检查依赖，避免角色在上下文未就绪时抢跑；
3. 把角色结果写入 Blackboard；
4. 为每次调用留下 Trace（含批次号，能看出哪些角色是并行投票的）。

Conductor 不生成业务内容，不直接调用模型。
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .contracts import (
    AgentResult,
    AgentTask,
    Blackboard,
    Plan,
    PlanBuilder,
    RunResult,
    TraceEvent,
)
from .registry import AgentRegistry

# 一次并行批最多开几个线程：六帽 5+1、实训团队决策 10 类角色，留到 20 为答辩「并发加速」口径。
MAX_WORKERS = 20


class Conductor:
    def __init__(self, registry: AgentRegistry | None = None, max_workers: int = MAX_WORKERS) -> None:
        self.registry = registry or AgentRegistry()
        self.max_workers = max(1, int(max_workers))

    # ---------- 依赖分层 ----------

    @staticmethod
    def levels(plan: Plan) -> list[list[AgentTask]]:
        """把 Plan 按依赖排成层级；同层任务互不依赖，可并行。

        依赖缺失或存在环时抛 ValueError（由调用方转成 RunResult.error）。
        """
        known = {task.id for task in plan.tasks}
        done: set[str] = set()
        pending = list(plan.tasks)
        levels: list[list[AgentTask]] = []
        while pending:
            ready = [task for task in pending if all(dep in done for dep in task.depends_on)]
            if not ready:
                missing = sorted({dep for task in pending for dep in task.depends_on if dep not in known})
                if missing:
                    raise ValueError("缺少上游任务: " + ", ".join(missing))
                raise ValueError("任务依赖存在环: " + ", ".join(task.id for task in pending))
            levels.append(ready)
            done |= {task.id for task in ready}
            pending = [task for task in pending if task.id not in done]
        return levels

    # ---------- 执行 ----------

    def _execute(self, task: AgentTask, board: Blackboard) -> tuple[AgentResult, int]:
        started = time.perf_counter()
        try:
            bound = self.registry.get(task.agent)
            result = bound.handler(task, board)
            if not isinstance(result, AgentResult):
                result = AgentResult(task.id, task.agent, ok=True, output=result)
        except Exception as exc:  # 角色失败不能击穿整条主链
            result = AgentResult(task.id, task.agent, ok=False,
                                 error=f"{type(exc).__name__}: {exc}")
        return result, int((time.perf_counter() - started) * 1000)

    def run(self, plan: Plan, blackboard: Blackboard | None = None) -> RunResult:
        board = blackboard or Blackboard()
        run_id = uuid.uuid4().hex[:12]
        outputs: dict[str, Any] = {}
        trace: list[TraceEvent] = []
        seq_map = {task.id: index + 1 for index, task in enumerate(plan.tasks)}

        try:
            levels = self.levels(plan)
        except ValueError as exc:
            return RunResult(False, outputs, trace, str(exc), run_id)

        batches: list[tuple[str, ...]] = []
        for batch_index, batch in enumerate(levels):
            batches.append(tuple(task.id for task in batch))
            workers = max(1, min(self.max_workers, len(batch)))
            if len(batch) == 1:
                outcomes = {batch[0].id: self._execute(batch[0], board)}
            else:
                outcomes: dict[str, tuple[AgentResult, int]] = {}
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="orchestra") as pool:
                    futures = {pool.submit(self._execute, task, board): task for task in batch}
                    for future in as_completed(futures):
                        task = futures[future]
                        outcomes[task.id] = future.result()

            failed: AgentTask | None = None
            for task in batch:
                result, duration = outcomes[task.id]
                trace.append(TraceEvent(
                    run_id=run_id, seq=seq_map[task.id], task_id=task.id, agent=task.agent,
                    action=task.action, ok=result.ok, duration_ms=duration,
                    error=result.error, evidence=tuple(result.evidence),
                    meta={"section": plan.section, "batch": batch_index,
                          "batch_size": len(batch), **result.meta}))
                if result.ok:
                    outputs[task.id] = result.output
                    board.set(task.id, result.output)
                    board.merge(result.meta)
                elif task.optional:
                    continue
                elif failed is None:
                    failed = task

            if failed is not None:
                error = outcomes[failed.id][0].error or f"{failed.agent} 执行失败"
                trace.sort(key=lambda event: event.seq)
                return RunResult(False, outputs, trace, error, run_id)

        trace.sort(key=lambda event: event.seq)
        return RunResult(True, outputs, trace, "", run_id, batches=tuple(batches))

    def run_dynamic(self, planner_task: AgentTask, build_plan: PlanBuilder,
                    blackboard: Blackboard | None = None) -> RunResult:
        """先让调度器角色产出意图，再按意图生成可执行 Plan。"""
        board = blackboard or Blackboard()
        first = self.run(Plan("orchestra.plan", "orchestra", (planner_task,)), board)
        if not first.ok:
            return first
        try:
            plan = build_plan(first.outputs.get(planner_task.id), board)
        except Exception as exc:
            message = f"PlanBuilder 失败: {type(exc).__name__}: {exc}"
            return RunResult(False, dict(first.outputs), list(first.trace), message,
                             first.run_id, batches=first.batches)

        second = self.run(plan, board)
        return RunResult(
            ok=second.ok,
            outputs={**first.outputs, **second.outputs},
            trace=[*first.trace, *second.trace],
            error=second.error,
            run_id=first.run_id,
            batches=first.batches + second.batches,
        )
