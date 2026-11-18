"""实训团队决策 —— 行中事件处置的十类角色并行评审 + 写死规则仲裁。

十类角色由 Conductor **同批并行**执行（互不依赖，因此批次只有一层）：
客户接受度 / 定制师资源方可行性 / 地接可行性 / 车队可行性 / 司导现场执行 /
司机现场执行 / 酒店可行性 / 平台合规 / 风控合规 / 总控评分口径。
角色只投自己那一票；最终判定由 ``_arbitrate`` 的写死规则给出，模型不参与裁决：

1. 风控「不接受」一票否决（verdict=驳回，veto_by=practice.team.risk）；
2. 否则按权重 customer .20 / planner .15 / dmo .12 / fleet .10 / guide .12 /
   driver .08 / hotel .08 / platform .05 / risk .05 / director .05 加权：
   接受=1.0、有条件接受=0.6、不接受=0.0、弃权=跳过（不计入分母）；
3. score >= 0.7 且没有任何附加条件 → 接受；
   0.45 <= score < 0.7，或 score >= 0.7 但存在非空 condition → 有条件接受
   （合并所有非空 condition）；
   score < 0.45 → 驳回。

「有条件接受」的判定口径：带条件的同意不是无条件同意，因此只要任一角色给了
condition，即使加权分已经过 0.7 也落在有条件接受档。

``llm is None`` 时不联网：十类角色一律按规则投「接受」，reason 写明
「未配置模型，按规则评审」，保证离线/未配置模型时仍可演示。
"""

from __future__ import annotations

import json
import uuid

from ..orchestration import AgentResult, AgentTask, Blackboard, Conductor, Plan

# (task_id, agent_id, 角色名)。task_id 同时是权重键；角色名会写进 system 提示词。
# 角色名必须互不为子串：离线/假模型按「角色名」分派，子串互吃会让两票立场串味。
TEAM_ROLES: tuple[tuple[str, str, str], ...] = (
    ("customer", "practice.team.customer", "客户接受度"),
    ("planner", "practice.team.planner", "资源方可行性"),
    ("dmo", "practice.team.dmo", "地接可行性"),
    ("fleet", "practice.team.fleet", "车队可行性"),
    ("guide", "practice.team.guide", "司导现场执行"),
    ("driver", "practice.team.driver", "司机现场执行"),
    ("hotel", "practice.team.hotel", "酒店可行性"),
    ("platform", "practice.team.platform", "平台合规"),
    ("risk", "practice.team.risk", "风控合规"),
    ("director", "practice.team.director", "总控评分口径"),
)

# 每个角色的「评审口径」：离线 provider（scenario_service.ScenarioLLM._team_decision）
# 只认这五个既有关键词，十类角色靠这里一一命中，offline provider 无需改动。
ROLE_DIMENSIONS: dict[str, str] = {
    "customer": "客户接受度",
    "planner": "资源方可行性",
    "dmo": "资源方可行性",
    "fleet": "资源方可行性",
    "guide": "司导现场执行",
    "driver": "司导现场执行",
    "hotel": "资源方可行性",
    "platform": "风控合规",
    "risk": "风控合规",
    "director": "教练评分口径",
}

# 十类角色权重之和必须为 1.0（tests/test_team_decision_10_roles.py 断言）。
WEIGHTS: dict[str, float] = {
    "customer": 0.20, "planner": 0.15, "dmo": 0.12, "fleet": 0.10, "guide": 0.12,
    "driver": 0.08, "hotel": 0.08, "platform": 0.05, "risk": 0.05, "director": 0.05,
}

STANCE_ACCEPT = "接受"
STANCE_CONDITIONAL = "有条件接受"
STANCE_REJECT = "不接受"
STANCE_ABSTAIN = "弃权"
STANCES = (STANCE_ACCEPT, STANCE_CONDITIONAL, STANCE_REJECT, STANCE_ABSTAIN)
STANCE_VALUE = {STANCE_ACCEPT: 1.0, STANCE_CONDITIONAL: 0.6, STANCE_REJECT: 0.0}

ACCEPT_AT = 0.7
CONDITIONAL_AT = 0.45
RISK_AGENT = "practice.team.risk"

DECISION_KIND = "团队决策"
EVENT_TYPE = "team_decision"
VERDICT_ACCEPT = "接受"
VERDICT_CONDITIONAL = "有条件接受"
VERDICT_REJECT = "驳回"

NO_LLM_REASON = "未配置模型，按规则评审"


def _system_prompt(role: str, agent_id: str = "", dimension: str = "") -> str:
    """角色提示词：必须含「团队决策」、本角色名与评审口径，离线 provider 据此分派。

    角色名用「」包住，与同属一个评审口径的其它角色区分；``agent_id`` 让英文 id
    也出现在提示词里（排障与目录对账用）。
    """
    id_part = f"（{agent_id}）" if agent_id else ""
    dimension_part = f"评审口径：{dimension}。" if dimension else ""
    return (
        f"你是定制游实训「团队决策」评审团中的「{role}」角色{id_part}。"
        "团队决策只评审这一条行中突发事件的处置方案是否可行，不写别的。"
        f"本角色只从「{role}」的角度投一票，不得替其他角色发言。"
        f"{dimension_part}"
        "只输出一个 JSON 对象，字段固定："
        '{"stance":"接受|有条件接受|不接受|弃权","reason":"一句话","condition":"可选"}；'
        "stance 只能取这四个值之一；reason 必须是一句话；"
        "condition 只在 stance=有条件接受 时填写，否则留空。"
    )


def _user_prompt(order_id: str, incident: dict, plan_text: str) -> str:
    return (
        f"订单号：{order_id}\n"
        f"事件：{incident.get('title') or ''}（{incident.get('code') or ''}）\n"
        f"步骤：{incident.get('step') or ''}\n"
        f"渠道：{incident.get('channel') or ''}\n"
        f"事件描述：{incident.get('body') or ''}\n"
        f"处置方案：{(plan_text or '').strip() or '（定制师未填写具体方案）'}"
    )


def _arbitrate(votes: list[dict]) -> dict:
    """写死规则的仲裁：风控一票否决，否则加权计分。"""
    risk = next(vote for vote in votes if vote["agent"] == RISK_AGENT)
    total_weight = 0.0
    weighted = 0.0
    for vote in votes:
        if vote["stance"] == STANCE_ABSTAIN:
            continue
        weight = float(vote["weight"])
        total_weight += weight
        weighted += weight * STANCE_VALUE[vote["stance"]]
    score = weighted / total_weight if total_weight else 0.0

    conditions: list[str] = []
    for vote in votes:
        condition = str(vote.get("condition") or "").strip()
        if condition and condition not in conditions:
            conditions.append(condition)

    veto = risk["stance"] == STANCE_REJECT
    if veto:
        verdict = VERDICT_REJECT
    elif score >= ACCEPT_AT and not conditions:
        verdict = VERDICT_ACCEPT
    elif score >= CONDITIONAL_AT:
        verdict = VERDICT_CONDITIONAL
    else:
        verdict = VERDICT_REJECT

    return {
        "verdict": verdict,
        "veto": veto,
        "veto_by": RISK_AGENT if veto else "",
        "score": score,
        "conditions": conditions,
    }


class TeamDecisionService:
    """行中事件处置：十类角色并行评审 + 规则仲裁 + 证据/事件落库。"""

    def __init__(self, store, practice=None, llm=None, conductor: Conductor | None = None) -> None:
        self._store = store
        self._practice = practice
        self._llm = llm
        # 十类角色同批并行：自建 Conductor 时并发度取角色数，批内不留排队。
        self._conductor = conductor or Conductor(max_workers=len(TEAM_ROLES))
        self._bind_agents()

    def _bind_agents(self) -> None:
        for _task_id, agent_id, _role in TEAM_ROLES:
            self._conductor.registry.bind(agent_id, self._review)

    # ---------- 角色执行 ----------

    def _review(self, task: AgentTask, board: Blackboard) -> AgentResult:
        """一个角色的评审：调模型拿 JSON 立场；未配置模型时给确定性立场。"""
        payload = task.payload or {}
        role = str(payload.get("role") or "")
        if self._llm is None:
            output = {"stance": STANCE_ACCEPT, "reason": NO_LLM_REASON, "condition": ""}
            return AgentResult(task.id, task.agent, output=output)

        messages = [
            {"role": "system", "content": _system_prompt(
                role, task.agent, ROLE_DIMENSIONS.get(task.id, ""))},
            {"role": "user", "content": _user_prompt(
                str(payload.get("order_id") or ""), payload.get("incident") or {},
                str(payload.get("plan") or ""))},
        ]
        data = self._llm.chat_json(messages, temperature=0.2)
        if not isinstance(data, dict):
            raise ValueError(f"{role} 未返回 JSON 对象")
        stance = str(data.get("stance") or "").strip()
        if stance not in STANCES:
            raise ValueError(f"{role} 返回了无效立场: {stance!r}")
        output = {
            "stance": stance,
            "reason": str(data.get("reason") or "").strip(),
            "condition": (str(data.get("condition") or "").strip()
                          if stance == STANCE_CONDITIONAL else ""),
        }
        return AgentResult(task.id, task.agent, output=output)

    # ---------- 对外入口 ----------

    def decide(self, order_id: str, incident_id: str, plan_text: str) -> dict:
        """对一条行中事件的处置方案做团队决策，返回固定结构的决策 JSON。"""
        if not self._store.order(order_id):
            raise ValueError(f"未找到订单: {order_id}")
        incident = next(
            (row for row in self._store.incidents(order_id)
             if str(row.get("incident_id")) == str(incident_id)),
            None,
        )
        if incident is None:
            raise ValueError(f"未找到事件: {incident_id}")

        plan_text = plan_text or ""
        tasks = tuple(
            AgentTask(
                task_id, agent_id, "团队决策",
                {"role": role, "order_id": order_id, "incident_id": str(incident_id),
                 "incident": dict(incident), "plan": plan_text},
                optional=True,
            )
            for task_id, agent_id, role in TEAM_ROLES
        )
        result = self._conductor.run(
            Plan("practice.team_decision", "practice", tasks),
            Blackboard({"order_id": order_id, "incident_id": str(incident_id)}),
        )
        if not result.ok:
            raise RuntimeError(f"团队决策编排失败: {result.error}")

        trace_by_id = {event.task_id: event for event in result.trace}
        votes: list[dict] = []
        for task_id, agent_id, role in TEAM_ROLES:
            event = trace_by_id.get(task_id)
            output = result.outputs.get(task_id)
            stance = (output or {}).get("stance") if isinstance(output, dict) else None
            ok = bool(event and event.ok and stance in STANCES)
            votes.append({
                "agent": agent_id,
                "role": role,
                "stance": stance if ok else STANCE_ABSTAIN,
                "weight": WEIGHTS[task_id],
                "reason": str((output or {}).get("reason") or "").strip() if ok
                          else ((event.error if event is not None else "") or "角色未返回结果"),
                "condition": str((output or {}).get("condition") or "").strip() if ok else "",
                "ok": ok,
                "ms": int(event.duration_ms) if event is not None else 0,
            })

        ruling = _arbitrate(votes)
        verdict = ruling["verdict"]
        score = ruling["score"]
        decision_id = f"td-{uuid.uuid4().hex[:8]}"
        evidence_text = self._evidence_text(incident, verdict, score, votes)
        if self._practice is not None:
            evidence_id = self._practice.record_evidence(
                order_id, DECISION_KIND, evidence_text, step=str(incident.get("step") or ""))
        else:
            evidence_id = self._store.add_evidence(
                order_id, DECISION_KIND, str(incident.get("step") or ""), "", evidence_text)

        batches = result.batch_dicts()
        decision = {
            "decision_id": decision_id,
            "order_id": order_id,
            "incident_id": str(incident_id),
            "verdict": verdict,
            "conditions": list(ruling["conditions"]),
            "votes": votes,
            "rules": {
                "veto": bool(ruling["veto"]),
                "veto_by": str(ruling["veto_by"]),
                "score": round(score, 4),
                "weights": dict(WEIGHTS),
                "thresholds": {"accept": ACCEPT_AT, "conditional": CONDITIONAL_AT},
            },
            "orchestra": {
                "run_id": result.run_id,
                "trace": result.trace_dicts(),
                "batches": batches,
                "parallel": any(batch["parallel"] for batch in batches),
            },
            "evidence_id": "" if evidence_id is None else str(evidence_id),
        }
        self._store.add_event(order_id, EVENT_TYPE, decision)
        return decision

    @staticmethod
    def _evidence_text(incident: dict, verdict: str, score: float,
                       votes: list[dict]) -> str:
        """证据正文：事件标题 + verdict + score + 十个角色 stance 缺一不可。"""
        stances = "；".join(f"{vote['role']}={vote['stance']}" for vote in votes)
        return (
            f"事件：{incident.get('title') or incident.get('code') or ''}\n"
            f"团队决策：{verdict}（score={score:.2f}）\n"
            f"角色立场：{stances}"
        )

    def latest_decision(self, order_id: str, incident_id: str) -> dict | None:
        """最近一次该事件的团队决策 payload；没有则 None（供 GET 读取）。"""
        found: dict | None = None
        for row in self._store.events(order_id):
            if row.get("type") != EVENT_TYPE:
                continue
            try:
                payload = json.loads(row.get("payload") or "{}")
            except (TypeError, ValueError):
                continue
            if str(payload.get("incident_id")) == str(incident_id):
                found = payload
        return found
