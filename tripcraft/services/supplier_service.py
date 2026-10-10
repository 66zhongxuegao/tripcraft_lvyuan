"""资源方 Agent —— 每单一套群，事实来自硬数据，措辞交给模型（PRD 2.2 / 6.2 / D-050）。

**分工（关键）**
- 写死：群矩阵、群与订单的绑定、基准价表、报价与库存的推导、**阶段可见性**、话术禁区；
- 交给模型：把事实说成这个角色该说的话。

资源方不是自由聊天机器人：它只知道自己这一单的客观事实（报价/库存/档期/时限），
提示词里注入这些事实并禁止编造数字；问超纲的问题就按角色回绝或说需要核实。

**防止偏离 13 步的四个硬卡点**
1. 会话必须绑定 order_id —— 不同订单绝不共用一个群，投递交付物也按订单落群；
2. 每个资源方有 `min_stage`，订单没走到那个阶段就不进入该环节（只做礼貌推诿）；
3. 报价/库存由基准价表 + 情景约束**推导后落库**，约束一变按指纹重算，同一群里不会出现两套数字；
4. 事件与事实同源：导演注入的事件带 `effect`，写群消息的同时改写**这一单**的事实；
   资源方也不会主动承诺流程以外的事（锁价、垫付、改合同），一律要求走定制师流程。

**应答路由**：本模块是群应答总入口——资源方四类走 `_supplier_reply`（事实 + 阶段门控），
司导群走 `_guide_reply`（只报现象、请定制师拍板），客户群走 `_customer_reply`（人设 + 情绪档）。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from ..agents.customer import persona_for
from ..agents.llm import DeepSeekClient

# 平台 8 态名称（数据库行里没有 stage_name，那是计算字段）
ORDER_STEPS = ["定制师接单", "定制师提供方案", "客户确认方案", "定制师提供合同",
               "客户确认合同", "客户出团", "定制师提交结算", "订单完成"]

# ---------------------------------------------------------------- 群矩阵（写死）

@dataclass(frozen=True)
class GroupSpec:
    code: str
    name: str
    kind: str                 # 资源方类型（也是 agent 角色）
    members: tuple[str, ...]  # {customer} / {dest} 占位
    min_stage: int            # 订单走到这个平台阶段才"在场"
    intro: str
    contact: str = ""         # 要进这个群，必须先加哪一类联系人（"" = 平台通道，无需加好友）


@dataclass(frozen=True)
class ContactSpec:
    """联系人目录：这一单能拿到哪些人、从哪来、什么时候能拿到。"""

    kind: str                 # 联系人类型（也是会话与台账口径）
    source: str               # 来源：首呼 / 平台指派 / 地接提供
    unlock: str               # first_call / grab / contact:地接社 / contact:地接社+stage:4
    note: str = ""


GROUPS: tuple[GroupSpec, ...] = (
    GroupSpec("customer", "客户服务群", "客户", ("我", "{customer}"), 0,
              "首呼达成意向后建的客户群", contact="客户"),
    GroupSpec("supplier", "地接资源信息群", "地接社", ("我", "{agent}"), 1,
              "目的地地接，负责住宿/用车/门票/导游的落实与报价", contact="地接社"),
    GroupSpec("hotel", "酒店沟通群", "酒店", ("我", "{agent}"), 1,
              "酒店团队销售，负责房型、房价、房态与保留时限", contact="酒店"),
    GroupSpec("vehicle", "车队沟通群", "车队", ("我", "{agent}"), 1,
              "车队调度，负责车型、座位、日租价与档期", contact="车队"),
    GroupSpec("ticket", "票务沟通群", "票务", ("我", "票务·陈"), 1,
              "旅行社票务，负责机票/高铁票价、余票与价格波动"),
    GroupSpec("guide", "司导沟通群", "行中", ("我", "{guide}", "{driver}"), 4,
              "行前对接、行中执行的导游与司机", contact="导游"),
)

BY_CODE = {g.code: g for g in GROUPS}

# ---------------------------------------------------------------- 联系人目录（写死规则）

# 票务不在目录里：票务是平台通道，不需要加好友。
CONTACTS: tuple[ContactSpec, ...] = (
    ContactSpec("客户", "首呼时问到的手机号", "first_call", "首呼问到电话，加上了才能建群沟通"),
    ContactSpec("地接社", "接单后平台指派", "grab", "平台确认接单后指派的目的地地接"),
    ContactSpec("酒店", "地接提供", "contact:地接社", "要用地接给的酒店销售联系方式"),
    ContactSpec("车队", "地接提供", "contact:地接社", "要用地接给的车队调度联系方式"),
    ContactSpec("导游", "地接提供", "contact:地接社+stage:4", "行前地接排班后才给导游电话"),
    ContactSpec("司机", "地接提供", "contact:地接社+stage:4", "行前地接排班后才给司机电话"),
)

_SURNAMES = ("张", "李", "王", "陈", "刘", "周", "吴", "赵", "黄", "徐")
_HOTELS = ("全季", "亚朵", "维也纳", "开元", "建国", "锦江")
_FLEETS = ("顺达", "远行", "安捷", "通达", "恒运")


def _stable_hash(text: str) -> int:
    h = 0
    for ch in text:
        h = (h * 31 + ord(ch)) % 100003
    return h


def _phone(order_id: str, salt: str, idx: int) -> str:
    """按订单 + 对象派生稳定手机号：同一单每次一样，不同单不一样。"""
    h = _stable_hash(f"{order_id}|{salt}|{idx}")
    return f"1{h % 6 + 3}{(h // 7) % 10}{(h // 13) % 10}{(h // 17) % 10000:04d}"


def contact_identity(order_id: str, kind: str, dest: str, city: str, customer: str) -> str:
    """这一单这一类的联系人叫什么（确定性派生，每单不同）。"""
    i = _stable_hash(f"{order_id}|{kind}") % len(_SURNAMES)
    surname = _SURNAMES[i]
    if kind == "客户":
        return customer
    if kind == "地接社":
        return f"{dest}地接·{surname}经理"
    if kind == "酒店":
        return f"{city}·{_HOTELS[i % len(_HOTELS)]}销售{surname}"
    if kind == "车队":
        return f"{city}·{_FLEETS[i % len(_FLEETS)]}车队·{surname}调度"
    if kind == "导游":
        return f"导游·{surname}"
    if kind == "司机":
        return f"司机·{surname}师傅"
    return kind


def _contact_spec(kind: str) -> ContactSpec | None:
    return next((c for c in CONTACTS if c.kind == kind), None)

# 资源方类型 -> 平台阶段下限（写死；不到这个阶段不进入对应环节）
KIND_MIN_STAGE: dict[str, int] = {g.kind: g.min_stage for g in GROUPS}

# ---------------------------------------------------------------- 基准价表（写死）

DEFAULT_BASE = {"city": "目的地", "hotel4": 480, "vehicle7": 900, "guide_day": 520, "ticket_avg": 130}

CITY_BASE: dict[str, dict] = {
    "云南": {"city": "昆明", "hotel4": 460, "vehicle7": 850, "guide_day": 500, "ticket_avg": 120},
    "贵州": {"city": "贵阳", "hotel4": 420, "vehicle7": 800, "guide_day": 480, "ticket_avg": 110},
    "四川": {"city": "成都", "hotel4": 470, "vehicle7": 880, "guide_day": 510, "ticket_avg": 140},
    "广西": {"city": "桂林", "hotel4": 450, "vehicle7": 830, "guide_day": 490, "ticket_avg": 125},
    "陕西": {"city": "西安", "hotel4": 490, "vehicle7": 870, "guide_day": 520, "ticket_avg": 150},
    "福建": {"city": "厦门", "hotel4": 510, "vehicle7": 900, "guide_day": 530, "ticket_avg": 130},
    "湖南": {"city": "长沙", "hotel4": 430, "vehicle7": 820, "guide_day": 480, "ticket_avg": 115},
    "浙江": {"city": "杭州", "hotel4": 540, "vehicle7": 950, "guide_day": 560, "ticket_avg": 145},
    "江苏": {"city": "南京", "hotel4": 520, "vehicle7": 930, "guide_day": 540, "ticket_avg": 135},
    "北京": {"city": "北京", "hotel4": 620, "vehicle7": 1100, "guide_day": 620, "ticket_avg": 160},
    "甘肃": {"city": "兰州", "hotel4": 410, "vehicle7": 860, "guide_day": 500, "ticket_avg": 120},
    "青海": {"city": "西宁", "hotel4": 430, "vehicle7": 900, "guide_day": 520, "ticket_avg": 110},
    "内蒙古": {"city": "呼和浩特", "hotel4": 420, "vehicle7": 880, "guide_day": 510, "ticket_avg": 105},
    "海南": {"city": "三亚", "hotel4": 680, "vehicle7": 1000, "guide_day": 600, "ticket_avg": 170},
    "新疆": {"city": "乌鲁木齐", "hotel4": 450, "vehicle7": 1050, "guide_day": 560, "ticket_avg": 130},
    "西藏": {"city": "拉萨", "hotel4": 520, "vehicle7": 1150, "guide_day": 620, "ticket_avg": 120},
    "山西": {"city": "太原", "hotel4": 420, "vehicle7": 830, "guide_day": 490, "ticket_avg": 120},
    "重庆": {"city": "重庆", "hotel4": 460, "vehicle7": 860, "guide_day": 500, "ticket_avg": 125},
}

# 7 座以上车型的加价（写死）
VEHICLE_TIERS = {"7 座商务": 1.0, "5 座轿车": 0.8, "15 座中巴": 1.35, "33 座大巴": 1.8}

PARTY_RE = re.compile(r"(\d+)\s*大")
CHILD_RE = re.compile(r"(\d+)\s*小")


def _party(payload: dict) -> dict:
    """从派单的出行人构成里解析人数（缺就按 2 大估算，并在字段里说明是估算）。"""
    text = str(payload.get("party") or "")
    adults = int(PARTY_RE.search(text).group(1)) if PARTY_RE.search(text) else 0
    children = int(CHILD_RE.search(text).group(1)) if CHILD_RE.search(text) else 0
    if not adults and not children:
        m = re.search(r"(\d+)", text)
        adults = int(m.group(1)) if m else 2
    return {"adults": adults, "children": children, "total": adults + children,
            "known": bool(text.strip())}


def _state(store, kind: str, order_id: str = "") -> dict:
    """该单该资源方的有效情景约束：订单级覆盖优先，其次导演台的全局默认。"""
    try:
        row = store.order(order_id) or {}
        user_id = row.get("user_id") or "u-demo"
        return store.supplier_state_for(user_id, kind, order_id)
    except Exception:
        return {}


def _state_key(state: dict) -> str:
    """约束指纹：约束一变，之前落库的报价就作废（否则群里会报出前后矛盾的数）。"""
    return json.dumps({k: state.get(k) for k in ("price_factor", "availability", "note")},
                      ensure_ascii=False, sort_keys=True)


def build_quote(store, order_id: str, kind: str) -> dict:
    """按基准价表 + 情景约束**推导**该资源方对这一单的客观事实，并落库。"""
    row = store.order(order_id)
    payload = json.loads((row or {}).get("payload") or "{}")
    dest = (row or {}).get("destination", "")
    base = CITY_BASE.get(dest, DEFAULT_BASE)
    p = _party(payload)
    rooms = max(1, -(-p["total"] // 2))          # 两人一间
    state = _state(store, kind, order_id)
    factor = float(state.get("price_factor") or 1.0)
    avail = state.get("availability") or "有货"
    note = state.get("note") or ""

    if kind == "酒店":
        price = round(base["hotel4"] * factor)
        items = [{"name": "四星标准间（含双早）", "unit": "间/晚", "price": price},
                 {"name": "预估间数", "unit": "间", "price": rooms}]
        summary = f"四星 {price}/间/晚，含双早；按 {p['total']} 人估 {rooms} 间"
    elif kind == "车队":
        price = round(base["vehicle7"] * factor)
        items = [{"name": "7 座商务（含司机、油费、过路费）", "unit": "天", "price": price},
                 {"name": "建议车型", "unit": "—", "price": 0, "text": "7 座商务" if p["total"] <= 6 else "15 座中巴"}]
        summary = f"7 座商务 {price}/天，含司机与油费；按 {p['total']} 人建议 7 座商务"
    elif kind == "票务":
        train = round(base["ticket_avg"] * factor * 4.2 / 10) * 10
        items = [{"name": "高铁二等座（参考）", "unit": "人", "price": train},
                 {"name": "机票（参考区间）", "unit": "人", "price": f"{round(train * 3.2)}-{round(train * 4.1)}"}]
        summary = f"高铁二等座参考 {train}/人；机票波动大，报价请自留空间"
    elif kind == "地接社":
        hotel = round(base["hotel4"] * factor)
        vehicle = round(base["vehicle7"] * factor)
        items = [{"name": "住宿（四星含早）", "unit": "间/晚", "price": hotel},
                 {"name": "用车（7 座含司机油费）", "unit": "天", "price": vehicle},
                 {"name": "导游", "unit": "天", "price": round(base["guide_day"] * factor)},
                 {"name": "门票（首道）", "unit": "人", "price": round(base["ticket_avg"] * factor)}]
        summary = (f"四星 {hotel}/间/晚；7 座 {vehicle}/天；导游 {round(base['guide_day'] * factor)}/天；"
                   f"首道门票 {round(base['ticket_avg'] * factor)}/人")
    else:
        items, summary = [], "该角色不提供报价"

    quote = {"order_id": order_id, "kind": kind, "city": base["city"], "destination": dest,
             "state_key": _state_key(state),
             "party": p, "rooms": rooms, "price_factor": factor, "availability": avail,
             "note": note, "items": items, "summary": summary,
             "deadline": "今天 18:00 前确认" if avail in ("有货", "紧张") else "—"}
    store.save_quote(order_id, kind, quote)
    return quote


# ---------------------------------------------------------------- 资源方 Agent

ROLE_SYSTEM = """{role}

【这一单的客观事实（只能基于这些回答，不得编造或改动数字）】
城市：{city}
出行人构成：{party}
资源可用性：{availability}
报价：{summary}
回复时限：{deadline}
补充说明：{note}

【当前订单阶段】{stage_name}（{step_hint}）

【规矩】
1. 用微信口语，2-4 句，不要写成长篇正式文件；
2. 数字只能说上面给出的事实；客户问到你没有的信息，就说「我核实一下，X 点前回你」；
3. 不承诺流程以外的事（垫付、改合同、脱离定制师直接对接客户），一律让对方走定制师流程；
4. 不主动透露与当前阶段无关的后段信息（例如还没到行前就别提结算）；
5. 只输出你要说的话，不要 JSON、不要旁白。
"""

DEFER_VARIANTS = (
    "这个我这边现在还说不好——{reason}，你先跟客人那边对完流程，定下来在群里@我，我马上给你核。",
    "先给不了准数：{reason}。需求定下来在群里说一声，我立刻核给你。",
    "这会儿还报不了——{reason}。你把需求确认完在群里喊我一下，我马上核。",
)
DEFER_TPL = DEFER_VARIANTS[0]

GUIDE_TPL = ("{ask}\n\n客人那边我们先按原来的安排走，别让他们看出乱。"
             "怎么调你定，你说改我就改，行程的事我不自己动；要是涉及加钱或赔偿，"
             "得你先跟客人和公司确认，我这边只执行。")
GUIDE_TPL_IDLE = ("今天按计划走，客人挺配合，时间和集合点我都核过了。"
                  "后面有调整你群里说一声，我随时回。")

CUSTOMER_TPL_NAG = "行，那我等你消息。这个大概多久能给我个准信？我这边时间比较紧。"
CUSTOMER_TPL_IDLE = "好的，我知道了。你按这个方向先做，有进展发我。"

GUIDE_SYSTEM = """你是{speaker}，这一个团的{customer}（{party}）正在{destination}。
你现在在司导沟通群里跟定制师对接。

【这一单的客观情况】
已确认的资源：{resources}
本群已发生的事：{incidents}
订单阶段：{stage}

【规矩】
1. 你是导游/司机，不是定制师：不擅自改行程、不承诺赔偿、不跟客人谈价格与合同；
2. 只报告现象、说明现场影响、给出你能做到的备选（如「可以晚 30 分钟出发」「我可以先带客人去下一个点」）；
3. 需要改行程、加钱、赔偿、对接客人情绪的，一律请定制师拍板；
4. 微信口语，2-3 句，只输出你要说的话，不要旁白或 JSON。
"""

CUSTOMER_SYSTEM_IM = """你在扮演一位来中国旅行的客户，正在客户服务群里和你的定制师沟通。

【你的人设（必须保持）】
{customer}，{age}岁，{gender}，来自{market}，使用语言：{language}。
性格：{personality}
最初的需求：{intent}

【这一单的现状】
定制师已报的资源情况：{brief}
你在这个群里提过/抱怨过的事：{incidents}
订单阶段：{stage}

【规矩】
1. 你始终是客户：不出戏、不点评对方表现、不扮演教练、不替对方总结标准答案；
2. 口语、1-3 句；对方专业、问得清楚你就配合，对方含糊或拖延你可以不耐烦或追问；
3. 不问到你该知道的就不主动多给信息；预算、日期这类细节仍然按人设逐步释放；
4. 不用书面语、不写长段落；**你只说{language}**——对方用别的语言问，你也用{language}回答，
   不要翻译成中文，也不要为了迁就对方改说中文；
5. 只输出你的台词，不要任何旁白、括号说明或 JSON。
"""

STAGE_HINT = {
    0: "还在接单/首呼，资源方不宜介入",
    1: "正在做方案，可询价、比价",
    2: "等客户确认方案",
    3: "准备合同与保险",
    4: "客户确认合同，可锁资源",
    5: "客人已出团，行中",
    6: "行程结束，提交结算",
    7: "订单完成",
}


class SupplierService:
    """群矩阵 + 资源方事实 + 阶段门控。"""

    def __init__(self, store, llm: DeepSeekClient | None = None, practice=None) -> None:
        self._store = store
        self._llm = llm
        self._practice = practice

    # ---------- 群操作 ----------

    def rename(self, session_id: str, name: str) -> dict:
        """改群名（写系统消息留痕，群里所有人都看得到）。"""
        name = (name or "").strip()
        sess = self._store.session(session_id)
        if not sess:
            raise ValueError(f"未找到会话: {session_id}")
        if not name:
            raise ValueError("群名不能为空")
        if len(name) > 20:
            raise ValueError("群名最长 20 个字")
        old_name = sess["name"]
        self._store.rename_session(session_id, name)
        self._store.add_im_message(session_id, "系统", "system",
                                   f"群名已由「{old_name}」改为「{name}」", kind="system")
        return {"session_id": session_id, "name": name, "old_name": old_name}

    def add_members(self, session_id: str, names: list[str]) -> dict:
        """拉人进群：只能拉已加过联系方式的人（没加过的人拉不进来）。"""
        sess = self._store.session(session_id)
        if not sess:
            raise ValueError(f"未找到会话: {session_id}")
        order_id = sess.get("order_id") or ""
        added = self.added_contacts(order_id)
        members = self._members(sess)
        want = [n.strip() for n in (names or []) if n and n.strip()]
        known = {c["name"] for c in added.values()}
        joined, rejected = [], []
        for n in want:
            if n in members:
                continue
            if n not in known:
                rejected.append(n)
                continue
            members.append(n)
            joined.append(n)
        if joined:
            self._store.set_session_members(session_id, members)
            self._store.add_im_message(session_id, "系统", "system",
                                       f"你邀请 {('、'.join(joined))} 加入了群聊", kind="system")
        return {"session_id": session_id, "members": members, "joined": joined,
                "rejected": rejected}

    # ---------- 群 ----------

    # ---------- 联系人（学员级通讯录：跨订单只有一份，备注名自己起） ----------

    @staticmethod
    def hub_id(user_id: str) -> str:
        return f"im-hub-{user_id}"

    def _user(self, order_id: str) -> str:
        return (self._store.order(order_id) or {}).get("user_id") or "u-demo"

    @staticmethod
    def display(contact: dict) -> str:
        """对外显示：优先备注名，没有备注才用默认名。"""
        return (contact.get("remark") or "").strip() or contact.get("name") or ""

    def ensure_hub(self, user_id: str) -> dict:
        """资源大群：一个学员一个。所有地接 / 酒店 / 车队 / 票务 / 导游都在这里对接。"""
        sid = self.hub_id(user_id)
        rows = [c for c in self._store.contacts_for_user(user_id)
                if c.get("added_at") and c["kind"] != "客户"]
        members = ["我"] + [self.display(c) for c in rows]
        if not self._store.session(sid):
            self._store.upsert_session(sid, user_id, "资源对接群", "资源方", members,
                                       order_id="", code="hub")
            self._store.add_im_message(
                sid, "系统", "system",
                "这是你和目的地资源方的对接群。看到谁的联系方式，点他头像加好友。", kind="system")
        else:
            self._store.set_session_members(sid, members)
        return self._store.session(sid) or {}

    def contact_dm(self, user_id: str, kind: str, order_id: str = "") -> str:
        """某人（某类人）的单聊会话；没加过联系方式就返回空。"""
        for c in self._store.contacts_for_user(user_id):
            if not c.get("added_at") or c["kind"] != kind:
                continue
            cid = c.get("order_id") or ""
            if order_id and cid and cid != order_id:
                continue                     # 别的单的同类型联系人
            if kind == "客户" and order_id and c["name"] != self.names(order_id).get("客户"):
                continue                     # 别的单的客户
            return c.get("session_id") or ""
        return ""

    def rename_contact(self, contact_id: str, remark: str) -> dict:
        """给联系人起备注名；他的单聊会话名跟着变，资源大群成员名也刷新。"""
        row = self._store.contact(contact_id)
        if not row:
            raise ValueError(f"未找到联系人: {contact_id}")
        self._store.update_contact(contact_id, remark=(remark or "").strip())
        fresh = self._store.contact(contact_id) or {}
        sid = fresh.get("session_id") or ""
        if sid:
            self._store.rename_session(sid, self.display(fresh))
            self._store.add_im_message(sid, "系统", "system",
                                       f"你把「{fresh['name']}」的备注改成了「{self.display(fresh)}」",
                                       kind="system")
        self.ensure_hub(fresh.get("user_id") or "u-demo")
        return fresh

    def contacts_of_user(self, user_id: str) -> list[dict]:
        return [{**c, "display": self.display(c)} for c in self._store.contacts_for_user(user_id)
                if c.get("added_at")]

    def names(self, order_id: str) -> dict:
        """这一单的各类联系人叫什么（确定性派生）。"""
        row = self._store.order(order_id) or {}
        dest = (row.get("destination") or "目的地").rstrip("省市")
        city = CITY_BASE.get(row.get("destination") or "", {}).get("city") or dest
        customer = row.get("customer") or "客户"
        out = {}
        for spec in CONTACTS:
            out[spec.kind] = contact_identity(order_id, spec.kind, dest, city, customer)
        return out

    def _guide_ready(self, order_id: str) -> bool:
        return int((self._store.order(order_id) or {}).get("stage_index") or 0) >= 4

    def added_contacts(self, order_id: str) -> dict[str, dict]:
        """这一单涉及的人里，已经加过联系方式的（学员级通讯录里挑）。"""
        user = self._user(order_id)
        names = self.names(order_id)
        out: dict[str, dict] = {}
        for c in self._store.contacts_for_user(user):
            if not c.get("added_at"):
                continue
            # 通讯录是学员级的，跨单共用；这里必须按订单过滤，
            # 否则多单并行时会拿别单的地接/酒店/车队去投递，还漏掉本单自己的。
            cid = c.get("order_id") or ""
            if cid and cid != order_id:
                continue
            if c["kind"] == "客户":
                if c["name"] == names.get("客户"):
                    out["客户"] = c
                continue
            out.setdefault(c["kind"], c)
        return out

    def contact_catalog(self, order_id: str) -> list[dict]:
        """这一单能拿到哪些联系人：来源、能不能加、加没加、备注名。"""
        row = self._store.order(order_id)
        if not row:
            return []
        stage = int(row["stage_index"] or 0)
        names = self.names(order_id)
        user = row["user_id"]
        # 只认这一单自己的联系人，否则同名地接会把新单的人「顶掉」
        mine = [c for c in self._store.contacts_for_user(user)
                if (c.get("order_id") or "") in ("", order_id)]
        grabbed = self._store.has_action(order_id, "grab")
        called = self._store.has_action(order_id, "first_call")
        out = []
        for spec in CONTACTS:
            if spec.unlock == "first_call":
                ok = called
            elif spec.unlock == "grab":
                ok = grabbed
            elif spec.unlock == "contact:地接社":
                ok = "地接社" in self.added_contacts(order_id)
            elif spec.unlock == "contact:地接社+stage:4":
                ok = "地接社" in self.added_contacts(order_id) and stage >= 4
            else:
                ok = False
            default_name = names.get(spec.kind, spec.kind)
            rec = next((c for c in mine if c["kind"] == spec.kind and c["name"] == default_name), None)
            out.append({
                "contact_id": rec["contact_id"] if rec else
                f"ct-{user}-{spec.kind}-{_stable_hash(default_name) % 100000}",
                "kind": spec.kind, "name": default_name,
                "display": self.display(rec) if rec else default_name,
                "remark": (rec or {}).get("remark") or "",
                "phone": rec["phone"] if rec else _phone(order_id, spec.kind,
                                                         _stable_hash(f"{order_id}|{spec.kind}") % 10),
                "source": spec.source, "note": spec.note,
                "available": bool(ok), "added": bool(rec and rec.get("added_at")),
                "session_id": (rec or {}).get("session_id") or "",
                "from_order": order_id,
            })
        return out

    def add_contact(self, order_id: str, kind: str) -> dict:
        """加联系人：建一条单聊。没到条件的加不了（来源顺序要对）。"""
        cat = {c["kind"]: c for c in self.contact_catalog(order_id)}
        item = cat.get(kind)
        if not item:
            raise ValueError(f"这一单没有这类联系人: {kind}")
        if item["added"]:
            return {"contact": item, "session_id": item["session_id"], "already": True}
        if not item["available"]:
            raise ValueError(f"现在拿不到{kind}的联系方式（{item['source']}）")
        row = self._store.order(order_id) or {}
        user = row.get("user_id") or "u-demo"
        sid = item["session_id"] or f"im-dm-{user}-{kind}-{_stable_hash(item['name']) % 100000}"
        self._store.upsert_session(sid, user, item["name"], kind, ["我", item["name"]],
                                   order_id=order_id, code=f"dm-{kind}")
        self._store.save_contact(item["contact_id"], order_id, user, item["name"], kind,
                                 phone=item["phone"], source=item["source"], note=item["note"],
                                 added_at=time.strftime("%Y-%m-%d %H:%M:%S"), session_id=sid)
        self._store.add_im_message(
            sid, "系统", "system",
            f"你已添加「{item['name']}」（{kind} · {item['source']}），号码 {item['phone']}。",
            kind="system")
        self.ensure_hub(user)
        return {"contact": {**item, "added": True, "session_id": sid}, "session_id": sid,
                "already": False}

    def room_state(self, order_id: str, session_id: str) -> dict:
        """单聊 / 自己拉的群 / 资源大群都能发言（不再有"未添加联系人就不能说"）。"""
        return {"locked": False, "requires": "", "hint": ""}

    # ---------- 会话（资源大群 + 单聊 + 学员自己拉的群） ----------

    def _session_view(self, sid: str) -> dict | None:
        s = self._store.session(sid)
        if not s:
            return None
        return {"session_id": s["session_id"], "code": s.get("code") or "", "name": s["name"],
                "kind": s["kind"], "members": self._members(s),
                "order_id": s.get("order_id") or "", "locked": False, "lock_hint": "",
                "present": True}

    def ensure_groups(self, order_id: str) -> list[dict]:
        """（兼容旧调用）本单可用的会话：资源大群 + 这一单已加联系人的单聊。"""
        row = self._store.order(order_id)
        if not row:
            return []
        payload = json.loads(row["payload"] or "{}")
        customer = row["customer"] or "客户"
        dest = (row["destination"] or "目的地").rstrip("省市")
        hub = self._session_view(self.ensure_hub(row["user_id"])["session_id"]) or {}
        hub.update({"customer": customer, "destination": dest,
                    "language": payload.get("language", "中文")})
        out = [hub]
        for kind, c in self.added_contacts(order_id).items():
            view = self._session_view(c.get("session_id") or "")
            if not view:
                continue
            view.update({"customer": customer, "destination": dest,
                         "language": payload.get("language", "中文")})
            out.append(view)
        return out

    def group_for(self, order_id: str, code: str) -> dict | None:
        return self.group_by_name(order_id, {
            "customer": "客户服务群", "supplier": "地接资源信息群", "hotel": "酒店沟通群",
            "vehicle": "车队沟通群", "ticket": "票务沟通群", "guide": "司导沟通群",
        }.get(code, code))

    def group_by_name(self, order_id: str, name: str) -> dict | None:
        """按场景名找会话：客户/资源类 → 对应单聊；地接资源信息群 → 资源大群。"""
        user = self._user(order_id)
        if name == "票务沟通群":
            # 票务是平台通道，不进你的通讯录；平台票务在你的资源群里对接
            return self._session_view(self.ensure_hub(user)["session_id"])
        # 学员自己按场景名拉的群优先：他在群里问的事，回应也该落在群里
        for sess in self._store.sessions(user):
            if sess["name"] == name and (sess.get("order_id") or "") == order_id:
                return self._session_view(sess["session_id"])
        want = {"客户服务群": "客户", "酒店沟通群": "酒店",
                "车队沟通群": "车队"}.get(name)
        if want:
            sid = self.contact_dm(user, want, order_id)
            return self._session_view(sid) if sid else None
        if name == "司导沟通群":
            sid = self.contact_dm(user, "导游", order_id) or self.contact_dm(user, "司机", order_id)
            return self._session_view(sid) if sid else None
        if name in ("地接资源信息群", "资源对接群"):
            return self._session_view(self.ensure_hub(user)["session_id"])
        return None

    # ---------- 该单该资源方的客观事实 ----------

    def facts(self, order_id: str, kind: str) -> dict:
        """取该单该资源方的客观事实：约束没变就复用落库结果，约束变了就重算。"""
        quote = self._store.quote(order_id, kind)
        if quote and quote.get("state_key") == _state_key(_state(self._store, kind, order_id)):
            return quote
        return build_quote(self._store, order_id, kind)

    def apply_fact(self, order_id: str, kind: str, patch: dict) -> dict:
        """把导演注入的事件落到**这一单**的资源方事实上（订单级覆盖，不牵连别的订单）。

        事件与事实必须同源：群里说了「酒店超售」，那么学员再去酒店群问，
        得到的也必须是超售后的口径，否则同一个群里前后矛盾。
        """
        row = self._store.order(order_id) or {}
        user_id = row.get("user_id") or "u-demo"
        merged = {**self._store.supplier_state_for(user_id, kind, order_id),
                  **{k: v for k, v in (patch or {}).items() if v not in (None, "")}}
        self._store.set_supplier_state(user_id, kind, merged, order_id=order_id)
        return merged

    def facts_text(self, order_id: str) -> str:
        """把该单已询到的资源事实压成一行，供客户/司导 agent 参考（不编数字）。"""
        parts = []
        for kind in ("地接社", "酒店", "车队", "票务"):
            q = self._store.quote(order_id, kind)
            if q and q.get("summary"):
                parts.append(f"{kind}：{q['summary']}")
        return "；".join(parts) or "还没有向地接社/酒店/车队/票务询过价"

    # ---------- 群应答总入口 ----------

    def respond(self, session_id: str, question: str, order_id: str = "") -> dict | None:
        """学员在某个会话里发言 → 由该会话里的角色按自己的事实与规矩应答。"""
        sess = self._store.session(session_id)
        if not sess:
            return None
        # 资源大群：没有"这一单"的上下文——前端会告诉我他在弄哪一单，没给就按最近动过的那单
        if (sess.get("code") or "") == "hub" or not sess.get("order_id"):
            return self._hub_reply(sess, question, order_id)
        row = self._store.order(sess["order_id"])
        if not row:
            return None
        kind = sess["kind"]
        if kind == "客户":
            return self._customer_reply(sess, row, question)
        if kind in ("导游", "司机", "行中"):
            return self._guide_reply(sess, row, question)
        if kind in ("地接社", "酒店", "车队", "票务"):
            return self._supplier_reply(sess, row, question)
        # 学员自己拉的群：看群里有谁——有客户就客户答，有资源方就资源方答
        members = " ".join(self._members(sess))
        user = sess.get("user_id") or "u-demo"
        if self.names(row["order_id"]).get("客户") in members:
            return self._customer_reply(sess, row, question)
        return self._supplier_reply({**sess, "kind": "地接社"}, row, question)

    def _latest_order(self, user_id: str) -> dict | None:
        """学员最近在跟的一单：未完成里挑「最后一次动手最晚」的那单。

        资源大群没有订单上下文，只能这样推断；用"最后动作时间"而不是创建时间，
        才符合"我正在弄哪一单"的直觉。
        """
        rows = [o for o in self._store.orders(user_id) if o["status"] != "禁用"]
        if not rows:
            return None
        active = [o for o in rows if int(o["stage_index"] or 0) < 7] or rows

        def touched(o: dict) -> str:
            acts = self._store.actions(o["order_id"]) if hasattr(self._store, "actions") else []
            last = max([a.get("at") or "" for a in acts], default="")
            ev = self._store.evidence(o["order_id"]) or []
            last_ev = max([e.get("created_at") or "" for e in ev], default="")
            return max(last, last_ev, o.get("created_at") or "")

        return sorted(active, key=touched, reverse=True)[0]

    def _hub_reply(self, sess: dict, question: str, order_id: str = "") -> dict:
        """资源大群里的应答：按"他正在弄的那一单"的地接口径回；没给就用最近动过的单。"""
        user = sess.get("user_id") or "u-demo"
        row = self._store.order(order_id) if order_id else None
        if not row or (row.get("user_id") or user) != user:
            row = self._latest_order(user)
        if not row:
            return {"sender": "资源对接群", "role": "other",
                    "content": "你还没在跟的单，等接到单我再给你安排资源。"}
        names = self.names(row["order_id"])
        who = names.get("地接社") or "地接"
        out = self._supplier_reply({"session_id": sess["session_id"], "order_id": row["order_id"],
                                    "kind": "地接社", "members": ["我", who]}, row, question)
        if out:
            out["sender"] = who          # 名字在界面里已经显示，正文里不再重复「（姓名）」
        return out or {"sender": who, "role": "other", "content": "你说哪一单？把目的地和人数发我。"}

    def ask(self, order_id: str, kind: str, question: str) -> dict | None:
        """不带群的一次性询价（学员工具用）：用的还是这一单的同一套硬事实。

        口径必须与群里一致，否则学员在工具里问到的价和群里问到的价会打架。
        """
        row = self._store.order(order_id)
        if not row or kind not in KIND_MIN_STAGE:
            return None
        code = next((g.code for g in GROUPS if g.kind == kind), "")
        sess = {"session_id": f"ask-{order_id}-{code or 'x'}", "order_id": order_id,
                "kind": kind, "name": f"{kind}询价", "code": code, "members": []}
        return self._supplier_reply(sess, row, question)

    def _supplier_reply(self, sess: dict, row: dict, question: str) -> dict | None:
        order_id, kind = sess["order_id"], sess["kind"]
        if kind not in KIND_MIN_STAGE:
            return None
        stage = int(row["stage_index"] or 0)
        if stage < KIND_MIN_STAGE[kind]:
            reason = ("还没到锁资源的阶段" if kind in ("酒店", "车队", "票务")
                      else "需求还没确认完")
            return {"sender": self._speaker_of(sess, kind), "role": "other",
                    "content": self._defer_text(sess, reason, self._speaker_of(sess, kind)),
                    "deferred": True}
        quote = self.facts(order_id, kind)
        text = self._phrase(quote, row, question)
        return {"sender": self._speaker_of(sess, kind), "role": "other", "content": text,
                "deferred": False, "quote": quote}

    def _guide_reply(self, sess: dict, row: dict, question: str) -> dict | None:
        """司导群：导游/司机只报告现象、听定制师安排，不自行改行程、不跟客人谈钱。"""
        order_id = sess["order_id"]
        if int(row["stage_index"] or 0) < KIND_MIN_STAGE.get("行中", 4):
            return {"sender": self._speaker_of(sess, "行中"), "role": "other", "deferred": True,
                    "content": "我这边还没排到这单的班，等你们合同和行程定下来再拉我进群吧。"}
        incidents = self._incidents(sess["session_id"])
        ask = incidents[-1]["body"] if incidents else ""
        facts = "；".join(f"{i['title']}：{i['body']}" for i in incidents[-3:]) or "无"
        if self._llm is None:
            text = GUIDE_TPL.format(ask=ask) if ask else GUIDE_TPL_IDLE
            return {"sender": self._speaker_of(sess, "行中"), "role": "other", "content": text,
                    "deferred": False}
        system = GUIDE_SYSTEM.format(
            speaker=(self._members(sess) or ["我"])[-1], customer=row.get("customer") or "客人",
            destination=(row.get("destination") or "目的地").rstrip("省市"),
            party=json.loads(row["payload"] or "{}").get("party") or "人数待确认",
            resources=self.facts_text(order_id),
            incidents=facts,
            stage=ORDER_STEPS[min(int(row["stage_index"] or 0), len(ORDER_STEPS) - 1)])
        return {"sender": self._speaker_of(sess, "行中"), "role": "other", "deferred": False,
                "content": self._say(system, question) or (GUIDE_TPL.format(ask=ask) if ask else GUIDE_TPL_IDLE)}

    def _customer_reply(self, sess: dict, row: dict, question: str) -> dict | None:
        """客户服务群：客户按自己的人设与情绪档回话，不出戏、不点评、不教学。"""
        payload = json.loads(row["payload"] or "{}")
        incidents = self._incidents(sess["session_id"])
        facts = "；".join(f"{i['title']}：{i['body']}" for i in incidents[-3:]) or "无"
        if self._llm is None:
            text = CUSTOMER_TPL_NAG if incidents else CUSTOMER_TPL_IDLE
            return {"sender": "客户", "role": "other", "content": text, "deferred": False}
        p = persona_for(row.get("customer") or "客户", row.get("destination") or "",
                        payload.get("source_market", "香港"), payload.get("language", "中文"),
                        row["order_id"], payload.get("personality") or "")
        system = CUSTOMER_SYSTEM_IM.format(
            customer=row.get("customer") or "客户",
            age=p.age, gender=p.gender,
            market=payload.get("source_market", "香港"),
            language=p.language,
            personality=payload.get("personality") or "说话直接，时间不多",
            intent=payload.get("intent") or "想去旅行，具体没想好",
            brief=self.facts_text(row["order_id"]),
            incidents=facts,
            stage=ORDER_STEPS[min(int(row["stage_index"] or 0), len(ORDER_STEPS) - 1)])
        return {"sender": "客户", "role": "other", "deferred": False,
                "content": self._say(system, question) or CUSTOMER_TPL_IDLE}

    # ---------- 上下文 ----------

    def _incidents(self, session_id: str) -> list[dict]:
        """本群里由导演注入、且还没被学员处理完的事件。"""
        return self._store.incidents_by_session(session_id)

    def _defer_text(self, sess: dict, reason: str, sender: str = "") -> str:
        """阶段没到时的推诿话术：同一群里连着问，别一字不差地重复自己上一句。"""
        last = ""
        try:
            for m in reversed(self._store.im_messages(sess["session_id"])):
                if not sender or str(m.get("sender") or "") == sender:
                    last = str(m.get("content") or "").strip()
                    break
        except Exception:
            last = ""
        for tpl in DEFER_VARIANTS:
            text = tpl.format(reason=reason)
            if text.strip() != last:
                return text
        return DEFER_VARIANTS[0].format(reason=reason)

    def _say(self, system: str, question: str) -> str:
        try:
            out = self._llm.chat([{"role": "system", "content": system},
                                  {"role": "user", "content": question}],
                                 temperature=0.7, max_tokens=260)
            return (out or "").strip()
        except Exception:
            return ""

    def _phrase(self, quote: dict, row: dict, question: str) -> str:
        if self._llm is None:
            return self._template(quote, question)
        system = ROLE_SYSTEM.format(
            role=f"你是{quote['kind']}（{quote['city']}），正在为定制师提供这一单的资源。",
            city=quote["city"],
            party=f"{quote['party']['adults']} 大 {quote['party']['children']} 小" if quote["party"]["known"]
                  else "客人还没说清（先按 2 人估）",
            availability=quote["availability"], summary=quote["summary"],
            deadline=quote["deadline"], note=quote["note"] or "无",
            stage_name=ORDER_STEPS[min(int(row["stage_index"] or 0), len(ORDER_STEPS) - 1)],
            step_hint=STAGE_HINT.get(int(row["stage_index"] or 0), ""))
        try:
            out = self._llm.chat([{"role": "system", "content": system},
                                  {"role": "user", "content": question}],
                                 temperature=0.6, max_tokens=300)
            text = (out or "").strip()
            return text or self._template(quote, question)
        except Exception:
            return self._template(quote, question)

    @staticmethod
    def _template(quote: dict, question: str) -> str:
        return (f"{quote['summary']}。目前{quote['availability']}，"
                f"{quote['deadline']}。有要我留的你说一声。")

    @staticmethod
    def _speaker(kind: str) -> str:
        for g in GROUPS:
            if g.kind == kind:
                named = [m for m in g.members if "·" in m]
                return ((named[0] if named else g.members[-1])
                        .replace("{dest}", "").replace("{customer}", "客户"))
        return kind

    @staticmethod
    def _members(sess: dict) -> list[str]:
        """库里 members 存的是 JSON 文本，取出来要还原成列表。"""
        members = sess.get("members")
        if isinstance(members, str):
            try:
                members = json.loads(members or "[]")
            except Exception:
                members = []
        return [str(m) for m in (members or [])]

    @classmethod
    def _speaker_of(cls, sess: dict, kind: str) -> str:
        """群里的发言人：优先用这个群里带名字的成员（江苏地接·张经理 / 导游·小周）。"""
        for m in cls._members(sess):
            if "·" in m:
                return m
        return cls._speaker(kind)