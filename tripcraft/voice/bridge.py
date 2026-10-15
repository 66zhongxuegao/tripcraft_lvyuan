"""浏览器 ⇄ DashScope Qwen-Omni-Realtime 的语音中继（FastAPI WebSocket）。

职责：
  1. 浏览器只连本服务，DashScope 密钥留在后端（不落到前端）；
  2. 上行：浏览器麦克风 PCM16/16k -> input_audio_buffer.append；
  3. 下行：模型 24k PCM 音频增量 + 双方转写文本 -> 浏览器；
  4. 通话结束后：把转写写回 call_session/call_line，并登记为本单实战证据。

协议（JSON 文本帧）：
  浏览器 -> 服务端
    {"type":"audio","audio":"<base64 pcm16 16k>"}
    {"type":"commit"}                     # 手动提交一轮（默认由服务端 VAD 自动提交）
    {"type":"text","text":"..."}          # 无麦/调试：用文本触发一轮
    {"type":"stop"}                       # 主动结束
  服务端 -> 浏览器
    {"type":"ready"}
    {"type":"audio","audio":"<base64 pcm16 24k>"}
    {"type":"transcript","who":"agent|student","text":"...","final":bool}
    {"type":"state","value":"listening|thinking|speaking|idle"}
    {"type":"error","message":"..."}
    {"type":"closed"}
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..agents.customer import CustomerPersona
from ..agents.customer import persona_for
from .language_profiles import LANG_COUNTRIES, VOICE_LANG

ROOT = Path(__file__).resolve().parents[2]
TRACE_FILE = ROOT / "logs" / "voice_trace.jsonl"
from .realtime_qwen import (
    INPUT_RATE,
    OUTPUT_RATE,
    QwenRealtimeClient,
    build_scene_voice_instructions,
    resolve_env,
)

# 展示用语言名 -> 语言码
LANG_CODES = {
    "中文": "zh", "汉语": "zh", "简体中文": "zh",
    "English": "en", "英语": "en",
    "日本語": "ja", "日语": "ja", "한국어": "ko", "韩语": "ko",
    "Français": "fr", "法语": "fr", "Deutsch": "de", "德语": "de",
    "Español": "es", "西班牙语": "es", "Русский": "ru", "俄语": "ru",
    "العربية": "ar", "阿拉伯语": "ar", "Italiano": "it", "意大利语": "it",
    "Português": "pt", "葡萄牙语": "pt", "Tiếng Việt": "vi", "越南语": "vi",
    "Bahasa Indonesia": "id", "印尼语": "id", "ไทย": "th", "泰语": "th",
    "Türkçe": "tr", "土耳其语": "tr",
}


def lang_code(label: str) -> str:
    return LANG_CODES.get((label or "").strip(), "zh")


def pick_voice(lang: str, gender: str) -> str:
    table = VOICE_LANG.get(lang) or VOICE_LANG["zh"]
    return table["male"] if gender == "男" else table["female"]


def build_scene(order_customer: str, destination: str, stage_name: str) -> dict[str, Any]:
    return {
        "opening": f"定制师给你打电话，沟通来内地去{destination}的行程。",
        "location": "电话沟通",
        "stage_title": stage_name or "首呼与需求挖掘",
        "objective": "问清人数、日期、预算口径、住宿与交通意向，并约定后续联系时间",
        "situation": (
            "你时间不多，说话直接；需求分批释放，第一次不会说全；"
            "预算只说「性价比高」「别太贵」，除非对方专业地追问口径。"
        ),
    }


def build_persona(customer_name: str, destination: str, lang_label: str,
                  source_market: str = "", order_id: str = "", personality: str = "") -> dict:
    """语音提示词用的人设 —— 直接取自订单级人设（agents/customer.py），
    和文本通话、群聊是同一份，避免同一个客人换条链路就换个人。"""
    p = persona_for(customer_name, destination, source_market, lang_label, order_id, personality)
    return p.voice_profile()


def map_event(ev: dict) -> dict | None:
    """DashScope 事件 -> 浏览器事件（None = 不转发）。"""
    t = ev.get("type", "")
    if t == "session.updated":
        return {"type": "ready"}
    if t == "response.audio.delta":
        delta = ev.get("delta") or ev.get("audio")
        return {"type": "audio", "audio": delta} if delta else None
    if t == "response.audio_transcript.delta":
        return {"type": "transcript", "who": "agent", "text": ev.get("delta", ""), "final": False}
    if t == "response.audio_transcript.done":
        return {"type": "transcript", "who": "agent", "text": ev.get("transcript", ""), "final": True}
    if t in ("conversation.item.input_audio_transcription.completed",
             "conversation.item.input_audio_transcription.done"):
        return {"type": "transcript", "who": "student", "text": ev.get("transcript", ""), "final": True}
    if t == "input_audio_buffer.speech_started":
        return {"type": "state", "value": "listening"}
    if t == "input_audio_buffer.speech_stopped":
        return {"type": "state", "value": "thinking"}
    if t == "response.created":
        return {"type": "state", "value": "speaking"}
    if t == "response.done":
        return {"type": "state", "value": "listening"}
    if t in ("error", "ws_error"):
        return {"type": "error", "message": json.dumps(ev, ensure_ascii=False)[:400]}
    if t == "closed":
        return {"type": "closed"}
    return None


class VoiceBridge:
    """一次语音通话的中继会话。"""

    def __init__(self, ws, order: dict, customer_name: str, destination: str,
                 call_svc, practice) -> None:
        self.ws = ws
        self.order = order
        self.customer_name = customer_name
        self.destination = destination
        self.call_svc = call_svc
        self.practice = practice
        self.client: QwenRealtimeClient | None = None
        self.lines: list[dict] = []
        self._agent_buf = ""
        self._pending = ""
        self.session_id = ""
        # ---- 通话埋点：上游到底有没有就绪、双方各发了多少音频 ----
        self.started_at = time.time()
        self.ready_ok = False
        self.ready_ms: int | None = None
        self.audio_in_frames = 0
        self.audio_in_bytes = 0
        self.audio_out_frames = 0
        self.audio_out_bytes = 0

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(ev: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

        label = self.order.get("language", "中文")
        lang = lang_code(label)
        p = persona_for(self.customer_name, self.destination, self.order.get("source_market", ""),
                        label, self.order.get("order_id", ""), self.order.get("personality", ""))
        persona = p.voice_profile()
        scene = build_scene(self.customer_name, self.destination, self.order.get("stage_name", ""))
        scene["objective"] = (
            "问清人数、日期、预算口径、住宿与交通意向，"
            "确认客源地证件与入境是否顺畅，并约定后续联系时间与方式"
        )
        instructions = build_scene_voice_instructions(scene, persona, lang)

        try:
            api_key, ws_url, model = resolve_env()
        except RuntimeError as exc:
            await self._send({"type": "error", "message": str(exc)})
            return

        sess = self.call_svc.open_session(self.order["order_id"], self.customer_name,
                                          self.destination, mode="voice",
                                          source_market=self.order.get("source_market", "香港"),
                                          language=label,
                                          personality=self.order.get("personality", ""))
        self.session_id = sess.session_id

        voice = pick_voice(lang, p.gender)
        client = QwenRealtimeClient(
            api_key, ws_url, model, instructions,
            voice=voice, on_event=on_event)
        self.client = client
        client.connect()
        if not await asyncio.to_thread(client.wait_ready, 20):
            await self._send({"type": "error", "message": "语音服务连接超时（未收到 session.updated）"})
            client.close()
            self._trace("ready_timeout")
            return

        # ready 里带上语言与人设：前端要显示「这通电话对方说什么语言」，也便于演示时讲解
        await self._send({"type": "ready", "session_id": self.session_id,
                          "lang": lang, "language": label, "voice": voice,
                          "persona": {"name": p.name, "nationality": p.nationality,
                                      "age": p.age, "gender": p.gender},
                          "input_rate": INPUT_RATE, "output_rate": OUTPUT_RATE})

        self.ready_ok = True
        self.ready_ms = int((time.time() - self.started_at) * 1000)
        self._mark_dialed()

        sender = asyncio.create_task(self._pump(queue))
        try:
            while True:
                raw = await self.ws.receive_text()
                if not await self._handle(raw):
                    break
        except Exception:
            pass
        finally:
            sender.cancel()
            client.close()
            await self._finalize()

    async def _pump(self, queue: asyncio.Queue) -> None:
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    return
                line = transcript_line(ev)
                if line is not None:
                    who, text = line
                    if who == "agent":
                        self._agent(text)
                    else:
                        self._student(text)
                mapped = map_event(ev)
                if mapped is None:
                    continue
                if mapped.get("type") == "audio":
                    b64 = mapped.get("audio") or ""
                    if b64:
                        self.audio_out_frames += 1
                        self.audio_out_bytes += len(b64) * 3 // 4
                await self._send(mapped)
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _handle(self, raw: str) -> bool:
        try:
            msg = json.loads(raw)
        except Exception:
            return True
        t = msg.get("type")
        if t == "stop":
            return False
        if self.client is None:
            return True
        if t == "audio":
            b64 = msg.get("audio") or ""
            if b64:
                self.audio_in_frames += 1
                try:
                    raw = base64.b64decode(b64)
                    self.audio_in_bytes += len(raw)
                    self.client.append_audio(raw)
                except Exception:
                    pass
        elif t == "commit":
            try:
                self.client.commit()
            except Exception:
                pass
        elif t == "text":
            text = (msg.get("text") or "").strip()
            if text:
                self._student(text)
                try:
                    self.client.ask_text(text)
                except Exception:
                    pass
        return True

    # ---- 转写落库 ----

    def _student(self, text: str) -> None:
        if self.lines and self.lines[-1]["who"] == "student" and self.lines[-1]["text"] == text:
            return
        self.lines.append({"who": "student", "text": text})
        if self.call_svc is not None and self.session_id:
            sess = self.call_svc.get(self.session_id)
            if sess is not None:
                self.call_svc.record_line(sess, "student", text)

    def _agent(self, text: str) -> None:
        if self.lines and self.lines[-1]["who"] == "agent" and self.lines[-1]["text"] == text:
            return
        self.lines.append({"who": "agent", "text": text})
        if self.call_svc is not None and self.session_id:
            sess = self.call_svc.get(self.session_id)
            if sess is not None:
                self.call_svc.record_line(sess, "agent", text)

    def _mark_dialed(self) -> None:
        """拨通即算「发起首呼」。
        门槛只管有没有真的发起这一通电话，聊得好不好交给评分 Agent（有证据链可查）。
        record_action 本身幂等，重复调用不会写两条。
        """
        if self.practice is None or not self.order:
            return
        try:
            self.practice.record_action(
                self.order["order_id"], "first_call",
                {"session_id": self.session_id, "mode": "voice", "stage": "dialed"},
            )
        except Exception:
            pass

    def _trace(self, reason: str) -> None:
        """把这一通的关键数字记到 logs/voice_trace.jsonl。

        ready_ok / ready_ms 回答「语音模型到底连上没有」，
        audio_in_* 是浏览器送上来的音频，audio_out_* 是模型返回的音频。
        """
        rec = {
            "ts": time.time(),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "session_id": self.session_id,
            "order_id": (self.order or {}).get("order_id", ""),
            "customer": self.customer_name,
            "reason": reason,
            "ready_ok": self.ready_ok,
            "ready_ms": self.ready_ms,
            "duration_s": round(time.time() - self.started_at, 1),
            "audio_in_frames": self.audio_in_frames,
            "audio_in_bytes": self.audio_in_bytes,
            "audio_out_frames": self.audio_out_frames,
            "audio_out_bytes": self.audio_out_bytes,
            "turns": sum(1 for l in self.lines if l["who"] == "student"),
        }
        try:
            TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with TRACE_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    async def _send(self, payload: dict) -> None:
        try:
            await self.ws.send_json(payload)
        except Exception:
            pass

    async def _finalize(self) -> None:
        if not self.session_id:
            return
        try:
            self.call_svc.end(self.session_id)
        except Exception:
            pass
        turns = sum(1 for l in self.lines if l["who"] == "student")
        # 首呼已在「拨通」（收到 ready）时登记，这里只统计轮数，不再重复登记。
        self._trace("closed")
        await self._send({"type": "closed", "turns": turns,
                          "evidence": len(self.practice.evidence(self.order["order_id"]))
                          if self.practice is not None else 0})


def transcript_line(ev: dict) -> tuple[str, str] | None:
    """把上游事件里的「最终转写」取出来，用于落库。

    中间的分片（delta）不落库，只落 done / completed，避免同一句话被拆成十几条。
    """
    t = ev.get("type")
    if t == "response.audio_transcript.done":
        who = "agent"
    elif t in ("conversation.item.input_audio_transcription.completed",
               "conversation.item.input_audio_transcription.done"):
        who = "student"
    else:
        return None
    text = (ev.get("transcript") or "").strip()
    return (who, text) if text else None


def collect_transcript(ev: dict, buf: dict) -> None:
    """（可选）供离线复用的转写累加器。"""
    if ev.get("type") == "response.audio_transcript.done":
        buf["agent"] = ev.get("transcript", "")