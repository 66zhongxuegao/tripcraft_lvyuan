"""TripCraft M0 最小 API —— 暴露数据契约与状态机骨架。

M0 阶段：内存存储，仅用于验证「契约 + 状态机」闭环。
后续 M1 起接入数据库与真实业务。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from tripcraft.contracts import culture_bridges as cb
from tripcraft.contracts import skill_points as sp
from tripcraft.contracts import skill_points as sp_module
from tripcraft.contracts.deliverables import Deliverable
from tripcraft.contracts.enums import (
    DIMENSION_NAMES,
    DIMENSION_WEIGHTS,
    MASTERY_NAMES,
    STEP_NAMES,
    DeliverableKind,
    Dimension,
    StepId,
    mastery_of,
)
from tripcraft.contracts.profile import LearnerProfile, dimension_value
from tripcraft.contracts.rubric import RUBRICS
from tripcraft.contracts.task import TaskInstance
from tripcraft.engine.state_machine import Run
from tripcraft.agents.llm import DeepSeekClient, LLMError
from tripcraft.agents import profiler as profile_agent
from tripcraft.services.call_service import CallService
from tripcraft.services.director_service import EVENTS as DIRECTOR_EVENTS
from tripcraft.services.director_service import INCIDENT_RULES, DirectorService
from tripcraft.services.deliverable_service import DeliverableError, DeliverableService
from tripcraft.services.guard_service import GuardService
from tripcraft.services.finance_service import FinanceService
from tripcraft.services.plan_service import PlanService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.services.workflow import ACTION_LABELS, MANUAL_ACTIONS
from tripcraft.mcp.server import MCPServer
from tripcraft.calibration import audit_dataset, load_samples, run_calibration
from tripcraft.services.s2_session import S2Session
from tripcraft.services.practice_service import GROUP_STEP, PracticeService
from tripcraft.services.thread_service import ThreadService
from tripcraft.services.tools_service import ToolsService
from tripcraft.voice.bridge import VoiceBridge
from tripcraft.services.visit_monitor import VISIT_MONITOR, VisitMonitorMiddleware
from tripcraft.storage import Store


# ---------------- 请求模型（必须定义在模块级，否则 FastAPI 无法解析） ----------------

class CreateRun(BaseModel):
    user_id: str = "u1"
    template_id: str = "tpl1"
    inbound: bool = True
    language: str = "中文"


class FlagBody(BaseModel):
    name: str
    value: bool = True


class DeliverableBody(BaseModel):
    kind: DeliverableKind
    step: StepId
    payload: dict = {}


class RollbackBody(BaseModel):
    to_step: StepId
    reason: str = ""


class TranslateBody(BaseModel):
    text: str
    target: str = "English"


class AbilityBody(BaseModel):
    skill_point_id: str
    value: float
    field: str = "teach"      # teach = 教学侧；real = 实战侧


class AssessmentBody(BaseModel):
    user_id: str = "u-demo"
    answers: list[dict] = []
    language: str = "中文"


class CreateS2(BaseModel):
    user_id: str = "u1"
    inbound: bool = True
    language: str = "中文"


class SendMessage(BaseModel):
    text: str


class ThreadMsg(BaseModel):
    user_id: str = "u-demo"
    text: str


class ThreadAssetBody(BaseModel):
    user_id: str = "u-demo"
    kind: str


class ThreadQuizAnswer(BaseModel):
    user_id: str = "u-demo"
    question: dict = {}
    answer: str = ""


class SupplierBody(BaseModel):
    kind: str
    request: str
    order_id: str = ""          # 带上订单：口径与群里一致，并登记为询价证据


class DeliverableBody2(BaseModel):
    kind: str
    content: str
    customer: str = "客户"
    order_id: str = ""


class CallSay(BaseModel):
    text: str


class DeliverableSubmit(BaseModel):
    values: dict = {}
    file_ids: list[str] = []
    targets: list[str] = []      # 发在给谁：会话 ID 列表（客户群 / 地接群 / 司导群 / 单聊）


class DeliverablePreview(BaseModel):
    values: dict = {}


class PlanBody(BaseModel):
    values: dict = {}
    note: str = ""


class PlanSendBody(BaseModel):
    targets: list[str] = []


class TemplateBody(BaseModel):
    user_id: str = "u-demo"
    name: str
    sections: list = []
    kind: str = "plan"


class FileUpload(BaseModel):
    filename: str
    mime: str = "application/octet-stream"
    data_b64: str
    order_id: str = ""
    deliverable_id: str = ""


class ActionBody(BaseModel):
    action: str


class DispatchGenerateBody(BaseModel):
    user_id: str = "u-demo"
    count: int = 1
    language: str = ""        # ""=随机各国；否则只生成说这种语言的客源


class CalibrationBody(BaseModel):
    repeats: int = 1
    limit: int = 0


class GuardBody(BaseModel):
    kind: str
    content: str
    order_id: str = ""
    geo: bool = False


class DirectorEventBody(BaseModel):
    type: str
    payload: dict = {}


class ReviewBody(BaseModel):
    decision: str = "accept"
    score: float | None = None


class SupplierStateBody(BaseModel):
    user_id: str = "u-demo"
    kind: str
    availability: str = ""
    price_factor: float = 0.0
    note: str = ""


class ItineraryBody(BaseModel):
    stops: list[str] = []


class FinanceDecideBody(BaseModel):
    bearer: str                 # 我方 | 资源方 | 客户
    note: str = ""


class ImMsg(BaseModel):
    sender: str
    role: str = "me"
    content: str
    kind: str = "text"            # text / file / card
    payload: dict = {}
    order_id: str = ""            # 资源大群/自建群里，告诉后端"我在弄哪一单"


class ContactBody(BaseModel):
    order_id: str
    kind: str


class RenameBody(BaseModel):
    name: str


class RemarkBody(BaseModel):
    remark: str = ""


class MembersBody(BaseModel):
    names: list[str] = []


class ImSessionBody(BaseModel):
    user_id: str = "u-demo"
    order_id: str = ""
    name: str
    kind: str = "客户"
    members: list[str] = []


def create_app() -> FastAPI:
    app = FastAPI(title="TripCraft · 旅鸢", version="0.1.0")
    runs: dict[str, Run] = {}

    # ---------------- 公网演示访问监控（只记日志，不改业务） ----------------

    app.add_middleware(VisitMonitorMiddleware)

    profiles: dict[str, LearnerProfile] = {}

    # ---------------- 健康检查 ----------------

    @app.get("/")
    def health():
        return {"status": "ok", "service": "TripCraft", "version": "0.1.0"}

    # ---------------- 文化桥（十大客源国共通点） ----------------

    @app.get("/learn/culture-bridges")
    def culture_bridges():
        return [cb.as_payload(b) for b in cb.all_bridges()]

    @app.get("/learn/culture-bridges/{code}")
    def culture_bridge(code: str):
        b = cb.get(code)
        if not b:
            raise HTTPException(404, f"未找到文化桥: {code}")
        return cb.as_payload(b)

    @app.post("/learn/translate")
    def learn_translate(body: TranslateBody):
        """把一段内容翻成目标语言，保持 Markdown 结构与专有名词不变。"""
        text = (body.text or "").strip()
        if not text:
            raise HTTPException(400, "没有要翻译的内容")
        try:
            llm = get_llm()
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        system = (
            f"你是翻译引擎，把用户给的内容翻译成{body.target}。\n"
            "硬性要求：\n"
            "1. 完整保留原有 Markdown 结构：标题层级、列表符号、加粗、表格、引用、代码块、链接一律不动；\n"
            "2. 只翻译自然语言；代码、URL、数字、单位、专有名词保持原样；\n"
            "3. 不要添加解释、不要输出「以下是翻译」之类的话；\n"
            "4. 直接输出译文本身。"
        )
        try:
            out = llm.chat([{"role": "system", "content": system},
                            {"role": "user", "content": text}],
                           temperature=0.2, max_tokens=2400)
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        return {"target": body.target, "text": (out or "").strip()}

    # ---------------- 数据契约 ----------------

    @app.get("/contracts/steps")
    def steps():
        return [{"id": s.value, "name": STEP_NAMES[s]} for s in StepId]

    @app.get("/contracts/dimensions")
    def dimensions():
        return [
            {"id": d.value, "name": DIMENSION_NAMES[d], "weight": DIMENSION_WEIGHTS[d]}
            for d in Dimension
        ]

    @app.get("/contracts/skill-points")
    def skill_points(dimension: str | None = None):
        items = sp.SKILL_POINTS
        if dimension:
            try:
                dim = Dimension(dimension)
            except ValueError:
                raise HTTPException(400, f"未知维度: {dimension}")
            items = sp.by_dimension(dim)
        return [
            {
                "id": x.id, "name": x.name, "dimension": x.dimension.value,
                "checkpoint": x.checkpoint.value, "material": x.material,
                "steps": [s.value for s in x.steps], "target": x.target,
            }
            for x in items
        ]

    @app.get("/contracts/skill-points/{skill_point_id}")
    def skill_point(skill_point_id: str):
        x = sp.SKILL_POINTS_BY_ID.get(skill_point_id)
        if x is None:
            raise HTTPException(404, f"未知技能点: {skill_point_id}")
        return {
            "id": x.id, "name": x.name, "dimension": x.dimension.value,
            "checkpoint": x.checkpoint.value, "material": x.material,
            "steps": [s.value for s in x.steps], "target": x.target,
        }

    @app.get("/contracts/rubric/{skill_point_id}")
    def rubric(skill_point_id: str):
        r = RUBRICS.get(skill_point_id)
        if r is None:
            raise HTTPException(404, "该技能点的 Rubric 尚未产出（M0 只有 C2.2 示例）")
        return {
            "skill_point_id": r.skill_point_id,
            "steps": [s.value for s in r.steps],
            "target": r.target,
            "trigger": r.trigger,
            "anchors": [{"level": a.level.value, "behavior": a.behavior} for a in r.anchors],
            "positive": r.positive,
            "negative": r.negative,
            "evidence_required": r.evidence_required,
            "knowledge": r.knowledge,
        }

    # ---------------- 演练与状态机 ----------------

    def snapshot(run: Run) -> dict:
        outcome = run.gate()
        return {
            "instance_id": run.instance.id,
            "current_step": run.instance.current_step.value,
            "current_step_name": STEP_NAMES[run.instance.current_step],
            "order_status": run.instance.status.value,
            "steps": [
                {"step": s.value, "name": STEP_NAMES[s], "status": run.steps[s].status.value}
                for s in StepId
            ],
            "gate": {"passed": outcome.passed, "reasons": outcome.reasons, "hard": outcome.hard},
            "deliverables": [d.kind.value for d in run.deliverables],
            "flags": dict(run.flags),
            "log": run.log[-20:],
        }

    def get_run(run_id: str) -> Run:
        run = runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"未找到演练: {run_id}")
        return run

    @app.post("/runs")
    def create_run(body: CreateRun):
        inst = TaskInstance(id=f"run-{len(runs) + 1}", template_id=body.template_id,
                            user_id=body.user_id, inbound=body.inbound, language=body.language)
        run = Run(instance=inst)
        runs[inst.id] = run
        profiles.setdefault(body.user_id, LearnerProfile(user_id=body.user_id))
        return snapshot(run)

    @app.get("/runs/{run_id}")
    def get_run_state(run_id: str):
        return snapshot(get_run(run_id))

    @app.post("/runs/{run_id}/advance")
    def advance(run_id: str):
        run = get_run(run_id)
        result = run.advance()
        return {"ok": result.ok, "from": result.from_step.value, "to": result.to_step.value,
                "reason": result.reason, "hard_blocked": result.hard_blocked, "state": snapshot(run)}

    @app.post("/runs/{run_id}/rollback")
    def rollback(run_id: str, body: RollbackBody):
        run = get_run(run_id)
        result = run.rollback(body.to_step, body.reason)
        return {"ok": result.ok, "from": result.from_step.value, "to": result.to_step.value,
                "reason": result.reason, "state": snapshot(run)}

    @app.post("/runs/{run_id}/flags")
    def set_flag(run_id: str, body: FlagBody):
        run = get_run(run_id)
        run.set_flag(body.name, body.value)
        return snapshot(run)

    @app.post("/runs/{run_id}/deliverables")
    def add_deliverable(run_id: str, body: DeliverableBody):
        run = get_run(run_id)
        d = Deliverable(id=f"d-{len(run.deliverables) + 1}", instance_id=run.instance.id,
                        kind=body.kind, step=body.step, payload=body.payload)
        run.add_deliverable(d)
        return snapshot(run)

    # ---------------- S2 垂直切片（M1） ----------------

    s2_sessions: dict[str, S2Session] = {}
    llm_holder: dict = {"client": None}

    def get_llm():
        if llm_holder["client"] is None:
            llm_holder["client"] = DeepSeekClient()
        return llm_holder["client"]

    @app.post("/s2/sessions")
    def create_s2(body: CreateS2):
        try:
            llm = get_llm()
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        sid = f"s2-{len(s2_sessions) + 1}"
        sess = S2Session(user_id=body.user_id, llm=llm, inbound=body.inbound,
                         instance_id=sid, language=body.language)
        opening = sess.start()
        s2_sessions[sid] = sess
        profiles.setdefault(body.user_id, LearnerProfile(user_id=body.user_id))
        return {"session_id": sid, "customer_opening": opening, "snapshot": sess.snapshot()}

    @app.post("/s2/sessions/{sid}/messages")
    def s2_send(sid: str, body: SendMessage):
        sess = s2_sessions.get(sid)
        if sess is None:
            raise HTTPException(404, "未找到会话")
        reply = sess.send(body.text)
        return {"customer_reply": reply, "snapshot": sess.snapshot()}

    @app.post("/s2/sessions/{sid}/finish")
    def s2_finish(sid: str):
        sess = s2_sessions.get(sid)
        if sess is None:
            raise HTTPException(404, "未找到会话")
        prof = profiles.setdefault(sess.user_id, LearnerProfile(user_id=sess.user_id))
        report = sess.finish(profile=prof)
        values = prof.values()
        report["profile"] = {
            "dimensions": {d.value: {"name": DIMENSION_NAMES[d], "value": dimension_value(values, d)} for d in Dimension},
            "weak_points": prof.weak_points(),
        }
        return report

    @app.get("/s2/sessions/{sid}")
    def s2_get(sid: str):
        sess = s2_sessions.get(sid)
        if sess is None:
            raise HTTPException(404, "未找到会话")
        return sess.snapshot()

    # ---------------- 实战：订单 / 完成条件 / 评分 ----------------

    store = Store()
    practice = PracticeService(store)
    practice.seed("u-demo")
    threads_holder: dict = {"svc": None}

    def get_threads():
        if threads_holder["svc"] is None:
            try:
                llm = get_llm()
            except LLMError:
                llm = None
            threads_holder["svc"] = ThreadService(store, llm)
        return threads_holder["svc"]

    @app.get("/practice/steps")
    def practice_steps():
        from tripcraft.services.practice_service import ORDER_STEPS, STAGE_HINTS
        return {"steps": ORDER_STEPS, "hints": STAGE_HINTS}

    @app.get("/practice/orders")
    def practice_orders(user_id: str = "u-demo"):
        return practice.list_orders(user_id)

    @app.get("/practice/dispatch/brief")
    def dispatch_brief(user_id: str = "u-demo"):
        """本单简报：画像 → 目标技能点 + 各难度旋钮档位（给前端解释用）。"""
        return practice.brief_for(user_id)

    @app.post("/practice/dispatch/generate")
    def dispatch_generate(body: DispatchGenerateBody):
        """按画像生成新派单（随机游客由画像反推，不是随机出题）。"""
        try:
            llm = get_llm()
        except LLMError:
            llm = None
        return practice.generate_dispatch(body.user_id, llm=llm, count=body.count,
                                          language=body.language)

    @app.get("/contracts/markets")
    def contracts_markets():
        """客源市场清单（前端"客源语言"下拉用同一份口径，避免两边写死不一致）。"""
        from tripcraft.agents.scenario import LANGUAGES, SOURCE_MARKETS
        return {"languages": list(LANGUAGES),
                "markets": [{"market": k, "language": v[0], "documents": v[1], "complexity": v[2]}
                            for k, v in SOURCE_MARKETS.items()]}

    @app.get("/practice/orders/available")
    def practice_available(user_id: str = "u-demo"):
        """可抢订单（消息中心「待接单」持续刷新用）。"""
        return practice.available_orders(user_id)

    @app.get("/practice/orders/{order_id}")
    def practice_order(order_id: str):
        detail = practice.order_detail(order_id)
        if not detail:
            raise HTTPException(404, f"未找到订单: {order_id}")
        return detail

    @app.get("/practice/orders/{order_id}/steps")
    def practice_order_steps(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return {"order_id": order_id, "steps": practice.order_steps(order_id)}

    @app.get("/practice/orders/{order_id}/contacts")
    def practice_order_contacts(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        rows = store.contacts(order_id)
        return [{"time": c["at"], "kind": c["kind"], "status": c["status"],
                 "has_record": bool(c["has_record"]), "detail": c["detail"]} for c in rows]

    @app.get("/practice/messages")
    def practice_messages(user_id: str = "u-demo"):
        return practice.messages(user_id)

    @app.get("/practice/orders/{order_id}/gates")
    def practice_gates(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return practice.gate_report(order_id)

    # ---------------- 交付物工作台（契约 → 渲染 → 校验 → 按对象投递） ----------------

    deliverable_svc = DeliverableService(store=store, practice=practice)

    def get_deliverables() -> DeliverableService:
        if deliverable_svc._guard is None:
            deliverable_svc._guard = get_guard()
        if deliverable_svc._tools is None:
            deliverable_svc._tools = get_tools()
        return deliverable_svc

    @app.get("/deliverables/specs")
    def deliverable_specs():
        return {"deliverables": DeliverableService.specs()}

    @app.get("/practice/orders/{order_id}/deliverables")
    def order_deliverables(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return get_deliverables().list_for_order(order_id)

    @app.get("/practice/orders/{order_id}/deliverables/{did}")
    def order_deliverable(order_id: str, did: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        try:
            return get_deliverables().detail(order_id, did)
        except DeliverableError as exc:
            raise HTTPException(404, str(exc))

    @app.post("/practice/orders/{order_id}/deliverables/{did}/preview")
    def order_deliverable_preview(order_id: str, did: str, body: DeliverablePreview):
        """按契约渲染当前填写内容（不提交、不校验），用于右侧实时预览。"""
        from tripcraft.contracts.deliverables_spec import render, resolve
        spec = resolve(did)
        order = store.order(order_id)
        if spec is None or not order:
            raise HTTPException(404, "交付物或订单不存在")
        payload = json.loads(order["payload"] or "{}")
        ctx = {"order_id": order_id, "customer": order["customer"], "destination": order["destination"],
               "source_market": payload.get("source_market", ""), "language": payload.get("language", "中文")}
        return {"rendered": render(spec, body.values, ctx), "missing": DeliverableService.validate(did, body.values)}

    @app.post("/practice/orders/{order_id}/deliverables/{did}/export.pdf")
    def order_deliverable_pdf(order_id: str, did: str, body: DeliverablePreview):
        """导出 PDF：复用工作台同一份渲染结果，前端不再拼一遍版式。"""
        from urllib.parse import quote

        from fastapi.responses import Response

        from tripcraft.contracts.deliverables_spec import render, resolve
        from tripcraft.services.pdf_service import markdown_to_pdf

        spec = resolve(did)
        order = store.order(order_id)
        if spec is None or not order:
            raise HTTPException(404, "交付物或订单不存在")
        payload = json.loads(order["payload"] or "{}")
        ctx = {"order_id": order_id, "customer": order["customer"], "destination": order["destination"],
               "source_market": payload.get("source_market", ""), "language": payload.get("language", "中文")}
        pdf = markdown_to_pdf(render(spec, body.values, ctx), title=spec.title,
                              order_id=order_id, customer=order["customer"])
        name = f"{spec.title}-{order_id}.pdf"
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name)})

    @app.post("/practice/orders/{order_id}/deliverables/{did}")
    def order_deliverable_submit(order_id: str, did: str, body: DeliverableSubmit):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        try:
            return get_deliverables().submit(order_id, did, body.values, body.file_ids,
                                             targets=body.targets)
        except DeliverableError as exc:
            raise HTTPException(400, str(exc))

    # ---------------- 方案版本：创建方案 → 发送方案 → 客户已读（PRD 28.31） ----------------

    plan_svc = PlanService(store=store, practice=practice, deliverable=deliverable_svc)

    def get_plans() -> PlanService:
        if plan_svc._deliverable is None:
            plan_svc._deliverable = get_deliverables()
        if plan_svc._tools is None:
            plan_svc._tools = get_tools()
        return plan_svc

    @app.get("/practice/orders/{order_id}/plans")
    def order_plans(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        plans = get_plans().list(order_id)
        return {"order_id": order_id, "plans": plans,
                "unread": sum(1 for p in plans if p["status"] == "已发送" and not p["read"])}

    @app.post("/practice/orders/{order_id}/plans")
    def order_plan_create(order_id: str, body: PlanBody):
        try:
            return {"ok": True, "plan": get_plans().create(order_id, body.values, body.note)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.put("/practice/orders/{order_id}/plans/{plan_id}")
    def order_plan_update(order_id: str, plan_id: str, body: PlanBody):
        try:
            return {"ok": True, "plan": get_plans().update(order_id, plan_id, body.values, body.note)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/practice/orders/{order_id}/plans/{plan_id}/send")
    def order_plan_send(order_id: str, plan_id: str, body: PlanSendBody):
        try:
            return get_plans().send(order_id, plan_id, body.targets)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/practice/orders/{order_id}/plans/{plan_id}/confirm")
    def order_plan_confirm(order_id: str, plan_id: str):
        try:
            return get_plans().confirm(order_id, plan_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    # 方案小节模板：学员自己写的标题存下来，下次创建方案直接用
    @app.get("/practice/doc-templates")
    def doc_templates(user_id: str = "u-demo", kind: str = "plan"):
        rows = store.doc_templates(user_id, kind)
        return {"templates": [{"template_id": r["template_id"], "name": r["name"],
                               "sections": json.loads(r["sections"] or "[]"),
                               "updated_at": r["updated_at"]} for r in rows]}

    @app.post("/practice/doc-templates")
    def doc_template_save(body: TemplateBody):
        if not body.name.strip():
            raise HTTPException(400, "模板名不能为空")
        tid = f"tpl-{body.user_id}-{body.kind}-{abs(hash(body.name)) % 100000}"
        store.save_doc_template(tid, body.user_id, body.name.strip(), body.sections, body.kind)
        return {"ok": True, "template_id": tid}

    @app.delete("/practice/doc-templates/{template_id}")
    def doc_template_delete(template_id: str):
        store._exec("DELETE FROM doc_template WHERE template_id=?", (template_id,))
        return {"ok": True}

    @app.post("/deliverables/files")
    def deliverable_upload(body: FileUpload):
        import base64 as _b64
        try:
            data = _b64.b64decode(body.data_b64, validate=False)
        except Exception:
            raise HTTPException(400, "文件内容不是合法 base64")
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(413, "文件过大（上限 8MB）")
        fid = f"f-{int(time.time() * 1000) % 100000000}-{abs(hash(body.filename)) % 10000}"
        store.save_file(fid, body.order_id, body.deliverable_id, body.filename,
                        body.mime, len(data), data)
        return {"file_id": fid, "filename": body.filename, "size": len(data)}

    @app.get("/deliverables/files/{file_id}")
    def deliverable_file(file_id: str):
        from fastapi.responses import Response
        row = store.file(file_id)
        if not row:
            raise HTTPException(404, "文件不存在")
        return Response(content=row["data"], media_type=row["mime"] or "application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'})

    # ---------------- 流程通关驱动（D-033） ----------------

    @app.post("/practice/orders/{order_id}/grab")
    def practice_grab(order_id: str):
        detail = practice.order_detail(order_id)
        if not detail:
            raise HTTPException(404, f"未找到订单: {order_id}")
        if detail["status"] in ("禁用", "已派他人"):
            raise HTTPException(409, "该订单已取消或已被接走，无法抢单")
        try:
            out = practice.record_action(order_id, "grab", {"by": "u-demo"})
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        out["dispatch"] = practice.dispatch_info(order_id)
        return out

    @app.post("/practice/orders/{order_id}/actions")
    def practice_action(order_id: str, body: ActionBody):
        try:
            return practice.record_action(order_id, body.action)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/practice/orders/{order_id}/actions")
    def practice_actions(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        rows = store.actions(order_id)
        return {"order_id": order_id,
                "actions": [{"action": r["action"], "at": r["at"],
                             "label": ACTION_LABELS.get(r["action"], r["action"])} for r in rows],
                "manual_options": list(MANUAL_ACTIONS),
                "labels": ACTION_LABELS}

    @app.get("/practice/orders/{order_id}/flow")
    def practice_flow(order_id: str):
        return practice.flow_progress(order_id)

    @app.get("/practice/orders/{order_id}/scores")
    def practice_scores(order_id: str):
        return practice.order_scores(order_id)

    # ---------------- 人工校准集（PRD 第 25 章） ----------------

    @app.get("/calibration")
    def calibration_status():
        run = store.latest_calibration()
        rows = load_samples()
        return {
            "gate": practice.calibration_gate(),
            "thresholds": practice.thresholds(),
            "samples": len(rows),
            "dataset": audit_dataset(rows),
            "latest": (None if not run else {
                "run_id": run["run_id"], "samples": run["samples"], "predictions": run["predictions"],
                "agreement": run["agreement"], "evidence_accuracy": run["evidence_accuracy"],
                "stability": run["stability"], "passed": bool(run["passed"]),
                "threshold_confidence": run["threshold_conf"],
                "threshold_delta": run["threshold_delta"],
                "created_at": run["created_at"],
            }),
            "history": [{"run_id": r["run_id"], "agreement": r["agreement"],
                         "evidence_accuracy": r["evidence_accuracy"], "passed": bool(r["passed"]),
                         "created_at": r["created_at"]} for r in store.calibration_runs(5)],
        }

    @app.get("/calibration/samples")
    def calibration_samples():
        rows = load_samples()
        return {"count": len(rows),
                "items": [{"id": s["id"], "skill_point_ids": s["skill_point_ids"],
                           "source_market": s.get("source_market", ""), "language": s.get("language", ""),
                           "difficulty": s.get("difficulty", ""),
                           "labels": [{"skill_point_id": l["skill_point_id"], "level": l["level"]}
                                      for l in s.get("labels", [])]} for s in rows]}

    @app.post("/calibration/run")
    def calibration_run(body: CalibrationBody):
        try:
            llm = get_llm()
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        samples = load_samples()
        if body.limit:
            samples = samples[:body.limit]
        if not samples:
            raise HTTPException(400, "没有校准样本")
        try:
            report = run_calibration(llm, samples, repeats=max(1, body.repeats))
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        store.add_calibration_run(
            report["run_id"], report["samples"], report["predictions"],
            report["agreement"], report["evidence_accuracy"], report["stability"],
            report["threshold"]["confidence"], report["threshold"]["boundary_delta"],
            report["passed"], report)
        return report

    # ---------------- MCP 封装（PRD 23 / D-011） ----------------
    # 外部数据与资源能力统一按 MCP 工具契约暴露：复赛换真实接口只替换下面的 handler。

    _knowledge_dir = Path(__file__).resolve().parents[2] / "data" / "knowledge"

    def _mcp_knowledge(args: dict):
        sp = str(args.get("skill_point_id", ""))
        f = _knowledge_dir / f"{sp}.json"
        if not f.exists():
            return {"error": f"未找到技能点知识底座: {sp}"}
        return json.loads(f.read_text(encoding="utf-8"))

    def _mcp_deliverable(args: dict):
        kind = str(args.get("kind", ""))
        content = str(args.get("content", ""))
        order_id = str(args.get("order_id", ""))
        report = get_guard().check(kind, content, order_id or None)
        if report["blocked"]:
            return {"blocked": True, "guard": report,
                    "message": "交付物未通过校验，未投递给客户"}
        out = get_tools().deliverable_feedback(kind, content, str(args.get("customer") or "客户"))
        out["guard"] = report
        if order_id:
            out["evidence_id"] = practice.record_evidence(
                order_id, kind, f"【交付物·{kind}】\n{content.strip()}",
                ref=f"mcp-{int(time.time() * 1000)}")
        return out

    mcp_handlers = {
        "weather": lambda a: get_tools().weather(str(a["city"])),
        "route": lambda a: get_tools().route(str(a["origin"]), str(a["destination"])),
        "itinerary": lambda a: get_tools().check_itinerary(list(a["stops"])),
        "fx": lambda a: get_tools().fx(str(a.get("base") or "CNY"), a.get("quotes") or None),
        "supplier": lambda a: get_tools().supplier(str(a["kind"]), str(a["request"])),
        "deliverable": _mcp_deliverable,
        "guard": lambda a: get_guard().check(str(a["kind"]), str(a["content"]),
                                             str(a.get("order_id") or "") or None,
                                             geo=bool(a.get("geo"))),
        "director": lambda a: get_director().emit(str(a["order_id"]), str(a["type"])),
        "order": lambda a: practice.order_detail(str(a["order_id"])) or {"error": "未找到订单"},
        "coverage": lambda a: practice.coverage(str(a["order_id"])),
        "knowledge": _mcp_knowledge,
    }
    mcp = MCPServer(mcp_handlers)

    @app.get("/mcp/tools")
    def mcp_tools():
        return MCPServer.catalog()

    @app.post("/mcp")
    def mcp_rpc(body: dict):
        """MCP 核心 JSON-RPC 入口（initialize / tools/list / tools/call / ping）。"""
        resp = mcp.handle(body if isinstance(body, dict) else {})
        if resp is None:
            return {"jsonrpc": "2.0", "id": None, "result": {}}
        return resp

    # ---------------- 双层拦截网（PRD 24.3） ----------------

    guard = GuardService(store=store, practice=practice)

    def get_guard() -> GuardService:
        if guard._llm is None:
            try:
                guard._llm = get_llm()
            except LLMError:
                pass
        return guard

    @app.post("/guard/check")
    def guard_check(body: GuardBody):
        return get_guard().check(body.kind, body.content, body.order_id or None, geo=body.geo)

    @app.post("/practice/orders/{order_id}/guard")
    def guard_order(order_id: str, body: GuardBody):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return get_guard().check(body.kind, body.content, order_id, geo=body.geo)

    # ---------------- 导演总线（事件 → 规则化注入突发事件） ----------------

    @app.get("/practice/director/catalog")
    def director_catalog():
        return {"events": list(DIRECTOR_EVENTS), "rules": director.catalog()}

    @app.post("/practice/orders/{order_id}/events")
    def director_emit(order_id: str, body: DirectorEventBody):
        try:
            return get_director().emit(order_id, body.type, body.payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/practice/orders/{order_id}/dispatch")
    def order_dispatch(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return practice.dispatch_info(order_id)

    @app.get("/practice/orders/{order_id}/timeline")
    def director_timeline(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return get_director().timeline(order_id)

    @app.get("/practice/orders/{order_id}/coverage")
    def practice_coverage(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return practice.coverage(order_id)

    @app.get("/practice/orders/{order_id}/reviews")
    def practice_reviews(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return practice.pending_reviews(order_id)

    @app.post("/practice/orders/{order_id}/reviews/{sp}")
    def practice_review(order_id: str, sp: str, body: ReviewBody):
        try:
            return practice.review_score(order_id, sp, body.decision, body.score)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    # ---------------- 通话（订单绑定的实时客户 Agent） ----------------

    director = DirectorService(store=store, practice=practice)
    practice.attach_director(director)   # 学员动作自动进总线（D-047）

    def get_director() -> DirectorService:
        if director._llm is None:
            try:
                director._llm = get_llm()
            except LLMError:
                pass
        return director

    call_svc = CallService(store=store, practice=practice)

    def get_call() -> CallService:
        if call_svc._llm is None:
            try:
                call_svc._llm = get_llm()
            except LLMError:
                pass
        return call_svc

    @app.post("/practice/orders/{order_id}/call")
    def start_call(order_id: str):
        detail = practice.order_detail(order_id)
        if not detail:
            raise HTTPException(404, f"未找到订单: {order_id}")
        if detail["status"] == "禁用":
            raise HTTPException(409, "该订单已取消，无法发起通话")
        try:
            sess = get_call().start(order_id, detail["customer"], detail["destination"],
                                   detail.get("source_market", "香港"), detail.get("language", "中文"),
                                   detail.get("personality", ""))
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        return sess.snapshot()

    @app.get("/practice/call/{sid}")
    def call_snapshot(sid: str):
        sess = get_call().get(sid)
        if sess is None:
            raise HTTPException(404, "未找到通话会话")
        return sess.snapshot()

    @app.post("/practice/call/{sid}/messages")
    def call_say(sid: str, body: CallSay):
        try:
            line = get_call().say(sid, body.text)
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        if line is None:
            raise HTTPException(404, "未找到通话会话")
        sess = get_call().get(sid)
        return {"reply": line, **(sess.snapshot() if sess else {})}

    @app.post("/practice/call/{sid}/end")
    def call_end(sid: str):
        snap = get_call().end(sid)
        if snap is None:
            raise HTTPException(404, "未找到通话会话")
        if snap.get("turns"):
            practice.record_action(snap["order_id"], "first_call", {"session_id": sid})
        return snap

    # ---------------- 实战评分（真实评分 Agent → 画像写回） ----------------

    @app.post("/practice/orders/{order_id}/score")
    def practice_score_order(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        try:
            llm = get_llm()
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        try:
            report = practice.score_order(order_id, llm)
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        if not report.get("ok"):
            raise HTTPException(409, report.get("error", "评分失败"))
        return report

    @app.get("/practice/orders/{order_id}/evidence")
    def practice_evidence(order_id: str):
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        rows = practice.evidence(order_id)
        return [{"kind": r["kind"], "step": r["step"], "ref": r["ref"],
                 "at": r["created_at"], "chars": len(r["text"] or "")} for r in rows]

    # ---------------- 学习地图（真实掌握度） ----------------

    @app.get("/learn/map")
    def learn_map(user_id: str = "u-demo"):
        ab = store.abilities(user_id)
        director = get_director()
        # 技能点 → 它涉及的事件（教学掌握度 ≥60 才解锁；和事件无关的点留空）
        events_of: dict[str, list] = {}
        for r in INCIDENT_RULES:
            for sp in r["skill_points"]:
                events_of.setdefault(sp, []).append(r)
        dims_out = []
        for d in Dimension:
            pts = []
            for spo in sp_module.SKILL_POINTS:
                if spo.dimension is not d:
                    continue
                row = ab.get(spo.id, {})
                teach = float(row.get("teach") or 0)
                evs = []
                for r in events_of.get(spo.id, []):
                    opened = any(float((ab.get(x) or {}).get("teach") or 0) >= director.TEACH_UNLOCK
                                 for x in r["skill_points"])
                    evs.append({"code": r["code"], "title": r["title"], "step": r["step"],
                                "channel": r["channel"], "unlocked": opened})
                pts.append({"id": spo.id, "name": spo.name, "checkpoint": spo.checkpoint.value,
                            "teach": teach, "real": float(row.get("real_v") or 0),
                            "events": evs})
            avg_t = round(sum(p["teach"] for p in pts) / len(pts), 1) if pts else 0
            avg_r = round(sum(p["real"] for p in pts) / len(pts), 1) if pts else 0
            dims_out.append({"id": d.value, "name": DIMENSION_NAMES[d], "teach": avg_t, "real": avg_r, "points": pts})
        all_t = [p["teach"] for d in dims_out for p in d["points"]]
        all_r = [p["real"] for d in dims_out for p in d["points"]]
        return {"dimensions": dims_out,
                "overall": {"teach": round(sum(all_t) / len(all_t), 1) if all_t else 0,
                            "real": round(sum(all_r) / len(all_r), 1) if all_r else 0}}

    # ---------------- 工具台 ----------------

    tools = ToolsService(store=store)

    def get_tools():
        if tools._llm is None:
            try:
                tools._llm = get_llm()
            except LLMError:
                pass
        return tools

    @app.get("/tools/weather")
    def tools_weather(city: str, date: str | None = None):
        try:
            return get_tools().weather(city, date)
        except Exception as exc:
            raise HTTPException(503, f"天气查询失败: {exc}")

    def _waypoints(raw: str) -> list[str]:
        import re as _re
        return [w.strip() for w in _re.split(r"[,，、]", raw or "") if w.strip()]

    @app.get("/tools/route")
    def tools_route(origin: str, destination: str, mode: str = "driving", waypoints: str = ""):
        """真实路线：驾车（可带途经点）/ 步行 / 骑行 / 公交。"""
        try:
            return get_tools().route(origin, destination, mode, _waypoints(waypoints))
        except Exception as exc:
            raise HTTPException(503, f"路线查询失败: {exc}")

    @app.get("/tools/poi/tips")
    def tools_poi_tips(q: str, city: str = ""):
        """输入联想（高德输入提示）：前端输入框的下拉候选。"""
        try:
            return {"tips": get_tools().poi_tips(q, city)}
        except Exception as exc:
            raise HTTPException(503, f"联想查询失败: {exc}")

    @app.get("/tools/map")
    def tools_map(origin: str, destination: str, mode: str = "driving", waypoints: str = "",
                  size: str = "900*520"):
        """静态地图 PNG（高德底图 + 起终点与途经点标记 + 驾车路线）。"""
        from fastapi.responses import Response
        try:
            png = get_tools().map_image(origin, destination, mode, _waypoints(waypoints), size)
        except Exception as exc:
            raise HTTPException(503, f"地图生成失败: {exc}")
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "no-cache"})

    @app.post("/tools/itinerary/check")
    def tools_itinerary(body: ItineraryBody):
        try:
            return get_tools().check_itinerary(body.stops)
        except Exception as exc:
            raise HTTPException(503, f"行程核验失败: {exc}")

    @app.get("/tools/fx")
    def tools_fx(base: str = "CNY", quotes: str = ""):
        try:
            want = [q.strip() for q in quotes.split(",") if q.strip()] or None
            return get_tools().fx(base, want)
        except Exception as exc:
            raise HTTPException(503, f"汇率查询失败: {exc}")

    @app.get("/tools/supplier/state")
    def tools_supplier_state():
        return {"states": get_tools().supplier_states()}

    @app.post("/tools/supplier/state")
    def tools_supplier_state_set(body: SupplierStateBody):
        try:
            state = get_tools().set_supplier_state(body.kind, {
                "availability": body.availability,
                "price_factor": body.price_factor,
                "note": body.note,
            })
            return {"kind": body.kind, "state": state, "states": get_tools().supplier_states()}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/tools/supplier")
    def tools_supplier(body: SupplierBody):
        # 带订单：走该单的资源方事实（与群里同一个口径），并登记为询价证据
        if body.order_id:
            out = get_supplier().ask(body.order_id, body.kind, body.request)
            if out is not None:
                q = out.get("quote") or {}
                reply = {"kind": body.kind, "request": body.request, "reply": out["content"],
                         "price": q.get("summary", ""), "availability": q.get("availability", ""),
                         "note": q.get("note", ""), "deferred": bool(out.get("deferred"))}
                practice.record_evidence(
                    body.order_id, "供应商询价",
                    f"【询价·{body.kind}】\n我问：{body.request.strip()}\n"
                    f"{out['sender']}：{out['content']}",
                    ref=f"supplier-{int(time.time() * 1000)}")
                return reply
        try:
            return get_tools().supplier(body.kind, body.request)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(503, str(exc))
        except LLMError as exc:
            raise HTTPException(503, str(exc))

    @app.post("/tools/deliverable")
    def tools_deliverable(body: DeliverableBody2):
        # 第一层先跑拦截网：被拦下的交付物不投递给客户、不登记证据
        report = get_guard().check(body.kind, body.content, body.order_id or None)
        if report["blocked"]:
            return {"blocked": True, "guard": report, "reply": "",
                    "sentiment": "", "asks": [],
                    "message": "交付物未通过校验，未投递给客户；请按下方问题修改后重新提交。"}
        try:
            out = get_tools().deliverable_feedback(body.kind, body.content, body.customer)
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        out["guard"] = report
        if body.order_id:
            ev_id = practice.record_evidence(
                body.order_id, body.kind,
                f"【交付物·{body.kind}】\n{body.content.strip()}",
                ref=f"deliverable-{int(time.time() * 1000)}")
            out["evidence_id"] = ev_id
            # 只登记门槛里真正存在的动作（并非每种交付物都有关卡动作）
            for act in (f"deliverable:{body.kind}", f"guard_pass:{body.kind}"):
                if act in ACTION_LABELS:
                    practice.record_action(body.order_id, act)
            out["gates"] = practice.gate_report(body.order_id)
        return out

    @app.post("/practice/im/sessions/{sid}/messages")
    def im_send(sid: str, body: ImMsg):
        sess0 = store.session(sid) or {}
        state = get_supplier().room_state(sess0.get("order_id") or "", sid)
        if body.role == "me" and state["locked"]:
            raise HTTPException(409, state["hint"])
        store.add_im_message(sid, body.sender, body.role, body.content,
                             kind=body.kind, payload=body.payload)
        # 学员在群里回话 = 对注入事件的「可观测反应」→ B 型考点算覆盖
        reacted = get_director().react(sid) if body.role == "me" else []
        reply, error, fin = None, "", None
        if body.role == "me":
            try:
                reply = get_supplier().respond(sid, body.content, body.order_id)
            except Exception as exc:      # 不再静默吞掉：把原因带回去，便于定位
                error = f"{type(exc).__name__}: {exc}"
            if reply:
                store.add_im_message(sid, reply["sender"], "other", reply["content"])
            # 学员在资源方群里谈追偿/赔付 → 按写死比例定责（协调赔偿的考核入口）
            try:
                fin = get_finance().maybe_attribute_from_chat(
                    (store.session(sid) or {}).get("order_id", ""),
                    (store.session(sid) or {}).get("kind", ""), body.content)
            except Exception:
                fin = None
            if fin and fin.get("message"):
                store.add_im_message(sid, f"{reply['sender'] if reply else '资源方'}", "other",
                                     fin["message"])
            # 群聊也是证据：询价过程与事件应对必须能进评分（PRD 21.2 每分必有证据）
            # 资源大群没有订单号（学员级），挂到"最近在跟的一单"上，否则大群里的询价白问
            sess = store.session(sid) or {}
            oid = sess.get("order_id") or body.order_id or ""
            if not oid:
                latest = get_supplier()._latest_order(sess.get("user_id") or "u-demo")
                oid = (latest or {}).get("order_id") or ""
            used = reply["content"] if reply else "（对方未应答）"
            practice.record_evidence(
                oid, "im",
                f"【群聊·{sess.get('name') or '聊天群'}】订单 {sess.get('order_id') or '—'}\n"
                f"我：{body.content.strip()}\n{reply['sender'] if reply else '系统'}：{used}",
                step=GROUP_STEP.get(sess.get("code") or "") or None, ref=sid)
        out = {"ok": True, "reacted": reacted, "reply": reply}
        if fin and fin.get("entry"):
            out["finance"] = {"entry_id": fin["entry"]["entry_id"], "bearer": fin["entry"]["bearer"],
                              "ours": fin["entry"]["ours"], "amount": fin["entry"]["amount"]}
        if error:
            out["error"] = error
        return out

    # ---------------- 语音通话中继（Qwen-Omni-Realtime） ----------------

    @app.websocket("/voice/realtime")
    async def voice_realtime(ws: WebSocket):
        await ws.accept()
        order_id = str(ws.query_params.get("order_id", "") or "")
        detail = practice.order_detail(order_id) if order_id else None
        if not detail:
            await ws.send_json({"type": "error", "message": f"未找到订单: {order_id}"})
            await ws.close()
            return
        if detail["status"] == "禁用":
            await ws.send_json({"type": "error", "message": "该订单已取消，无法发起通话"})
            await ws.close()
            return
        bridge = VoiceBridge(ws, detail, detail["customer"], detail["destination"],
                             get_call(), practice)
        try:
            await bridge.run()
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # 保底：把失败原因送回前端而不是静默断开
            try:
                await ws.send_json({"type": "error", "message": f"语音通道异常: {exc}"})
            except Exception:
                pass
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    # ---------------- 技能点对话线程（第 27 章） ----------------

    @app.get("/threads/{sp}")
    def thread_snapshot(sp: str, user_id: str = "u-demo"):
        if sp not in sp_module.SKILL_POINTS_BY_ID:
            raise HTTPException(404, f"未知技能点: {sp}")
        try:
            return get_threads().snapshot(user_id, sp)
        except LLMError as exc:
            raise HTTPException(503, str(exc))

    @app.post("/threads/{sp}/messages")
    def thread_message(sp: str, body: ThreadMsg):
        try:
            return get_threads().reply(body.user_id, sp, body.text)
        except LLMError as exc:
            raise HTTPException(503, str(exc))

    @app.post("/threads/{sp}/assets")
    def thread_asset(sp: str, body: ThreadAssetBody):
        try:
            return get_threads().generate_asset(body.user_id, sp, body.kind)
        except (LLMError, ValueError) as exc:
            raise HTTPException(503, str(exc))

    @app.post("/threads/{sp}/quiz")
    def thread_quiz(sp: str, body: ThreadQuizAnswer | None = None):
        try:
            return get_threads().pick_question("u-demo", sp)
        except LLMError as exc:
            raise HTTPException(503, str(exc))

    @app.post("/threads/{sp}/quiz/answer")
    def thread_quiz_answer(sp: str, body: ThreadQuizAnswer):
        try:
            return get_threads().submit_answer(body.user_id, sp, body.question, body.answer)
        except LLMError as exc:
            raise HTTPException(503, str(exc))

    # ---------------- 聊天界面（第 26.10 节） ----------------

    supplier_svc = SupplierService(store=store, practice=practice)

    finance_svc = FinanceService(store=store, practice=practice)

    def get_finance() -> FinanceService:
        return finance_svc

    def get_supplier() -> SupplierService:
        if supplier_svc._llm is None:
            try:
                supplier_svc._llm = get_llm()
            except LLMError:
                pass
        return supplier_svc

    @app.get("/practice/im/sessions")
    def im_sessions(user_id: str = "u-demo", order_id: str = ""):
        """聊天会话：资源大群 + 单聊 + 自己拉的群（跨订单混排，像真实聊天软件）。

        注意：不再按订单自动建"客户群/酒店群/车队群"这些房间——群由学员自己拉。
        """
        svc = get_supplier()
        hub = svc._session_view(svc.ensure_hub(user_id)["session_id"]) or {}
        rows = [hub] if hub else []
        keep = ("hub", "group", "custom")
        for sess in store.sessions(user_id):
            code = sess.get("code") or ""
            if not (code.startswith("dm-") or code in keep):
                continue                      # 老的按订单自动建的房间：不再显示
            if sess["session_id"] == hub.get("session_id"):
                continue
            view = svc._session_view(sess["session_id"]) or {}
            rows.append(view)
        orders = {o["order_id"]: o for o in practice.list_orders(user_id)}
        out = []
        for v in rows:
            o = orders.get(v.get("order_id") or "", {})
            payload = json.loads(o.get("payload") or "{}") if o else {}
            out.append({**v,
                        "customer": o.get("customer", ""),
                        "destination": o.get("destination", ""),
                        "language": payload.get("language", "中文"),
                        "min_stage": 0, "intro": "",
                        "messages": store.im_messages(v["session_id"])})
        out.sort(key=lambda r: (0 if r.get("code") == "hub" else 1, r.get("name") or ""))
        # 方案「客户已读」是惰性结算的：聊天页面也要顺手结算一次，
        # 否则学员点完「发送方案」跳到聊天里会一直等不到客户回复（回复只在查方案时生成）。
        for oid in {r.get("order_id") for r in out if r.get("order_id")}:
            try:
                get_plans().list(oid)
            except Exception:
                pass
        for r in out:
            r["messages"] = store.im_messages(r["session_id"])
        return out

    @app.get("/practice/im/contacts")
    def im_contacts(order_id: str = "", user_id: str = "u-demo"):
        """这一单能拿到哪些联系人（来源 / 能不能加 / 加没加）+ 我的通讯录。"""
        svc = get_supplier()
        catalog = []
        if order_id:
            if not store.order(order_id):
                raise HTTPException(404, f"未找到订单: {order_id}")
            catalog = svc.contact_catalog(order_id)
        return {"order_id": order_id, "contacts": catalog, "mine": svc.contacts_of_user(user_id)}

    @app.patch("/practice/im/contacts/{contact_id}")
    def im_contact_remark(contact_id: str, body: RemarkBody):
        """给联系人起备注名（真实聊天软件的核心功能）。"""
        try:
            c = get_supplier().rename_contact(contact_id, body.remark)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return {"ok": True, "contact": c, "display": get_supplier().display(c)}

    @app.post("/practice/im/contacts")
    def im_add_contact(body: ContactBody):
        """加联系人：建 1:1 会话。没到条件（没首呼 / 没接单 / 地接还没给）加不了。"""
        try:
            out = get_supplier().add_contact(body.order_id, body.kind)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True, **out}

    @app.post("/practice/im/sessions/{sid}/rename")
    def im_rename(sid: str, body: RenameBody):
        try:
            return {"ok": True, **get_supplier().rename(sid, body.name)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/practice/im/sessions/{sid}/members")
    def im_members(sid: str, body: MembersBody):
        try:
            out = get_supplier().add_members(sid, body.names)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if out["rejected"]:
            out["message"] = f"这些还没有联系方式，先加好友：{'、'.join(out['rejected'])}"
        return {"ok": True, **out}

    # ---------------- 成本 · 损失 · 结算（PRD 6.2 / C5 · C6.7） ----------------

    @app.get("/practice/orders/{order_id}/finance")
    def finance_view(order_id: str):
        """本单成本与结算：资源口径成本、损失台账、实际毛利与自报口径的偏差。"""
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return get_finance().summary(order_id)

    @app.post("/practice/orders/{order_id}/finance/entries/{entry_id}/decide")
    def finance_decide(order_id: str, entry_id: str, body: FinanceDecideBody):
        """给一笔损失定责：我方承担 / 向资源方追偿 / 转嫁客户。"""
        try:
            out = get_finance().decide(order_id, entry_id, body.bearer, body.note)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return {"ok": True, "message": out["message"], "entry": out["entry"],
                "summary": get_finance().summary(order_id)}

    @app.post("/practice/orders/{order_id}/finance/settle")
    def finance_settle(order_id: str):
        """结账：汇总成本与损失、落库，并写一条 S11 结算证据。"""
        if not store.order(order_id):
            raise HTTPException(404, f"未找到订单: {order_id}")
        return get_finance().settle(order_id)

    @app.post("/practice/im/sessions")
    def im_create(body: ImSessionBody):
        """拉群：只能邀请已加过联系方式的人；群名可改（默认「旅行小群」）。"""
        svc = get_supplier()
        members = [m for m in (body.members or []) if m and m.strip()]
        mine = svc.contacts_of_user(body.user_id)
        known = {c["name"] for c in mine} | {svc.display(c) for c in mine}
        rejected = [m for m in members if m not in known]
        if rejected:
            raise HTTPException(409, f"还没有这些人的联系方式，先加好友：{'、'.join(rejected)}")
        name = (body.name or "").strip() or "旅行小群"
        # 稳定哈希：Python 的 hash() 每个进程都不一样，重启会生成新会话
        h = 0
        for ch in f"{body.order_id}|{name}|{'|'.join(members)}":
            h = (h * 31 + ord(ch)) % 100000
        sid = f"im-{body.order_id}-group-{h}" if body.order_id else f"s{h}"
        full = ["我"] + [m for m in members if m != "我"]
        store.upsert_session(sid, body.user_id, name, body.kind, full,
                             order_id=body.order_id, code="group")
        store.add_im_message(sid, "系统", "system",
                             f"你创建了群聊「{name}」，成员：{'、'.join(full[1:]) or '（待邀请）'}",
                             kind="system")
        return {"session_id": sid, "name": name, "kind": body.kind,
                "order_id": body.order_id, "members": full}

    # ---------------- 画像 ----------------

    # 画像读写统一走数据库 ability 表（与实时评分同源）：
    # 之前这里读写的是内存里的 LearnerProfile，和评分实际写入的表是两套，导致「怎么调分都不影响难度」。
    def _profile_values(user_id: str) -> dict[str, float]:
        ab = store.abilities(user_id)
        out: dict[str, float] = {}
        for x in sp_module.SKILL_POINTS:
            row = ab.get(x.id) or {}
            real = float(row.get("real_v") or 0)
            teach = float(row.get("teach") or 0)
            out[x.id] = real if real > 0 else teach
        return out

    @app.get("/profiles/{user_id}")
    def get_profile(user_id: str):
        values = _profile_values(user_id)
        weak = [x.id for x in sp_module.SKILL_POINTS if values[x.id] < 70]
        return {
            "user_id": user_id,
            "dimensions": {
                d.value: {"name": DIMENSION_NAMES[d], "value": dimension_value(values, d)}
                for d in Dimension
            },
            "mastery": {
                x.id: {"value": round(values[x.id], 1), "level": mastery_of(values[x.id]).value,
                       "level_name": MASTERY_NAMES[mastery_of(values[x.id])]}
                for x in sp_module.SKILL_POINTS
            },
            "weak_points": weak,
        }

    @app.get("/profiles/{user_id}/trend")
    def profile_trend(user_id: str):
        teach = 30.0
        teach_map = {}
        for r in store.all_attempts(user_id):
            teach = min(100.0, max(0.0, teach + (7.0 if r["correct"] else -9.0)))
            teach_map[(r["created_at"] or "")[:10]] = round(teach, 1)
        real_map = {}
        for s in store.order_scores_all(user_id):
            try:
                sc = float(s["score"])
            except (TypeError, ValueError):
                continue
            real_map[(s["created_at"] or "")[:10]] = round(sc, 1)
        dates = sorted(set(teach_map) | set(real_map))
        last_t, last_r = None, None
        trend = []
        for d in dates:
            last_t = teach_map.get(d, last_t)
            last_r = real_map.get(d, last_r)
            trend.append({"date": d[5:],
                          "teach": last_t if last_t is not None else 0,
                          "real": last_r if last_r is not None else 0})
        return {"trend": trend}

    @app.post("/profiles/{user_id}/abilities")
    def set_ability(user_id: str, body: AbilityBody):
        if body.field == "real":
            store.set_ability(user_id, body.skill_point_id, real_v=body.value)
        else:
            store.set_ability(user_id, body.skill_point_id, teach=body.value)
        return get_profile(user_id)

    # ---------------- 画像 Agent：初始画像测评 + 动态刷新（D-066） ----------------

    REPORT_TYPE = "profile_report"

    def load_report(user_id: str) -> dict:
        row = store.latest_memory(user_id, REPORT_TYPE)
        if not row:
            return {}
        try:
            data = json.loads(row.get("content") or "{}")
        except (TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        data["created_at"] = data.get("created_at") or row.get("created_at") or ""
        return data

    def recent_order_scores(user_id: str) -> list[dict]:
        """按订单聚合成一条：均分 + 档位 + 一句评语（给画像 Agent 当证据）。"""
        agg: dict[str, dict] = {}
        for r in store.order_scores_all(user_id):
            oid = r.get("order_id") or ""
            bucket = agg.setdefault(oid, {"scores": [], "levels": [], "comment": ""})
            try:
                bucket["scores"].append(float(r.get("score") or 0))
            except (TypeError, ValueError):
                pass
            if r.get("level"):
                bucket["levels"].append(str(r["level"]))
            if not bucket["comment"] and r.get("comment"):
                bucket["comment"] = str(r["comment"])
        out = []
        for oid, bucket in agg.items():
            order = store.order(oid) or {}
            avg = round(sum(bucket["scores"]) / len(bucket["scores"]), 1) if bucket["scores"] else 0
            out.append({"order_id": oid, "destination": order.get("destination", ""),
                        "level": (bucket["levels"] or [""])[0], "score": f"{avg}",
                        "comment": bucket["comment"][:80]})
        return out

    def profile_llm():
        try:
            return get_llm()
        except LLMError:
            return None      # 没有模型也要能出画像（走确定性模板）

    @app.get("/profile/quiz")
    def profile_quiz():
        return {"questions": profile_agent.questions_public(),
                "total": len(profile_agent.QUIZ),
                "dimensions": [{"id": d.value, "name": DIMENSION_NAMES[d]} for d in Dimension]}

    @app.get("/profiles/{user_id}/intake")
    def profile_intake(user_id: str):
        """初始画像入口状态：新用户可做，已有画像数据的不再开放（只给「更新画像」）。"""
        has_data = store.has_profile_data(user_id)
        report = load_report(user_id)
        return {"user_id": user_id, "has_profile_data": has_data,
                "can_assess": not has_data, "has_report": bool(report),
                "report": report}

    @app.post("/profile/assessment")
    def profile_assessment(body: AssessmentBody):
        if store.has_profile_data(body.user_id):
            raise HTTPException(409, "该用户已有画像数据：初始画像只对新用户开放，请用「更新画像」刷新。")
        answers = [a for a in (body.answers or []) if isinstance(a, dict)]
        if len(answers) < len(profile_agent.QUIZ):
            raise HTTPException(400, f"请完成全部 {len(profile_agent.QUIZ)} 道题再提交")
        scores = profile_agent.score_answers(answers)
        agent = profile_agent.ProfileAgent(profile_llm())
        report = agent.assess(answers, scores, sp_module.SKILL_POINTS, language=body.language)
        for spo in sp_module.SKILL_POINTS:
            store.set_ability(body.user_id, spo.id, teach=float(scores.get(spo.dimension.value, 0)))
        store.add_memory(body.user_id, REPORT_TYPE, json.dumps(report, ensure_ascii=False),
                         source_thread="profile:assessment", importance=0.8)
        return {"report": report, "scores": scores}

    @app.get("/profiles/{user_id}/report")
    def profile_report(user_id: str):
        return {"report": load_report(user_id)}

    @app.post("/profiles/{user_id}/refresh")
    def profile_refresh(user_id: str):
        abilities = store.abilities(user_id)
        dims = profile_agent.dim_scores_from_abilities(abilities, sp_module.SKILL_POINTS)
        if not any((v["teach"] or v["real"]) for v in dims.values()):
            raise HTTPException(409, "还没有画像数据：先做一次初始画像测评。")
        agent = profile_agent.ProfileAgent(profile_llm())
        report = agent.refresh(dims, sp_module.SKILL_POINTS, abilities,
                               orders=recent_order_scores(user_id),
                               attempts=store.all_attempts(user_id),
                               previous=load_report(user_id))
        store.add_memory(user_id, REPORT_TYPE, json.dumps(report, ensure_ascii=False),
                         source_thread="profile:refresh", importance=0.7)
        return {"report": report}

    return app
