"""AI 客户 Agent —— 扮演 S2 首呼中的客户（PRD 第 2.3.2 节）。

关键：客户必须「直接、可能不耐烦、需求分批释放、预算模糊」，
否则考不出学员的需求挖掘能力（尤其 C2.2 预算口径、C1.6 应对不耐烦）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .base import AgentContext, BaseAgent
from .llm import DeepSeekClient


@dataclass
class CustomerPersona:
    name: str = "王女士"
    nationality: str = "中国"
    age: str = "38"
    gender: str = "女"
    language: str = "中文"          # 客户说的语言标签（中文 / English / 日本語 …）
    personality: str = "说话直接，时间紧，不太有耐心"
    trip_hint: str = "想去云南玩，和家人一起"
    preferences: str = ""           # 语音提示词：偏好
    quirks: str = ""                # 语音提示词：说话习惯
    hidden: str = ""                # 语音提示词：隐藏诉求
    details: dict = field(default_factory=dict)
    traits: list[str] = field(default_factory=lambda: [
        "时间不多，说话直接，可能催促",
        "需求模糊，第一次不会说全，被追问才补充",
        "预算只说「性价比高」「别太贵」，不说数字，除非被专业地追问",
        "连续被追问超过 3 个问题会不耐烦",
    ])

    def voice_profile(self) -> dict:
        """给语音提示词用的字典视图 —— 与文本人设同源，避免两套人设打架。"""
        d = {"name": self.name, "nationality": self.nationality, "age": self.age,
             "gender": self.gender, "language": self.language,
             "personality": self.personality, "preferences": self.preferences,
             "quirks": self.quirks, "hidden": self.hidden}
        d.update(self.details or {})
        return d


def build_customer_system(persona: CustomerPersona) -> str:
    traits = "\n".join("- " + t for t in persona.traits)
    return f"""你在扮演一位正在接听定制师首呼电话的客户，用于定制师实训测评。

【你的身份】
{persona.name}，{persona.age}岁，{persona.gender}，来自{persona.nationality}。
性格：{persona.personality}
出行意向：{persona.trip_hint}

【你的特征（必须保持）】
{traits}

【语言（硬约束，最高优先级）】
- 你只会说{persona.language}。**无论对方用什么语言提问，你一律用{persona.language}回答**，
  不要翻译成中文，也不要为了迁就对方改说中文。
- 保持这个语言的口语习惯与称呼方式，不要写成书面语。

【对话规则】
1. 你始终是客户，不出戏，不点评对方表现，不扮演教练。
2. 用口语、简短回复（1-3 句）。对方问得好你就配合，问得差你就更敷衍或不耐烦。
3. 需求分批释放：第一轮只说个大概（去哪、和谁），对方专业追问时才逐步补充人数、日期、预算等。
4. 被问到预算时，回答「性价比高就行」「别太贵」这类模糊说法；只有对方明确追问「人均还是总价、大概区间、含不含机票」时，才给出更具体的口径。
5. 如果对方连续追问超过 3 个问题还没回应你的话，就表现出不耐烦（如「你问题怎么这么多」「我很忙，你直接说重点」）。
6. 只输出你的台词，不要任何旁白、括号说明或 JSON。
"""


class CustomerAgent(BaseAgent):
    name = "customer"

    def __init__(self, llm: DeepSeekClient, persona: CustomerPersona | None = None) -> None:
        super().__init__(llm)
        self.persona = persona or CustomerPersona()
        self._system = build_customer_system(self.persona)

    def opening(self, ctx: AgentContext) -> str:
        """客户被动接听：由定制师先开口，这里只给一个简短应答。"""
        reply = self._llm.chat(
            [{"role": "system", "content": self._system},
             {"role": "user", "content": "（定制师刚打来电话，你先接起）请给出你的第一句应答。"}],
            temperature=0.8, max_tokens=120)
        ctx.add("assistant", reply.strip())
        return reply.strip()

    def reply(self, ctx: AgentContext, guide_message: str) -> str:
        ctx.add("user", guide_message)
        messages = [{"role": "system", "content": self._system}] + ctx.messages
        reply = self._llm.chat(messages, temperature=0.8, max_tokens=200)
        ctx.add("assistant", reply.strip())
        return reply.strip()


# 本平台只做入境接待：客人来自港澳台 / 新加坡 / 海外，中文单同样是入境单。
# 客源地 -> 该客源市场的典型习惯（决定客户 Agent 会怎么问、在意什么）
SOURCE_PROFILES: dict[str, dict[str, str]] = {
    "香港": {"docs": "回乡证", "pay": "八达通与信用卡，很少用内地支付",
             "im": "WhatsApp", "note": "对内地景区预约制、实名制不熟，习惯先看行程再谈价"},
    "澳门": {"docs": "回乡证", "pay": "澳门信用卡，习惯港币/澳门币",
             "im": "WeChat / WhatsApp", "note": "出行节奏偏慢，重视餐饮与住宿品质"},
    "台湾": {"docs": "台胞证", "pay": "台湾信用卡，关心能否刷卡",
             "im": "Line", "note": "对内地交通与高铁购票流程不熟，关注证件与实名问题"},
    "新加坡": {"docs": "新加坡护照", "pay": "信用卡与 PayNow，关心汇率",
               "im": "WhatsApp / Telegram", "note": "英文与中文混用，重视效率与明确报价"},
}
DEFAULT_SOURCE_PROFILE = {"docs": "护照", "pay": "国际信用卡", "im": "WhatsApp / Email",
                          "note": "对内地旅游流程不熟，关心证件、支付与网络"}

_AGES = ("29", "34", "38", "42", "47", "53")


def stable_gender_age(order_id: str) -> tuple[str, str]:
    """按订单号稳定派生性别与年龄：同一单每次进来都是同一个人，不同单会换人。"""
    seed = int(hashlib.md5((order_id or "order").encode("utf-8")).hexdigest()[:8], 16)
    return ("男" if seed % 2 else "女"), _AGES[(seed >> 3) % len(_AGES)]


def persona_for(customer: str, destination: str, source_market: str = "香港",
                language: str = "中文", order_id: str = "", personality: str = "") -> CustomerPersona:
    """订单级客户人设 —— 语音通话、文本通话、群聊共用这一份。"""
    prof = SOURCE_PROFILES.get(source_market, DEFAULT_SOURCE_PROFILE)
    gender, age = stable_gender_age(order_id or f"{source_market}-{customer}")
    lang = (language or "中文").strip()
    traits = [
        f"你是{source_market}客人，来内地旅游，日常用{lang}沟通，用词习惯与内地不同",
        f"证件：{prof['docs']}；你在意入境与证件办理是否顺畅",
        f"支付习惯：{prof['pay']}；你不确定内地能不能刷卡、要不要换钱",
        f"常用通讯工具：{prof['im']}；你不一定用微信，可能会问能不能加其他联系方式",
        prof["note"],
        "时间不多，说话直接；需求分批释放，第一次不会说全",
        "预算只说「性价比高」「别太贵」，除非对方专业地追问口径",
        "连续被追问超过 3 个问题会不耐烦",
    ]
    if lang != "中文":
        traits.insert(0, f"你只说{lang}；对方用中文提问你也用{lang}回答，不做翻译")
    return CustomerPersona(
        name=customer,
        nationality=source_market,
        age=age,
        gender=gender,
        language=lang,
        personality=personality or "说话直接，时间紧，不太有耐心",
        trip_hint=f"想来内地去{destination}玩，带家人一起",
        preferences=f"重视证件与支付是否顺畅，关心行程节奏与住宿品质",
        quirks=f"用{lang}保持本地口音与用词习惯",
        hidden="担心入境手续、能不能刷卡、行程会不会太赶",
        details={"docs": prof["docs"]},
        traits=traits,
    )
