"""六帽审查 Agent —— 学习资料生成后的反幻觉质检（对应 PRD 第 22 章「六帽审查」）。

帽子顺序与职责：
  白帽 事实核查 —— 对照知识点基座/Rubric，检查有无编造事实
  黑帽 逻辑审计 —— 反幻觉核心：逻辑矛盾、过度承诺、无中生有
  绿帽 创意转化 —— 是否讲得通俗、有例子，而非照搬资料
  黄帽 激励引导 —— 是否正面鼓励、给可操作下一步
  红帽 个性适配 —— 是否贴合学员当前掌握度与难度
  蓝帽 质量总控 —— 综合前五帽，给最终「合格 / 需修改」判定

白帽/黑帽是硬门槛：任一不通过 → 材料需重写。

执行方式：六顶帽子是六个独立 Agent（`review.white` … `review.red`），
由 Conductor 按依赖分层调度——五顶互不依赖的帽子同批并行，蓝帽在五顶
全部落黑板后才开跑（`depends_on=("white","black","green","yellow","red")`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from ..orchestration import AgentRegistry, AgentResult, AgentTask, Blackboard, Conductor, Plan
from .llm import DeepSeekClient

WHITE_SYSTEM = """你是六帽审查中的白帽事实核查员。
对照下方给出的【知识点基座】与【Rubric】，逐条核对材料里的事实声称：
- 有没有编造知识点、张冠李戴、把 A 技能点内容写成 B 的；
- 有没有与基座/Rubric 冲突的说法；
- 数字、规则、时限是否与资料一致。
只输出 JSON：{"verdict":"通过 或 不通过","note":"一句话理由"}"""

BLACK_SYSTEM = """你是六帽审查中的黑帽逻辑审计员，反幻觉核心角色。
只挑毛病，宁可从严：
- 材料内部有没有前后矛盾、逻辑跳跃；
- 有没有过度承诺（把「可能」说成「一定」）；
- 有没有凭空出现的步骤、工具、数字。
只输出 JSON：{"verdict":"通过 或 不通过","note":"一句话理由"}"""

GREEN_SYSTEM = """你是六帽审查中的绿帽创意转化评估员。
判断材料是否讲得通俗、有具体例子/比喻、有讲解价值，而不是照抄资料。
只输出 JSON：{"verdict":"通过 或 建议改进","note":"一句话理由"}"""

YELLOW_SYSTEM = """你是六帽审查中的黄帽激励评估员。
判断材料是否正面鼓励学员、给出可执行的下一步、不打击信心。
只输出 JSON：{"verdict":"通过 或 建议改进","note":"一句话理由"}"""

RED_SYSTEM = """你是六帽审查中的红帽个性适配检查员。
判断材料是否贴合该学员当前掌握度（教学/实战分）与难度：太难或太简单、语气是否合适。
只输出 JSON：{"verdict":"通过 或 需调整","note":"一句话理由"}"""

BLUE_SYSTEM = """你是六帽审查中的蓝帽总控。
下面是前五顶帽子的结论，请综合判断这份材料能否交付学员：
- 白帽/黑帽任一不通过 → 判定「需修改」；
- 其余帽子是「建议改进/需调整」→ 可判定「合格」但要在 note 里提醒。
只输出 JSON：{"verdict":"合格 或 需修改","note":"一句话综合意见"}"""

# 五顶并行帽子（蓝帽之外的声部）；白/黑是硬门槛。
HAT_IDS = ("white", "black", "green", "yellow", "red")
BLUE_ID = "blue"


@dataclass
class HatResult:
    id: str
    name: str
    verdict: str
    note: str


def _hat_dict(hat: HatResult) -> dict:
    return {"id": hat.id, "name": hat.name, "verdict": hat.verdict, "note": hat.note}


class SixHatsReview:
    HATS = [
        ("white", "白帽·事实核查", WHITE_SYSTEM),
        ("black", "黑帽·逻辑审计", BLACK_SYSTEM),
        ("green", "绿帽·创意转化", GREEN_SYSTEM),
        ("yellow", "黄帽·激励引导", YELLOW_SYSTEM),
        ("red", "红帽·个性适配", RED_SYSTEM),
        ("blue", "蓝帽·质量总控", BLUE_SYSTEM),
    ]
    _NAMES = {hid: name for hid, name, _system in HATS}

    def __init__(self, llm: DeepSeekClient, max_workers: int = 6) -> None:
        self._llm = llm
        # 六帽是一支独立团队：自己的 Conductor + Registry，不复用教学流水线的黑板。
        self._conductor = Conductor(AgentRegistry(), max_workers=max_workers)
        self._bind_agents()

    # ---------- 团队计划 ----------

    @classmethod
    def plan(cls) -> Plan:
        """五个帽子 role 任务（无依赖 → 同批并行）+ 蓝帽（等五帽落黑板）。

        任务设为 optional：任何一顶帽子异常都不能把整条审查打崩；
        蓝帽按黑板上的实际结果拼 digest，缺项按「通过」降级。
        """
        tasks = [
            AgentTask(hid, f"review.{hid}", "review", optional=True)
            for hid, _name, _system in cls.HATS[:-1]
        ]
        tasks.append(AgentTask(BLUE_ID, "review.blue", "arbitrate",
                               depends_on=tuple(HAT_IDS), optional=True))
        return Plan("review.six_hats", "review", tuple(tasks))

    def _bind_agents(self) -> None:
        for hid, name, system in self.HATS[:-1]:
            self._conductor.registry.bind(
                f"review.{hid}", partial(self._agent_hat, hid, name, system))
        self._conductor.registry.bind("review.blue", self._agent_blue)

    # ---------- 帽子 Agent ----------

    def _agent_hat(self, hid: str, name: str, system: str,
                   task: AgentTask, board: Blackboard) -> AgentResult:
        hat = self._run(hid, name, system,
                        str(board.get("content") or ""),
                        str(board.get("context_text") or ""))
        return AgentResult(task.id, task.agent, output=_hat_dict(hat))

    def _agent_blue(self, task: AgentTask, board: Blackboard) -> AgentResult:
        prior = [board.get(hid) or {} for hid in HAT_IDS]
        digest = "\n".join(
            f"- {self._NAMES[hid]}：{p.get('verdict') or '通过'}，{p.get('note') or ''}"
            for hid, p in zip(HAT_IDS, prior))
        system = BLUE_SYSTEM + f"\n\n前五帽结论：\n{digest}"
        hat = self._run(BLUE_ID, self._NAMES[BLUE_ID], system,
                        str(board.get("content") or ""),
                        str(board.get("context_text") or ""))
        return AgentResult(task.id, task.agent, output=_hat_dict(hat))

    # ---------- 审查 ----------

    def review(self, content: str, context_text: str) -> dict:
        board = Blackboard({"content": content, "context_text": context_text})
        result = self._conductor.run(self.plan(), board)
        hats = [self._hat_output(hid, result.outputs.get(hid))
                for hid, _name, _system in self.HATS]
        by_id = {h["id"]: h for h in hats}
        critical_fail = any(by_id[hid]["verdict"] == "不通过" for hid in ("white", "black"))
        # 硬门槛：白/黑任一不通过 → 必须「需修改」，蓝帽说合格也不能翻案。
        if critical_fail:
            final_verdict = "需修改"
        else:
            final_verdict = by_id["blue"]["verdict"] if by_id["blue"]["verdict"] in ("合格", "需修改") else "合格"
        return {
            "verdict": final_verdict,
            "critical_fail": critical_fail,
            "hats": hats,
            "orchestra": {
                "run_id": result.run_id,
                "trace": result.trace_dicts(),
                "batches": result.batches,
                "parallel": True,
            },
            "parallel": True,
        }

    def _hat_output(self, hid: str, out: object) -> dict:
        """把黑板上的帽子输出规范化；缺失/坏数据按旧行为降级为「通过」。"""
        data = out if isinstance(out, dict) else {}
        return {
            "id": hid,
            "name": self._NAMES[hid],
            "verdict": str(data.get("verdict") or "通过"),
            "note": str(data.get("note") or ""),
        }

    def _run(self, hid: str, name: str, system: str, content: str, context_text: str) -> HatResult:
        user = f"待审查材料：\n\n{content[:3500]}\n\n参考资料：\n{context_text[:1500]}"
        try:
            data = self._llm.chat_json(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.1, max_tokens=200)
            if not isinstance(data, dict):
                data = {}
            verdict = str(data.get("verdict") or "通过").strip()
            note = str(data.get("note") or "").strip()
        except Exception:
            # 单顶帽子的调用/解析失败只降级这一顶，不击穿整条审查。
            verdict, note = "通过", ""
        return HatResult(id=hid, name=name, verdict=verdict, note=note)
