"""交付物工作台服务 —— 结构化填写 → 渲染 → 校验 → 按对象投递 → 登记证据（PRD 第 8/10 章）。

一次提交做五件事：
  1. 按契约校验必填项，渲染成正式文档；
  2. 过双层拦截网（有适用校验规则时）；被拦则不投递、不登记证据；
  3. 按 `audience` 分路：客户 → 客户 Agent 读并反馈；地接社 → 写进聊天群；平台 → 登记平台投递；
  4. 渲染文档写入 `order_evidence`，作为评分 Agent 的素材（步骤落点来自契约）；
  5. 登记契约里的自动动作，可能有门槛因此达成、平台状态自动推进。
"""

from __future__ import annotations

import json
from typing import Any

from ..contracts.deliverables_spec import (BY_ID, CUSTOMER, PLATFORM, SUPPLIER, DeliverableSpec,
                                            render, resolve)


class DeliverableError(ValueError):
    pass


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def check_arithmetic(deliverable_id: str, values: dict) -> list[str]:
    """字段级算术校验（比解析渲染文本更可靠）。

    结构化交付物里的数字关系必须自洽——这是双层拦截网的第一层，
    只是它作用在**字段**上而不是渲染后的文本上。
    """
    code = deliverable_id
    errs: list[str] = []

    if code in ("quotation", "\u5206\u9879\u62a5\u4ef7"):
        items = values.get("items") or []
        total_from_rows = 0.0
        for it in items:
            amount = _num((it or {}).get("amount"))
            if amount is None:
                qty, price = _num((it or {}).get("qty")), _num((it or {}).get("price"))
                amount = (qty or 0) * (price or 0)
            total_from_rows += amount or 0
        total = _num(values.get("total"))
        if total and items and abs(total_from_rows - total) > max(1.0, total * 0.01):
            errs.append(f"\u5206\u9879\u5408\u8ba1 {round(total_from_rows)} \u5143\u4e0e\u5408\u8ba1\u91d1\u989d {round(total)} \u5143\u4e0d\u4e00\u81f4")
        cost = _num(values.get("cost"))
        if cost is not None and total is not None and cost >= total:
            errs.append(f"\u6210\u672c {round(cost)} \u5143 \u2265 \u5408\u8ba1 {round(total)} \u5143\uff0c\u6bdb\u5229 \u2264 0")
        if cost is not None and total:
            margin = (total - cost) / total * 100
            if margin < 5:
                errs.append(f"\u6bdb\u5229\u7387\u4ec5 {margin:.1f}%\uff0c\u6ca1\u6709\u7ed9\u7968\u52a1/\u9152\u5e97\u6da8\u4ef7\u7559\u7a7a\u95f4")

    if code in ("settlement", "\u5730\u63a5\u7ed3\u7b97\u6838\u5bf9\u5355"):
        settle, ours = _num(values.get("total_settle")), _num(values.get("total_ours"))
        diff, cost, margin = (_num(values.get("diff")), _num(values.get("actual_cost")),
                              _num(values.get("actual_margin")))
        if settle is not None and ours is not None and diff is not None:
            if abs(abs(settle - ours) - abs(diff)) > 1:
                errs.append(f"\u5408\u8ba1\u5dee\u5f02 {round(diff)} \u5143\u4e0e\u201c\u5730\u63a5 {round(settle)} - \u6211\u65b9 {round(ours)}\u201d\u4e0d\u4e00\u81f4")
        if ours is not None and cost is not None and margin is not None:
            if abs((ours - cost) - margin) > 1:
                errs.append(f"\u5b9e\u9645\u6bdb\u5229 {round(margin)} \u5143\u4e0e\u201c\u6211\u65b9 {round(ours)} - \u5b9e\u9645\u6210\u672c {round(cost)}\u201d\u4e0d\u4e00\u81f4")
        rows = values.get("items") or []
        for r in rows:
            a, b, d = _num((r or {}).get("supplier")), _num((r or {}).get("ours")), _num((r or {}).get("diff"))
            if a is not None and b is not None and d is not None and abs(abs(a - b) - abs(d)) > 1:
                errs.append(f"\u9010\u9879\u300c{(r or {}).get('item', '')}\u300d\u5dee\u5f02\u4e0d\u5bf9\uff1a{round(a)} vs {round(b)} \u5dee {round(d)}")

    if code in ("itinerary", "\u884c\u7a0b\u65b9\u6848"):
        days = [d for d in (values.get("days") or []) if (d or {}).get("day")]
        if days and len(days) < 2:
            errs.append("\u9010\u65e5\u884c\u7a0b\u81f3\u5c11\u9700\u8981\u4e24\u5929")

    return errs


class DeliverableService:
    def __init__(self, store, practice=None, guard=None, tools=None, llm=None) -> None:
        self._store = store
        self._practice = practice
        self._guard = guard
        self._tools = tools
        self._llm = llm

    # ---------- 契约 ----------

    @staticmethod
    def specs() -> list[dict]:
        return [{
            "id": d.id, "code": d.code, "step": d.step, "title": d.title, "purpose": d.purpose,
            "audience": list(d.audience), "filename": d.filename,
            "checks": list(d.checks), "auto_actions": list(d.auto_actions),
            "surface": d.surface,
            "conditional_actions": [list(x) for x in d.conditional_actions],
            "fields": [{
                "key": f.key, "label": f.label, "type": f.type, "required": f.required,
                "placeholder": f.placeholder, "help": f.help, "unit": f.unit,
                "options": list(f.options),
                "columns": [{"key": c.key, "label": c.label} for c in f.columns],
            } for f in d.fields],
        } for d in BY_ID.values()]

    @staticmethod
    def validate(deliverable_id: str, values: dict[str, Any]) -> list[str]:
        spec = resolve(deliverable_id)
        if spec is None:
            raise DeliverableError(f"未知交付物: {deliverable_id}")
        missing = []
        for f in spec.fields:
            if not f.required:
                continue
            v = values.get(f.key)
            if f.is_rows:
                rows = [r for r in (v or []) if any(str(x or "").strip() for x in (r or {}).values())]
                if not rows:
                    missing.append(f.label)
                    continue
                # 逐日行程要写全六要素（时间/交通+耗时/景点/餐食/住宿/导游）：
                # 只填个「D1 逛西湖」不算方案，客户与评分都没法核对
                if f.key == "days":
                    for i, row in enumerate(rows, 1):
                        blank = [c.label for c in f.columns
                                 if not str(row.get(c.key) or "").strip()]
                        if blank:
                            day = str(row.get("day") or f"D{i}").strip()
                            missing.append(f"{f.label} {day}（缺 {'、'.join(blank)}）")
            elif v in (None, "", []):
                missing.append(f.label)
        return missing

    # ---------- 提交 ----------

    def submit(self, order_id: str, deliverable_id: str, values: dict[str, Any],
               file_ids: list[str] | None = None, context: dict | None = None,
               targets: list[str] | None = None, defer_customer_reply: bool = False) -> dict:
        spec = resolve(deliverable_id)
        if spec is None:
            raise DeliverableError(f"未知交付物: {deliverable_id}")
        deliverable_id = spec.id
        order = self._store.order(order_id)
        if not order:
            raise DeliverableError(f"未找到订单: {order_id}")

        missing = self.validate(deliverable_id, values)
        if missing:
            raise DeliverableError("以下必填项未完成：" + "、".join(missing))

        arith = check_arithmetic(spec.code, values)
        if arith:
            return {"order_id": order_id, "deliverable_id": spec.id, "code": spec.code,
                    "blocked": True, "rendered": "",
                    "guard": {"blocked": True, "verdict": "block", "reasons": arith,
                              "deterministic": {"layer": "deterministic", "errors": arith,
                                                "warnings": [], "checks": []},
                              "semantic": {"issues": [], "skipped": True},
                              "layers": ["deterministic", "semantic"]},
                    "message": "字段算术校验未通过，未投递；请按下列问题修改后重新提交。"}

        ctx = context or {}
        if not ctx:
            payload = json.loads(order["payload"] or "{}")
            ctx = {"order_id": order_id, "customer": order["customer"], "destination": order["destination"],
                   "source_market": payload.get("source_market", ""), "language": payload.get("language", "中文")}
        rendered = render(spec, values, ctx)

        files = [self._store.file_meta(f) for f in
                 (self._store.file(fid) for fid in (file_ids or [])) if f]

        # 1) 拦截网
        guard: dict = {"blocked": False, "verdict": "pass", "reasons": [],
                       "deterministic": {"errors": [], "warnings": [], "checks": []},
                       "semantic": {"issues": []}}
        if spec.checks and self._guard is not None:
            kind = spec.checks[0]
            guard = self._guard.check(kind, rendered, order_id)
            if guard.get("blocked"):
                return {"order_id": order_id, "deliverable_id": deliverable_id,
                        "blocked": True, "guard": guard, "rendered": rendered,
                        "message": "交付物未通过校验，未投递；请按下列问题修改后重新提交。"}

        # 2) 分路投递（学员可以指定发到哪个会话；不指定就按交付物默认去向）
        routing = self._route(spec, rendered, order, ctx, files, targets or [],
                              defer_reply=defer_customer_reply)

        # 3) 证据 + 动作
        evidence_id = None
        if self._practice is not None:
            evidence_id = self._practice.record_evidence(
                order_id, spec.id, rendered, step=spec.step, ref=f"doc:{deliverable_id}")
            from .workflow import is_known_action
            for act in spec.auto_actions:
                if is_known_action(act):
                    self._practice.record_action(order_id, act, {"deliverable": deliverable_id})
            # 条件动作：字段取到期望值才登记（例如「客户签署状态 = 已签署」）
            for act, key, expected in spec.conditional_actions:
                if is_known_action(act) and str(values.get(key) or "") == expected:
                    self._practice.record_action(order_id, act, {"deliverable": deliverable_id,
                                                                 "field": key})

        version = self._store.save_deliverable(order_id, deliverable_id, values, rendered,
                                               list(spec.audience), guard,
                                               [f["file_id"] for f in files])

        gates = self._practice.gate_report(order_id) if self._practice else None
        return {
            "order_id": order_id, "deliverable_id": deliverable_id, "version": version,
            "blocked": False, "guard": guard, "routing": routing, "files": files,
            "rendered": rendered, "evidence_id": evidence_id,
            "audience": list(spec.audience), "step": spec.step, "gates": gates,
        }

    # 交付物默认去向 → 该订单的会话
    AUDIENCE_ROOM = {"客户": "客户服务群", "地接社": "地接资源信息群"}

    def target_options(self, order_id: str, spec) -> list[dict]:
        """这份产出能发到哪些会话：资源大群 / 已加联系人的单聊 / 自己拉的群。

        默认勾选：发给客户 → 客户单聊；发给地接 → 资源大群。
        """
        from .supplier_service import SupplierService
        svc = SupplierService(self._store)
        user = (self._store.order(order_id) or {}).get("user_id") or "u-demo"
        added = svc.added_contacts(order_id)
        customer_dm = svc.contact_dm(user, "客户", order_id)
        hub = svc.ensure_hub(user)["session_id"]
        out: list[dict] = []
        want_customer = CUSTOMER in spec.audience
        want_supplier = SUPPLIER in spec.audience
        for c in added.values():
            sid = c.get("session_id") or ""
            if not sid:
                continue
            is_customer = c["kind"] == "客户"
            out.append({"session_id": sid, "name": svc.display(c), "kind": c["kind"],
                        "code": f"dm-{c['kind']}",
                        "hint": "发给客户，客户会直接读并回复" if is_customer else "单独发给对方",
                        "default": bool(want_customer and is_customer)})
        out.append({"session_id": hub, "name": "资源对接群", "kind": SUPPLIER, "code": "hub",
                    "hint": "发给地接，按这个口径落实资源", "default": bool(want_supplier)})
        # 学员自己拉的群也可以作为投递对象
        for sess in self._store.sessions(user):
            if (sess.get("code") or "") in ("group", "custom") and sess["session_id"] != hub:
                out.append({"session_id": sess["session_id"], "name": sess["name"],
                            "kind": sess.get("kind") or "群聊", "code": "group",
                            "hint": "发到你拉的这个群", "default": False})
        return out

    def _resolve_targets(self, order: dict, spec, targets: list[str]) -> list[dict]:
        """学员选了发到哪就发到哪；没选就按交付物的默认受众映射到房间。"""
        from .supplier_service import SupplierService
        svc = SupplierService(self._store)
        groups = {g["session_id"]: g for g in svc.ensure_groups(order["order_id"])}
        chosen: list[dict] = []
        for sid in targets or []:
            g = groups.get(sid)
            if g:
                chosen.append({"session_id": sid, "name": g["name"], "kind": g["kind"]})
                continue
            row = self._store.session(sid)
            if row:
                chosen.append({"session_id": sid, "name": row["name"], "kind": row["kind"]})
        if chosen:
            return chosen
        for a in spec.audience:
            if a == CUSTOMER:
                if not self._customer_reachable(order):
                    continue      # 客户微信还没加上：先留在平台消息
                sid = svc.contact_dm(order.get("user_id") or "u-demo", "客户", order["order_id"])
                if sid:
                    chosen.append({"session_id": sid,
                                   "name": (self._store.session(sid) or {}).get("name", "客户"),
                                   "kind": CUSTOMER})
            elif a == SUPPLIER:
                hub = svc.ensure_hub(order.get("user_id") or "u-demo")
                chosen.append({"session_id": hub["session_id"], "name": hub["name"],
                               "kind": SUPPLIER})
        return chosen

    def _route(self, spec, rendered: str, order: dict, ctx: dict, files: list[dict],
               targets: list[str] | None = None, defer_reply: bool = False) -> dict:
        out: dict[str, Any] = {"sent_to": [], "customer_reply": "", "sentiment": "",
                               "asks": [], "im_session": "", "platform_note": "", "targets": []}
        att = ("　附件：" + "、".join(f["filename"] for f in files)) if files else ""

        chosen = self._resolve_targets(order, spec, targets or [])
        for t in chosen:
            self._post_card(t["session_id"], spec, rendered, files, t["name"])
            out["targets"].append(t)
            out["im_session"] = out["im_session"] or t["session_id"]

        cust = next((t for t in chosen if t["kind"] == CUSTOMER), None)
        if cust is not None:
            out["sent_to"].append(CUSTOMER)
            # 方案类产出由「发送方案 → 客户已读」驱动回复：发送时先不触发
            if self._tools is not None and not defer_reply:
                try:
                    fb = self._tools.deliverable_feedback(spec.id, rendered + att, order["customer"])
                    out.update({"customer_reply": fb.get("reply", ""),
                                "sentiment": fb.get("sentiment", ""),
                                "asks": fb.get("asks", [])})
                    if out["customer_reply"]:
                        self._store.add_im_message(cust["session_id"], order["customer"],
                                                   "other", out["customer_reply"])
                except Exception as exc:
                    out["customer_error"] = f"{type(exc).__name__}: {exc}"

        if any(t["kind"] in (SUPPLIER, "行中") for t in chosen):
            out["sent_to"].append(SUPPLIER)

        if PLATFORM in spec.audience:
            note = f"{spec.title} V1 已提交平台（订单 {order['order_id']}）"
            self._store.add_event(order["order_id"], "platform_submission",
                                  {"deliverable": spec.id, "note": note})
            out["platform_note"] = note
            out["sent_to"].append(PLATFORM)

        return out

    def _customer_reachable(self, order: dict) -> bool:
        """客户是不是已经在你通讯录里（没有的话交付物先留在平台，不进单聊）。"""
        from .supplier_service import SupplierService
        try:
            return bool(SupplierService(self._store).contact_dm(
                order.get("user_id") or "u-demo", "客户", order["order_id"]))
        except Exception:
            return False

    def _post_card(self, sid: str, spec, rendered: str, files: list[dict],
                   target: str) -> None:
        """交付物以卡片形式落进会话：对方能读到、复盘能追溯到是哪一份。"""
        self._store.add_im_message(
            sid, "我", "me", f"【{spec.title}】已发送给{target}", kind="card",
            payload={"deliverable_id": spec.id, "title": spec.title, "step": spec.step,
                     "target": target, "audience": list(spec.audience),
                     "files": [f["filename"] for f in files],
                     "excerpt": (rendered or "")[:600]})

    def _ensure_group(self, order: dict, name: str) -> str:
        """投递必须落进**这一单**的群：否则 A 单的报价会出现在 B 单的地接群里（D-050）。"""
        from .supplier_service import SupplierService
        g = SupplierService(self._store).group_by_name(order["order_id"], name)
        if g:
            return g["session_id"]
        sid = f"im-{order['order_id']}-misc"
        self._store.upsert_session(sid, order["user_id"], name, "地接社", ["我", name],
                                   order_id=order["order_id"], code="misc")
        return sid

    # ---------- 查询 ----------

    def list_for_order(self, order_id: str) -> dict:
        rows = {r["deliverable_id"]: r for r in self._store.deliverables(order_id)}
        items = []
        for spec in BY_ID.values():
            row = rows.get(spec.id)
            items.append({
                "id": spec.id, "code": spec.code, "step": spec.step, "title": spec.title, "purpose": spec.purpose,
                "audience": list(spec.audience), "checks": list(spec.checks),
                "surface": spec.surface,
                "submitted": bool(row), "version": int((row or {}).get("version") or 0),
                "at": (row or {}).get("at", ""),
                "values": json.loads((row or {}).get("values_json") or "{}"),
                "file_ids": json.loads((row or {}).get("file_ids") or "[]"),
            })
        return {"order_id": order_id, "deliverables": items}

    def detail(self, order_id: str, deliverable_id: str) -> dict:
        spec = resolve(deliverable_id)
        if spec is None:
            raise DeliverableError(f"未知交付物: {deliverable_id}")
        deliverable_id = spec.id
        row = self._store.deliverable(order_id, deliverable_id)
        values = json.loads((row or {}).get("values_json") or "{}")
        ctx = {}
        order = self._store.order(order_id)
        if order:
            payload = json.loads(order["payload"] or "{}")
            ctx = {"order_id": order_id, "customer": order["customer"], "destination": order["destination"],
                   "source_market": payload.get("source_market", ""), "language": payload.get("language", "中文")}
            # 新填写时用订单信息预填部分字段
            values.setdefault("guest", order["customer"])
            values.setdefault("source", payload.get("source_market", ""))
            values.setdefault("people", order["customer"] and "")
        return {"order_id": order_id, "spec": next(s for s in self.specs() if s["id"] == deliverable_id),
                "values": values, "rendered": (row or {}).get("rendered", ""),
                "version": int((row or {}).get("version") or 0),
                "file_ids": json.loads((row or {}).get("file_ids") or "[]"),
                "context": ctx,
                "surface": spec.surface,
                "target_options": self.target_options(order_id, spec) if order else []}