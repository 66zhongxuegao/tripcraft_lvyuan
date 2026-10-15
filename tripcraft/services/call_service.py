"""通话服务 —— 订单绑定的实时客户 Agent。

两种模式：
  - text：学员输入一句 → 客户 Agent 回复一句（文本链路，DeepSeek）。
  - voice：浏览器麦克风 ⇄ DashScope Qwen-Omni-Realtime 流式语音（见 voice/bridge.py）。

两种模式的每一句都会写回数据库（call_session / call_line），并在通话结束时
登记为本单的实战证据，供评分 Agent 评。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..agents.base import AgentContext
from ..agents.customer import CustomerAgent, CustomerPersona
from ..agents.llm import DeepSeekClient

# 客户人设只有一份定义（agents/customer.py）：语音通话、文本通话、群聊共用，
# 避免出现「语音说德语、文本说中文」这种同一个客人自相矛盾的情况。
from ..agents.customer import persona_for  # noqa: E402  （放在此处以免改动既有导入顺序）


@dataclass
class CallSession:
    session_id: str
    order_id: str
    customer: str
    destination: str
    source_market: str = "香港"
    language: str = "中文"
    personality: str = ""
    llm: DeepSeekClient | None = None
    mode: str = "text"
    lines: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    ended: bool = False
    _agent: CustomerAgent | None = field(default=None, init=False)
    _ctx: AgentContext | None = field(default=None, init=False)

    def persona(self):
        """本单客户人设 —— 语音/文本/群聊共用同一份。"""
        return persona_for(self.customer, self.destination, self.source_market,
                           self.language, self.order_id, self.personality)

    def _ensure_agent(self) -> None:
        if self._agent is None:
            if self.llm is None:
                raise RuntimeError("未配置 LLM（缺少 DEEPSEEK_API_KEY）")
            self._agent = CustomerAgent(self.llm, persona_for(
                self.customer, self.destination, self.source_market, self.language,
                self.order_id, self.personality))
            self._ctx = AgentContext(instance_id=self.session_id, user_id="u-demo")

    def add(self, who: str, text: str) -> dict:
        line = {"who": who, "text": text, "at": self._stamp()}
        self.lines.append(line)
        return line

    def opening(self) -> str:
        self._ensure_agent()
        assert self._agent is not None and self._ctx is not None
        line = self._agent.opening(self._ctx)
        self.add("agent", line)
        return line

    def reply(self, text: str) -> str:
        self._ensure_agent()
        assert self._agent is not None and self._ctx is not None
        self.add("student", text)
        line = self._agent.reply(self._ctx, text)
        self.add("agent", line)
        return line

    def transcript(self) -> str:
        return "\n".join(
            ("客户: " if l["who"] == "agent" else "定制师: ") + l["text"] for l in self.lines
        )

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id, "order_id": self.order_id,
            "customer": self.customer, "destination": self.destination,
            "source_market": self.source_market, "language": self.language,
            "mode": self.mode, "lines": self.lines,
            "turns": sum(1 for l in self.lines if l["who"] == "student"),
            "ended": self.ended,
        }

    def _stamp(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime())


class CallService:
    """按订单维护通话会话。文本链路走内存 + 落库；语音链路由 voice/bridge.py 复用本类。"""

    def __init__(self, llm: DeepSeekClient | None = None, store=None,
                 practice=None) -> None:
        self._llm = llm
        self._store = store
        self._practice = practice
        self._sessions: dict[str, CallSession] = {}

    def _require_llm(self) -> DeepSeekClient:
        if self._llm is None:
            raise RuntimeError("未配置 LLM（缺少 DEEPSEEK_API_KEY）")
        return self._llm

    def open_session(self, order_id: str, customer: str, destination: str,
                     mode: str = "text", source_market: str = "香港",
                     language: str = "中文", personality: str = "") -> CallSession:
        sid = f"call-{order_id}-{int(time.time() * 1000) % 1000000}"
        sess = CallSession(session_id=sid, order_id=order_id, customer=customer,
                           destination=destination, source_market=source_market,
                           language=language, personality=personality,
                           llm=self._llm, mode=mode)
        self._sessions[sid] = sess
        if self._store is not None:
            self._store.save_call_session(sid, order_id, "u-demo", customer, destination, mode)
        return sess

    def start(self, order_id: str, customer: str, destination: str,
              source_market: str = "香港", language: str = "中文",
              personality: str = "") -> CallSession:
        """文本模式：建立会话并让客户先说第一句。"""
        sess = self.open_session(order_id, customer, destination, mode="text",
                                 source_market=source_market, language=language,
                                 personality=personality)
        self._require_llm()
        sess.opening()
        self._persist(sess)
        return sess

    def get(self, sid: str) -> CallSession | None:
        return self._sessions.get(sid)

    def say(self, sid: str, text: str) -> str | None:
        sess = self._sessions.get(sid)
        if sess is None:
            return None
        line = sess.reply(text)
        self._persist(sess)
        return line

    # ---- 落库 / 收口 ----

    def _persist(self, sess: CallSession) -> None:
        if self._store is None:
            return
        seen = getattr(sess, "_persisted", 0)
        for line in sess.lines[seen:]:
            self._store.add_call_line(sess.session_id, line["who"], line["text"])
        setattr(sess, "_persisted", len(sess.lines))

    def record_line(self, sess: CallSession, who: str, text: str) -> None:
        if not text.strip():
            return
        sess.add(who, text)
        if self._store is not None:
            self._store.add_call_line(sess.session_id, who, text)
            setattr(sess, "_persisted", len(sess.lines))

    def end(self, sid: str) -> dict | None:
        """结束通话：登记实战证据，并写一条联系记录。"""
        sess = self._sessions.get(sid)
        if sess is None:
            return None
        if sess.ended:
            return sess.snapshot()
        sess.ended = True
        self._persist(sess)
        text = sess.transcript()
        if text and self._practice is not None:
            self._practice.record_evidence(sess.order_id, "call", text, ref=sid)
        if self._store is not None:
            turns = sum(1 for l in sess.lines if l["who"] == "student")
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            status = f"已接通({turns}轮)" if turns else "未接通"
            self._store.add_contact(sess.order_id, "电话", stamp, status, True,
                                    f"{'语音' if sess.mode == 'voice' else '文字'}通话，共 {turns} 轮")
        return sess.snapshot()