# -*- coding: utf-8 -*-
"""Qwen-Omni-Realtime 服务端引擎（由 omni_realtime_poc/voice_chat.py 移植，去掉音频设备）。

职责：
  1. 作为服务端客户端连接 DashScope/百炼 Qwen realtime WebSocket（密钥留在后端）；
  2. 用「沙盒会话 + 游客人设 + 训练语言」组装 instructions，并指定音色；
  3. 接收浏览器上行 PCM(16k) 输入（input_audio_buffer.append），转发模型事件
     （24k PCM 音频增量 / 转写文本 / VAD）给回调方（FastAPI WebSocket 中继）。

不依赖 sounddevice / numpy；仅需 websocket-client。
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from tripcraft.voice.language_profiles import LANG_NAMES_EN

DEFAULT_MODEL = os.getenv("QWEN_OMNI_MODEL", "qwen3.5-omni-flash-realtime")
DEFAULT_WS = "wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime"
ENV_API_KEY = "DASHSCOPE_API_KEY"
ENV_WS_URL = "QWEN_OMNI_WS_URL"
ENV_MODEL = "QWEN_OMNI_MODEL"

# 输入/输出采样率（DashScope realtime 默认：输入 16k / 输出 24k，PCM16 单声道）
INPUT_RATE = 16000
OUTPUT_RATE = 24000


def _local_env() -> dict[str, str]:
    """读项目根 local.env（后端进程通常只加载这个文件，不注入 os.environ）。"""
    env: dict[str, str] = {}
    p = Path(__file__).resolve().parents[2] / "local.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def resolve_env() -> tuple[str, str, str]:
    """返回 (api_key, ws_url, model)；先看环境变量，再回退 local.env。"""
    fallback = _local_env()
    key = (os.getenv(ENV_API_KEY) or fallback.get(ENV_API_KEY, "")).strip()
    url = (os.getenv(ENV_WS_URL) or fallback.get(ENV_WS_URL, DEFAULT_WS)).strip()
    model = (os.getenv(ENV_MODEL) or fallback.get(ENV_MODEL, DEFAULT_MODEL)).strip()
    if not key:
        raise RuntimeError(
            "Qwen realtime 未配置：请设置 " + ENV_API_KEY + "（或写入项目根 local.env）"
        )
    if "{WorkspaceId}" in url:
        raise RuntimeError(
            "QWEN_OMNI_WS_URL 仍含 {WorkspaceId} 占位符，请替换为实际工作区地址"
        )
    return key, url, model


def build_scene_voice_instructions(
    scene: Mapping[str, Any],
    customer: Mapping[str, Any],
    lang: str = "en",
) -> str:
    """由「场景 dict + 游客人设」组装语音游客 instructions（TripCraft 版）。

    与旧库的区别：场景不再依赖 sandbox 模板对象，改为普通 dict，
    便于对接本系统的「导演/场景」结构。
    """
    lang_en = LANG_NAMES_EN.get(lang, lang)
    lang_code = lang

    def g(key: str) -> str:
        return str(customer.get(key, "") or "").strip()

    def s(key: str) -> str:
        return str(scene.get(key, "") or "").strip()

    name = g("name") or "游客"
    country = g("nationality") or "中国"
    age = g("age") or "30"
    gender = g("gender") or ""
    gender_word = gender if gender in ("男", "女") else ""
    base_desc = "一位来自" + country + "的" + age + "岁" + gender_word + "游客"

    extra: list[str] = []
    for key, label in (("occupation", "职业"), ("health", "健康状况"),
                       ("consumption", "消费习惯"), ("speech_style", "说话风格")):
        if g(key):
            extra.append(label + "：" + g(key))
    extra_lines = ("\n".join("- " + x for x in extra) + "\n") if extra else ""

    lines = [
        "你是" + name + "，" + base_desc + "，正在参加一次中国定制游。",
        "- 性格：" + (g("personality") or "随和友善"),
        "- 偏好：" + (g("preferences") or "喜欢历史文化"),
        "- 说话习惯与特点：" + (g("quirks") or "说话礼貌，偶有好奇提问"),
        "- 隐藏诉求：" + (g("hidden") or "希望旅程顺利，得到周到照顾"),
    ]
    if extra_lines:
        lines.append(extra_lines.rstrip("\n"))
    lines.append("")
    lines.append("【当前场景】（中文设定，只需理解，不要念出来，也不要翻译成其他语言）")
    lines.append(s("opening"))
    if s("location"):
        lines.append("你身处：" + s("location"))
    if s("stage_title"):
        lines.append("当前阶段：" + s("stage_title"))
    if s("objective"):
        lines.append("本阶段导游应该做到（你的期待）：" + s("objective"))
    lines.append("")
    lines.append("【你的处境】（这是你自己正在做的事——是你自己，不是别人）")
    lines.append(s("situation") or "（你只是普通游客，正在正常游玩）")
    lines.append("")
    lines.append("【角色规则】")
    lines.append("1. 你始终以游客身份说话，绝不出戏，绝不充当教练或评估者。")
    lines.append("2. 场景里只有你（游客）和定制师/导游两个人互动。")
    lines.append("3. 你只使用" + lang_en + "（" + lang_code + "）口语自然对话，每次 1-3 句，"
                 "带个人口音、称呼或口头禅，符合你的国籍、性别与年龄。")
    lines.append("4. 认真回应对方说的每一句话：做得好表露满意，做得差表露困惑、不满或质疑；"
                 "也可以主动提问、提要求或制造小麻烦来检验对方能力。")
    lines.append("5. 你说的话就是台词，直接开口即可，不要输出任何 JSON、标记或旁白。")
    return "\n".join(lines)
def speak_text(
    text: str,
    lang: str = "en",
    voice: str | None = None,
    timeout: float = 60.0,
) -> dict:
    """一次性朗读给定文本（多语种发音）。

    复用 Qwen realtime：让模型把传入文本用目标语言原样朗读，返回
    {"audio": <24k PCM bytes>, "transcript": 朗读文本, "lang", "voice"}。
    不依赖麦克风/浏览器，适合「译文发音」「短语朗读」等按需场景。
    """
    import base64 as _b64
    import threading as _th

    from tripcraft.voice.language_profiles import LANG_NAMES_EN, pick_voice

    api_key, url, model = resolve_env()
    voice = voice or pick_voice(lang, "")
    lang_en = LANG_NAMES_EN.get(lang, lang)
    instructions = (
        "You are a text-to-speech reader for a guide training app. "
        "The user will give you a piece of text. Read that text aloud in "
        + lang_en
        + " ("
        + lang
        + ") exactly as-is: do NOT translate, do NOT explain, do NOT add any "
        "greeting or closing words. Only speak the given text."
    )
    out: dict = {"audio": bytearray(), "transcript": "", "error": None}
    done = _th.Event()

    def on_event(ev: dict) -> None:
        t = ev.get("type", "")
        try:
            if t == "response.audio.delta":
                out["audio"] += _b64.b64decode(ev.get("delta", "") or "")
            elif t == "response.audio_transcript.done":
                tr = ev.get("transcript") or ""
                if tr:
                    out["transcript"] = tr
            elif t in ("error", "ws_error"):
                out["error"] = str(ev.get("error") or ev)[:300]
        except Exception:
            pass
        if t == "response.done":
            done.set()

    client = QwenRealtimeClient(api_key, url, model, instructions,
                                voice=voice, on_event=on_event)
    client.connect()
    try:
        if not client.wait_ready(20):
            raise RuntimeError("Qwen realtime 会话未就绪，请检查 DASHSCOPE_API_KEY / QWEN_OMNI_WS_URL")
        client.ask_text(text)
        done.wait(timeout)
        if not done.is_set():
            raise RuntimeError("朗读超时（>%ss）" % int(timeout))
        if out["error"]:
            raise RuntimeError("朗读失败: " + out["error"])
        audio = bytes(out["audio"])
        if not audio:
            raise RuntimeError("未收到语音数据")
        return {
            "audio": audio,
            "transcript": out["transcript"] or text,
            "lang": lang,
            "voice": voice,
        }
    finally:
        client.close()


class QwenRealtimeClient:
    """单向职责的 realtime 客户端：连上后按需 append/commit/ask，事件全部回调。

    on_event(ev: dict) 在每个服务端事件到达时被调用（子线程）。
    连接就绪前请等待 ready（threading.Event）。
    """

    def __init__(
        self,
        api_key: str,
        ws_url: str,
        model: str,
        instructions: str,
        voice: str | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_close: Callable[[int | None, str | None], None] | None = None,
    ):
        try:
            import websocket
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "缺少 websocket-client 依赖：请在项目环境执行 uv pip install websocket-client"
            ) from exc
        self._ws_lib = websocket
        url = ws_url + ("&" if "?" in ws_url else "?") + "model=" + model
        self.url = url
        self.api_key = api_key
        self.instructions = instructions
        self.voice = voice
        self.on_event_cb = on_event
        self.on_close_cb = on_close
        self.ready = threading.Event()
        self._ws = None
        self._stop = threading.Event()

    # ---- 连接 ----
    def connect(self) -> None:
        import threading as _t

        app = self._ws_lib.WebSocketApp(
            self.url,
            header=["Authorization: Bearer " + self.api_key],
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = _t.Thread(target=app.run_forever, daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float = 15.0) -> bool:
        return self.ready.wait(timeout)

    def close(self) -> None:
        self._stop.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    # ---- 事件 ----
    def _emit(self, ev: dict[str, Any]) -> None:
        if self.on_event_cb is not None:
            try:
                self.on_event_cb(ev)
            except Exception:
                pass

    def _on_open(self, ws) -> None:
        self._ws = ws
        sess: dict[str, Any] = {
            "modalities": ["text", "audio"],
            "instructions": self.instructions,
            "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
        }
        if self.voice:
            sess["voice"] = self.voice
        # 默认 server_vad 自动提交并作答；关闭「新语音打断当前回复」避免回声自我打断
        sess["turn_detection"] = {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 900,
            "create_response": True,
            "interrupt_response": False,
        }
        self._send({"type": "session.update", "session": sess})

    def _on_message(self, _ws, raw: str) -> None:
        try:
            ev = json.loads(raw)
        except Exception:
            return
        t = ev.get("type", "")
        if t == "session.updated":
            self.ready.set()
        self._emit(ev)

    def _on_error(self, _ws, err) -> None:
        self._emit({"type": "ws_error", "error": str(err)})

    def _on_close(self, _ws, code, msg) -> None:
        self.ready.set()  # 唤醒等待
        if self.on_close_cb is not None:
            try:
                self.on_close_cb(code, msg)
            except Exception:
                pass
        self._emit({"type": "closed", "code": code, "message": msg})

    # ---- 上行 ----
    def _send(self, obj: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("连接尚未建立")
        self._ws.send(json.dumps(obj, ensure_ascii=False))

    def append_audio(self, pcm_bytes: bytes) -> None:
        """上行：浏览器麦克风 PCM(16k/16bit/mono) -> 服务端输入缓冲。"""
        if not pcm_bytes:
            return
        if pcm_bytes.startswith(b"RIFF"):
            pcm_bytes = pcm_bytes[44:]
        self._send({
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm_bytes).decode("ascii"),
        })

    def commit(self) -> None:
        self._send({"type": "input_audio_buffer.commit"})

    def ask_text(self, text: str) -> None:
        """上行：纯文本引导一轮回复（用于破冰/自检/无麦调试）。"""
        self._send({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]},
        })
        self._send({"type": "response.create"})

    def cancel_response(self) -> None:
        self._send({"type": "response.cancel"})


def _main() -> None:  # 本地冒烟：不依赖麦克风与外部密钥即可验证指令构造
    import sys

    scene = {
        "opening": "客人刚接起电话，正在说明想去哪、几个人。",
        "location": "电话沟通",
        "stage_title": "首呼与需求挖掘",
        "objective": "问清人数、日期、预算口径与住宿意向",
        "situation": "你时间不多，说话直接，预算只肯说“性价比高”。",
    }
    customer = {"name": "Kenji", "nationality": "日本", "age": "42", "gender": "男"}
    ins = build_scene_voice_instructions(scene, customer, "en")
    print("== instructions head ==")
    print(ins[:400])
    try:
        api_key, url, model = resolve_env()
    except RuntimeError as exc:
        print("(跳过真实连接:", exc, ")")
        return
    print("== connecting ==", flush=True)

    def on_event(ev: dict) -> None:
        t = ev.get("type", "")
        if t in ("response.audio_transcript.done", "error", "ws_error", "session.updated"):
            print("EVENT", t, json.dumps(ev, ensure_ascii=False)[:300], flush=True)

    client = QwenRealtimeClient(api_key, url, model, ins, voice="Jennifer", on_event=on_event)
    client.connect()
    if not client.wait_ready(20):
        print("timeout waiting session.updated")
        client.close()
        return
    client.ask_text("Good morning! I am your trip designer. May I ask a few questions?")
    time.sleep(25)
    client.close()
    print("done")

if __name__ == "__main__":
    _main()