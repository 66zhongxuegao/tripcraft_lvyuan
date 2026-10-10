"""资源方群矩阵 / 订单级事实 / 阶段门控 离线测试（不联网，走模板兜底）。

对应 PRD 28.22 与 D-050：资源方骨架写死、措辞交给模型，
且**事件与事实必须同源**——群里说了酒店超售，酒店群里再问也必须是超售口径。
"""

import os
import tempfile
from uuid import uuid4

import pytest

from tripcraft.services.director_service import DirectorService
from tripcraft.services.practice_service import PracticeService
from tripcraft.services.supplier_service import SupplierService, _party
from tripcraft.storage import Store

O1 = "9000000000000001"          # 江苏 · 阶段 1
O2 = "9000000000000002"          # 云南 · 阶段 2
O4 = "9000000000000004"          # 浙江 · 阶段 4（行前/行中可用）
O6 = "9000000000000006"          # 贵州 · 阶段 0（还没接单）


def make():
    path = os.path.join(tempfile.gettempdir(), f"sup_{uuid4().hex}.sqlite")
    store = Store(path)
    practice = PracticeService(store)
    practice.seed("u-demo")
    svc = SupplierService(store=store, llm=None, practice=practice)
    director = DirectorService(store=store, practice=practice, llm=None)
    return store, practice, svc, director


def group(svc, order_id, code):
    return svc.group_for(order_id, code)


def unlock(svc, practice, order_id, *kinds):
    """新规则：没加联系人的群不能发言。测试里先把联系人加上。"""
    for kind in kinds:
        svc.add_contact(order_id, kind)


def test_hub_is_one_per_user_and_dms_are_per_person():
    """D-059：资源大群全局唯一；酒店/车队这些不再自动建群，加了才有单聊。"""
    store, practice, svc, _ = make()
    hub = svc.ensure_hub("u-demo")
    assert hub["session_id"] == svc.hub_id("u-demo")
    assert svc.ensure_hub("u-demo")["session_id"] == hub["session_id"]     # 幂等、全局唯一
    # 没加任何人之前：这一单的会话里只有资源大群
    assert [g["code"] for g in svc.ensure_groups(O1)] == ["hub"]
    # 加了地接 → 大群成员里出现他，且生出他的单聊
    unlock(svc, practice, O1, "地接社")
    groups = {g["code"]: g for g in svc.ensure_groups(O1)}
    assert "dm-地接社" in groups and svc.names(O1)["地接社"] in groups["hub"]["members"]
    # 同一学员的两个订单：客户是两个人，各有各的单聊，不会串
    unlock(svc, practice, O1, "客户")
    unlock(svc, practice, O2, "客户")
    assert svc.contact_dm("u-demo", "客户", O1) != svc.contact_dm("u-demo", "客户", O2)


def test_stage_gate_defers_before_the_step():
    """阶段门控还在：订单没走到询价那一步，酒店单聊里也是"现在说不好"。"""
    store, practice, svc, _ = make()
    practice.record_action(O6, "grab")
    practice.record_action(O6, "first_call")
    unlock(svc, practice, O6, "地接社", "酒店")
    hotel_sid = svc.contact_dm("u-demo", "酒店", O6)
    assert hotel_sid
    out = svc.respond(hotel_sid, "这三天四星房什么价？")
    assert out["deferred"] is True and out["sender"] == svc.names(O6)["酒店"]
    assert "说不好" in out["content"]


def test_quote_is_order_specific_and_persisted():
    store, _, svc, _ = make()
    q1 = svc.facts(O1, "酒店")                        # 江苏 → 南京四星 520
    q2 = svc.facts(O2, "酒店")                        # 云南 → 昆明四星 460
    assert q1["city"] == "南京" and q2["city"] == "昆明"
    assert q1["summary"] != q2["summary"]
    assert store.quote(O1, "酒店")["summary"] == q1["summary"]   # 落库


def test_quote_follows_constraint_change():
    store, _, svc, director = make()
    first = svc.facts(O1, "酒店")["summary"]
    store.set_supplier_state("u-demo", "酒店", {"price_factor": 1.5}, order_id=O1)
    second = svc.facts(O1, "酒店")["summary"]
    assert first != second                            # 约束一变，落库报价作废重算
    assert svc.facts(O2, "酒店")["summary"] != second   # 只影响这一单


def test_apply_fact_does_not_leak_to_other_orders():
    store, _, svc, director = make()
    svc.apply_fact(O1, "车队", {"availability": "无档期", "note": "车全派出去了"})
    a = svc.facts(O1, "车队")
    b = svc.facts(O2, "车队")
    assert a["availability"] == "无档期" and "车全派出去了" in a["note"]
    assert b["availability"] == "有货" and b["note"] == ""


def test_party_parsing():
    assert _party({"party": "3大1小"})["total"] == 4
    assert _party({"party": ""})["known"] is False
    assert _party({"party": ""})["adults"] == 2


def test_supplier_reply_uses_hard_facts():
    store, practice, svc, _ = make()
    unlock(svc, practice, O2, "地接社")
    sid = svc.contact_dm("u-demo", "地接社", O2)      # 地接单聊（阶段 2 ≥ 下限 1）
    out = svc.respond(sid, "云南这单四星和用车什么价？")
    assert out["deferred"] is False and out["sender"] == svc.names(O2)["地接社"]
    assert "460" in out["content"]                    # 昆明四星基准价
    assert out["quote"]["kind"] == "地接社"


def test_hub_reply_falls_back_to_latest_order():
    """资源大群没有"这一单"的上下文：以最近在跟的一单的地接口径回答。"""
    store, practice, svc, _ = make()
    unlock(svc, practice, O4, "地接社")
    hub = svc.ensure_hub("u-demo")
    out = svc.respond(hub["session_id"], "四星和用车什么价？")
    assert out and out["content"] and out["sender"].endswith("经理")


def test_guide_group_needs_pre_trip_then_reports_incident():
    store, practice, svc, director = make()
    unlock(svc, practice, O4, "地接社", "导游")
    g = svc.group_for(O4, "guide")
    assert g and g["kind"] == "导游"
    idle = svc.respond(g["session_id"], "今晚安排好了吗？")
    assert idle["deferred"] is False and "按计划走" in idle["content"]

    fired = director.emit(O4, "pre_trip")             # 车辆故障（司导群）
    assert fired["injected"] and fired["injected"]["code"] == "INC-VEHICLE-BREAKDOWN"
    assert fired["injected"]["session_id"] == g["session_id"]

    hot = svc.respond(g["session_id"], "客人那边你稳住，换车多久能好？")
    assert hot["deferred"] is False
    assert "换车" in hot["content"] or "车出问题" in hot["content"]
    # 事件与事实同源：车队这一单必须变成无档期，别的单不受影响
    assert svc.facts(O4, "车队")["availability"] == "无档期"
    assert svc.facts(O1, "车队")["availability"] == "有货"


def test_customer_group_replies_in_character():
    store, practice, svc, _ = make()
    unlock(svc, practice, O1, "客户")
    cus = svc.group_for(O1, "customer")
    out = svc.respond(cus["session_id"], "您好，我是您的定制师，方案今晚发您。")
    assert out["sender"] == "客户" and out["content"] and not out.get("locked")
    assert "教练" not in out["content"]


def test_contacts_follow_the_real_sequence():
    """联系人不是一上来全给：先首呼才有客户，接单才有地接，酒店车队由地接给，司导要等行前。"""
    store, practice, svc, _ = make()
    cat = {c["kind"]: c for c in svc.contact_catalog(O6)}
    assert cat["地接社"]["available"] is False and cat["客户"]["available"] is False
    with pytest.raises(ValueError):
        svc.add_contact(O6, "酒店")
    practice.record_action(O6, "grab")
    cat = {c["kind"]: c for c in svc.contact_catalog(O6)}
    assert cat["地接社"]["available"] is True and cat["客户"]["available"] is False
    practice.record_action(O6, "first_call")
    svc.add_contact(O6, "地接社")
    cat = {c["kind"]: c for c in svc.contact_catalog(O6)}
    assert cat["客户"]["available"] is True and cat["酒店"]["available"] is True
    assert cat["导游"]["available"] is False          # 还没到行前
    svc.add_contact(O6, "客户")
    assert "客户" in svc.added_contacts(O6)
    dms = [s for s in store.sessions("u-demo", O6) if s["code"].startswith("dm-")]
    assert len(dms) == 2                              # 每个联系人一个 1:1 会话


def test_group_rename_and_invite():
    store, practice, svc, _ = make()
    unlock(svc, practice, O4, "地接社", "导游", "司机")
    hub = svc.ensure_hub("u-demo")
    out = svc.rename(hub["session_id"], "我的资源群")
    assert out["name"] == "我的资源群"
    msgs = store.im_messages(hub["session_id"])
    assert any(m["kind"] == "system" and "群名已由" in m["content"] for m in msgs)
    res = svc.add_members(hub["session_id"], ["导游·测试", "陌生人"])
    assert res["rejected"] == ["导游·测试", "陌生人"]   # 没加过联系方式的人拉不进来


def test_contact_remark_is_shown_everywhere():
    """备注名：通讯录、单聊会话名、资源大群成员名三处都要跟着变。"""
    store, practice, svc, _ = make()
    unlock(svc, practice, O4, "地接社")
    cid = svc.added_contacts(O4)["地接社"]["contact_id"]
    svc.rename_contact(cid, "黄哥·云南地接")
    assert svc.added_contacts(O4)["地接社"]["remark"] == "黄哥·云南地接"
    sid = svc.contact_dm("u-demo", "地接社", O4)
    assert store.session(sid)["name"] == "黄哥·云南地接"
    hub = svc.ensure_hub("u-demo")
    assert "黄哥·云南地接" in svc._members(store.session(hub["session_id"]))


# ---------------- 回复体验：不重复前缀、不重复同一句 ----------------

def test_hub_reply_has_no_name_prefix():
    """名字在界面里已经显示，正文里不该再带「（姓名）」前缀。"""
    import inspect
    from tripcraft.services import supplier_service as ss

    src = inspect.getsource(ss.SupplierService._hub_reply)
    assert "（{who}）" not in src
    assert 'out["content"] = f"（' not in src


def test_defer_variants_differ():
    from tripcraft.services.supplier_service import DEFER_VARIANTS

    texts = {t.format(reason="需求还没确认完") for t in DEFER_VARIANTS}
    assert len(texts) == len(DEFER_VARIANTS) >= 3

def test_defer_reply_alternates_and_has_no_prefix():
    """连着追问时，资源方不能一字不差地重复上一句，正文也不该带（姓名）。"""
    store, practice, svc, _ = make()
    practice.record_action(O6, "grab")
    practice.record_action(O6, "first_call")
    unlock(svc, practice, O6, "地接社", "酒店")
    sid = svc.contact_dm("u-demo", "酒店", O6)      # O6 还在阶段 0，酒店不该报价
    assert sid
    first = svc.respond(sid, "这三天四星房什么价？")
    assert first["deferred"] is True
    assert not first["content"].startswith("（"), "正文里不该再带（姓名）前缀"
    store.add_im_message(sid, first["sender"], "other", first["content"])
    second = svc.respond(sid, "到底什么价，给个准数")
    assert second["deferred"] is True
    assert second["content"] != first["content"], "连问两次不能回一模一样的句子"

