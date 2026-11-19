"""Orchestra 角色目录。

目录是产品与调试面的单一来源：前端/答辩可以列出「有哪些声部」，
但实际执行仍以 Registry 中已绑定的 handler 为准。
"""

from __future__ import annotations

from .contracts import AgentSpec


TEACHING_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("teaching.router", "教学调度器", "teaching", ("route", "intent"),
              "判断本轮需要哪些协作者，不直接作答"),
    AgentSpec("teaching.retrieval", "知识召回", "teaching", ("knowledge", "bm25"),
              "从知识点基座检索依据，返回可追溯来源"),
    AgentSpec("teaching.context", "上下文装配", "teaching", ("context", "rubric"),
              "把六类资料装成一份可追溯上下文"),
    AgentSpec("teaching.profile", "画像顾问", "teaching", ("profile", "advice"),
              "读取掌握度与答题记录，给出薄弱点建议"),
    AgentSpec("teaching.teacher", "主讲 Agent（教师）", "teaching", ("teach", "synthesis"),
              "汇总各声部输入，输出一次带来源的讲解"),
    AgentSpec("teaching.quiz", "出题 Agent", "teaching", ("quiz", "rubric"),
              "按 Rubric 与掌握度出题"),
    AgentSpec("teaching.answer", "判分 Agent", "teaching", ("judge", "quiz"),
              "判题并给出针对性讲解"),
    AgentSpec("teaching.asset", "教研 Agent", "teaching", ("asset",),
              "生成讲义、实操指南、学习报告与错题本"),
    AgentSpec("teaching.review", "六帽审查", "teaching", ("review", "fact"),
              "白帽事实、黑帽逻辑等六顶帽子审查"),
)

# 六顶思考帽：每一顶都是独立 Agent（并行跑，蓝帽负责仲裁与最终判定）。
REVIEW_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("review.white", "白帽·事实核查", "review", ("facts", "knowledge"),
              "对照知识点基座与 Rubric 逐条核对材料事实"),
    AgentSpec("review.black", "黑帽·逻辑审计", "review", ("logic", "risk"),
              "反幻觉核心：找矛盾、过度承诺与无中生有"),
    AgentSpec("review.green", "绿帽·创意转化", "review", ("clarity", "example"),
              "判断是否讲得通俗、有例子，而不是照抄资料"),
    AgentSpec("review.yellow", "黄帽·激励引导", "review", ("motivation",),
              "判断是否正面鼓励、给可执行下一步"),
    AgentSpec("review.red", "红帽·个性适配", "review", ("persona", "difficulty"),
              "判断难度与语气是否贴合该学员掌握度"),
    AgentSpec("review.blue", "蓝帽·质量总控", "review", ("arbitrate", "verdict"),
              "汇总五顶帽子结论，给出最终合格/需修改判定"),
)

# 实训团队决策：行中事件处置时十类角色同批并行评估，再按写死规则仲裁。
# id 与 services/team_decision.py 的 TEAM_ROLES 一一对应；缺一个 decide() 就会少一票。
PRACTICE_TEAM_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("practice.team.customer", "客户接受度", "practice", ("acceptance", "customer"),
              "从该单客户人设出发判断处置方案能否被接受"),
    AgentSpec("practice.team.planner", "资源方可行性", "practice", ("feasibility", "cost"),
              "定制师视角判断资源能否协调、是否加价或换资源"),
    AgentSpec("practice.team.dmo", "地接可行性", "practice", ("feasibility", "dmo"),
              "地接社能否在目的地落地执行，库存与档期是否支持"),
    AgentSpec("practice.team.fleet", "车队可行性", "practice", ("feasibility", "fleet"),
              "车队/车辆能否调度，车型与营运资质是否满足"),
    AgentSpec("practice.team.guide", "司导现场执行", "practice", ("execution", "scene"),
              "判断司导现场是否可执行、需要什么支援"),
    AgentSpec("practice.team.driver", "司机现场执行", "practice", ("execution", "drive"),
              "司机视角判断实际驾驶与时间安排是否可行"),
    AgentSpec("practice.team.hotel", "酒店可行性", "practice", ("feasibility", "hotel"),
              "酒店房态与入住安排能否配合处置"),
    AgentSpec("practice.team.platform", "平台合规", "practice", ("compliance", "platform"),
              "平台规则、票据与派单口径是否允许该处置"),
    AgentSpec("practice.team.risk", "风控合规", "practice", ("risk", "compliance"),
              "安全/合规红线一票否决（无证、超时、违背客人明确约定）"),
    AgentSpec("practice.team.director", "总控评分口径", "practice", ("score", "rubric"),
              "从评分口径说明该处置对应哪些技能点与动作"),
)

PRACTICE_AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec("practice.hub", "资源大群调度", "practice", ("hub", "route"),
              "资源大群按订单与发言对象定位资源方"),
    AgentSpec("practice.customer", "客户 Agent", "practice", ("customer", "im"),
              "按订单人设与事实回复客户群"),
    AgentSpec("practice.supplier", "资源方 Agent", "practice", ("supplier", "quote"),
              "按订单报价、库存与档期回复"),
    AgentSpec("practice.guide", "司导 Agent", "practice", ("guide", "incident"),
              "只报现象、请定制师拍板"),
    AgentSpec("practice.phone_customer", "电话客户 Agent", "practice", ("customer", "phone"),
              "同一客户人设在电话通道的适配器；不是第二个客户"),
)

AGENT_SPECS: dict[str, AgentSpec] = {
    spec.id: spec for spec in (TEACHING_AGENTS + REVIEW_AGENTS + PRACTICE_AGENTS + PRACTICE_TEAM_AGENTS)
}


def get_spec(agent_id: str) -> AgentSpec | None:
    return AGENT_SPECS.get(agent_id)


def catalog() -> list[dict]:
    return [
        {
            "id": spec.id,
            "name": spec.name,
            "section": spec.section,
            "capabilities": list(spec.capabilities),
            "description": spec.description,
        }
        for spec in AGENT_SPECS.values()
    ]

