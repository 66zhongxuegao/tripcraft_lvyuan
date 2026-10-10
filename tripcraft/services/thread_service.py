"""技能点对话线程服务 —— 学习 / 做题 / 复盘 / 问答 / 个性资源。

对应 PRD 第 27 章。核心是「一次对话前，把 6 类来源装配成上下文」：
  ① Rubric  ② 知识点基座  ③ 本线程历史  ④ 答题情况  ⑤ 画像掌握度  ⑥ 实战证据
所有回复必须引用来源（evidence），不得凭空编造。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..agents.llm import DeepSeekClient
from ..agents.review import SixHatsReview
from ..contracts.enums import mastery_of
from ..contracts.rubric import RUBRICS
from ..contracts.skill_points import SKILL_POINTS_BY_ID
from ..storage.db import Store
from .retrieval import get_retriever

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"

ASSET_TYPES = {"lecture": "讲义", "guide": "实操指南", "report": "学习报告", "wrong_book": "错题本"}


@dataclass
class ThreadContext:
    sp: str
    name: str
    rubric: dict = field(default_factory=dict)
    knowledge: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    quiz: dict = field(default_factory=dict)
    ability: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)

    def sources(self) -> list[str]:
        out = [f"rubric:{self.sp}"]
        for s in (self.knowledge or {}).get("sources", [])[:4]:
            out.append(f"知识:{s}")
        out.append(f"thread:{len(self.history)}条")
        out.append(f"quiz:{self.quiz.get('count', 0)}题")
        out.append(f"mastery:教学{self.ability.get('teach', 0):.0f}/实战{self.ability.get('real_v', 0):.0f}")
        for e in self.evidence[:3]:
            out.append(f"order:{e.get('order_id', '')}")
        return out

    def render(self) -> str:
        lines: list[str] = []
        if self.rubric:
            r = self.rubric
            anchors = "\n".join(f"  {a['level']}: {a['behavior']}" for a in r.get("anchors", []))
            lines.append(f"【该技能点 Rubric】{r.get('target', '')}\n{anchors}\n正例：{r.get('positive', '')}\n反例：{r.get('negative', '')}")
        k = self.knowledge
        if k and k.get("text"):
            lines.append(f"【知识点基座（召回）】\n{k['text']}")
        if self.history:
            h = "\n".join(f"  {m['role']}: {m['content'][:80]}" for m in self.history[-6:])
            lines.append("【本线程历史（最近）】\n" + h)
        q = self.quiz
        if q.get("count"):
            lines.append(f"【答题情况】共 {q['count']} 题，正确 {q['correct']} 题，最近：{q.get('recent') or '无'}")
        lines.append(f"【画像掌握度】教学 {self.ability.get('teach', 0):.0f} / 实战 {self.ability.get('real_v', 0):.0f}")
        if self.evidence:
            ev = "\n".join(f"  {e.get('order_id')}：{e.get('summary', '')}" for e in self.evidence[:3])
            lines.append("【实战证据】\n" + ev)
        return "\n\n".join(lines)


TEACHER_SYSTEM = """你是「司南」，定制师实训系统的带教老师，一对一陪学员学。

【教学铁律】
1. 学员问知识点 → 先讲清楚：先给结论 → 2-3 个要点 → 举一个例子 → 点出常见易错点。
2. 讲解要用自己的话重新组织，禁止照搬资料原文；可以打比方、举例子。
3. 讲完必须问一句「要不要做两道题检验一下？」（学员说先不练就不问）。
4. 不讲与当前技能点无关的内容；严格对照给定的 Rubric 锚点。
5. 涉及事实时只依据提供的资料，不得编造；资料不足就说「这块资料还不全」。
6. 用口语短句，别写列表式提纲，别用「作为AI」这类套话。

【输出格式】
用 Markdown 回复（可用小标题、加粗、列表、引用）。
结尾另起一行用 <div class="refs">参考来源：…</div> 标出本次用到的来源。
"""

ASSET_SYSTEM = """你是定制师培训教研专家，负责按技能点生成学习资料。

【要求】
- 输出 **Markdown**（含标题、小标题、表格、引用、列表）。
- 内容必须围绕该技能点的 Rubric 锚点与知识点基座，不得跑题、不得编造事实。
- 末尾必须有一节「参考来源」，列出用到的 Rubric 锚点 / 知识点。
- 只输出 Markdown 正文，不要额外解释。
"""

JUDGE_SYSTEM = """你是评分专家。依据给定 Rubric 的 M1–M5 锚点，判断学员当前掌握到哪一档。

【规则】
- 就低不就高；证据不足时取较低档。
- 结合给定「答题情况」与「实战证据」。

【输出 JSON】{"level":"M3","score":75,"reason":"一句话理由"}
只输出 JSON。
"""

QUESTION_SYSTEM = """你是实战出题老师，给学员出一道贴近真实工作场景的题。

【规则】
- 必须围绕该技能点，用一个具体的客户/订单/突发场景出题，考「遇到这种情况该怎么做」，不考概念背诵。
- 难度只是你出题时的复杂度标尺（绝对不要把难度分级、M1-M5、Rubric 档位这些内部词说给学员听）：
  L1 基础：场景明确，直接套标准动作
  L2 简单辨析：带一个干扰点
  L3 进阶：带两个干扰点，需比较取舍
  L4 高阶：加时间压力 / 资源紧张 / 情绪升级
  L5 高压综合：多冲突并发，要排优先级并书面闭环
- 选择题 options 必须 4 个，answer 用 A/B/C/D；简答题给参考答案与评分要点。
- 题干里绝对不要出现「M1/M2/M3/M4/M5」「档位」「Rubric」等内部评分词。

【输出 JSON】
{"type":"choice","stem":"","options":["","","",""],"answer":"A","explain":"","difficulty":"L2"}
或 {"type":"short","stem":"","reference":"","rubric_points":["",""],"difficulty":"L3"}
只输出 JSON。
"""


ROUTER_SYSTEM = """你是定制师实训系统的核心调度器，由教师 Agent 指挥协作者。
根据学员这句话，判断本轮需要调用哪些协作者 Agent（教师永远最后执行，不要列在 agents 里）：
- retrieval：知识召回 —— 需要查知识点/规则/定义/步骤时
- profile：画像顾问 —— 学员提到掌握度、薄弱点、复盘、下一步建议、我的学习情况时
只列确实需要的；普通知识点提问通常只要 retrieval。
输出 JSON：{"agents":["retrieval","profile"]}
只输出 JSON。"""

PROFILE_SYSTEM = """你是画像顾问。根据学员当前画像，给出一条针对当前技能点的可操作学习建议。
要求：具体、口语化、不超过 40 字。只输出建议本身，不要解释。"""

AGENT_META = {
    "retrieval": {"id": "retrieval", "name": "知识召回", "icon": "search"},
    "profile": {"id": "profile", "name": "画像顾问", "icon": "user"},
    "teacher": {"id": "teacher", "name": "司南老师", "icon": "book"},
    "asset": {"id": "asset", "name": "教研生成", "icon": "notebook"},
    "judge": {"id": "judge", "name": "掌握度判档", "icon": "target"},
    "question": {"id": "question", "name": "Rubric 出题", "icon": "filetext"},
    "answer": {"id": "answer", "name": "答题判分", "icon": "check"},
}
HAT_ICON = {"white": "eye", "black": "shield", "green": "sparkle", "yellow": "star", "red": "user", "blue": "compass"}


def _difficulty_of(level: str) -> str:
    return {"M1": "L1", "M2": "L2", "M3": "L3", "M4": "L4", "M5": "L5"}.get(level, "L1")


class ThreadService:
    def __init__(self, store: Store, llm: DeepSeekClient | None = None) -> None:
        self._store = store
        self._llm = llm

    def _require_llm(self) -> DeepSeekClient:
        if self._llm is None:
            raise RuntimeError("未配置 LLM（缺少 DEEPSEEK_API_KEY）")
        return self._llm

    # ---------- 上下文装配 ----------

    def _knowledge(self, sp: str, query: str = "") -> dict:
        try:
            return get_retriever().render(sp, query, top_k=8)
        except Exception:
            return {}

    def _rubric(self, sp: str) -> dict:
        r = RUBRICS.get(sp)
        if not r:
            return {}
        return {
            "target": r.target, "trigger": r.trigger, "positive": r.positive,
            "negative": r.negative, "knowledge": r.knowledge,
            "anchors": [{"level": a.level.value, "behavior": a.behavior} for a in r.anchors],
        }

    def _quiz_stats(self, user_id: str, sp: str) -> dict:
        rows = self._store.attempts(user_id, sp)
        correct = sum(1 for r in rows if r["correct"])
        recent = ""
        if rows:
            last = rows[-1]
            recent = ("答对" if last["correct"] else "答错") + f"（{str(last['question'])[:40]}…）"
        return {"count": len(rows), "correct": correct, "recent": recent}

    def _practical_evidence(self, user_id: str, sp: str) -> list[dict]:
        """实战证据：从订单分数里取与该技能点相关的记录（当前用订单状态摘要）。"""
        out = []
        for o in self._store.orders(user_id)[:3]:
            out.append({"order_id": o["order_id"], "summary": f"{o['customer']}·{o['destination']}，当前阶段 {o['stage_index'] + 1}/8"})
        return out

    def build_context(self, user_id: str, sp: str, query: str = "") -> ThreadContext:
        thread = self._store.get_or_create_thread(user_id, sp)
        ab = self._store.abilities(user_id).get(sp, {})
        return ThreadContext(
            sp=sp, name=SKILL_POINTS_BY_ID[sp].name if sp in SKILL_POINTS_BY_ID else sp,
            rubric=self._rubric(sp), knowledge=self._knowledge(sp, query),
            history=self._store.messages(thread["thread_id"]),
            quiz=self._quiz_stats(user_id, sp),
            ability={"teach": float(ab.get("teach") or 0), "real_v": float(ab.get("real_v") or 0)},
            evidence=self._practical_evidence(user_id, sp),
        )

    # ---------- 对话 ----------

    def snapshot(self, user_id: str, sp: str) -> dict:
        ctx = self.build_context(user_id, sp)
        ab = ctx.ability
        assets = self._store.assets(user_id, sp)
        return {
            "skill_point_id": sp, "name": ctx.name,
            "mastery": {"teach": round(ab["teach"], 1), "real": round(ab["real_v"], 1),
                        "level": mastery_of(ab["teach"]).value},
            "messages": [{"role": m["role"], "content": m["content"],
                          "evidence": json.loads(m["evidence"] or "[]"), "created_at": m["created_at"]}
                         for m in ctx.history],
            "assets": [{"asset_id": a["asset_id"], "type": a["type"], "title": a["title"],
                        "content": a["content"], "evidence": json.loads(a["evidence"] or "[]"),
                        "created_at": a["created_at"]} for a in assets],
            "quiz": ctx.quiz,
        }

    def _plan(self, message: str) -> list[str]:
        try:
            data = self._require_llm().chat_json(
                [{"role": "system", "content": ROUTER_SYSTEM},
                 {"role": "user", "content": f"学员这句话：{message[:200]}"}],
                temperature=0.1, max_tokens=80)
            agents = list(data.get("agents") or [])
        except Exception:
            agents = []
        plan = [a for a in agents if a in ("retrieval", "profile")]
        if "retrieval" not in plan:
            plan.insert(0, "retrieval")
        return plan

    def _profile_advice(self, user_id: str, sp: str, ctx: ThreadContext) -> str:
        ab = ctx.ability
        brief = (f"当前技能点 {sp}（{ctx.name}）：教学 {ab.get('teach', 0):.0f}，实战 {ab.get('real_v', 0):.0f}；"
                 f"答题 {ctx.quiz.get('count', 0)} 题、正确 {ctx.quiz.get('correct', 0)} 题。")
        try:
            return self._require_llm().chat(
                [{"role": "system", "content": PROFILE_SYSTEM},
                 {"role": "user", "content": brief}],
                temperature=0.4, max_tokens=120).strip()
        except Exception:
            return ""

    def reply(self, user_id: str, sp: str, message: str) -> dict:
        plan = self._plan(message)
        ctx = self.build_context(user_id, sp, query=message)
        thread = self._store.get_or_create_thread(user_id, sp)
        self._store.add_message(thread["thread_id"], "user", message)

        profile_advice = ""
        if "profile" in plan:
            profile_advice = self._profile_advice(user_id, sp, ctx)

        context_text = ctx.render()
        if profile_advice:
            context_text += f"\n\n【画像顾问建议】{profile_advice}"

        messages = [
            {"role": "system", "content": TEACHER_SYSTEM},
            {"role": "system", "content": "以下是本次回复可用的资料（务必只依据这些）：\n\n" + context_text},
        ]
        for m in ctx.history[-10:]:
            messages.append({"role": "assistant" if m["role"] == "ai" else "user", "content": m["content"]})
        messages.append({"role": "user", "content": message})

        content = self._require_llm().chat(messages, temperature=0.6, max_tokens=1600)
        sources = ctx.sources()
        self._store.add_message(thread["thread_id"], "ai", content, sources)
        self._store.touch_thread(thread["thread_id"])
        pipeline = [dict(AGENT_META[a]) for a in plan] + [dict(AGENT_META["teacher"])]
        return {"content": content, "evidence": sources, "pipeline": pipeline, "profile_advice": profile_advice}

    # ---------- 资产 ----------

    def generate_asset(self, user_id: str, sp: str, kind: str) -> dict:
        if kind not in ASSET_TYPES:
            raise ValueError(f"未知资产类型: {kind}")
        ctx = self.build_context(user_id, sp, query=f"生成{ASSET_TYPES[kind]}")
        thread = self._store.get_or_create_thread(user_id, sp)
        ask = f"请为技能点「{ctx.name}（{sp}）」生成一份「{ASSET_TYPES[kind]}」。"
        if kind == "report":
            ask += f"\n结合：答题情况 {ctx.quiz}；掌握度 教学{ctx.ability['teach']:.0f}/实战{ctx.ability['real_v']:.0f}；实战证据 {ctx.evidence}。"
        content = self._require_llm().chat(
            [{"role": "system", "content": ASSET_SYSTEM},
             {"role": "system", "content": "资料依据：\n\n" + ctx.render()},
             {"role": "user", "content": ask}],
            temperature=0.5, max_tokens=2600)
        reviewer = SixHatsReview(self._require_llm())
        review = reviewer.review(content, ctx.render())
        regenerated = False
        if review["critical_fail"]:
            content = self._require_llm().chat(
                [{"role": "system", "content": ASSET_SYSTEM},
                 {"role": "system", "content": "资料依据：\n\n" + ctx.render()},
                 {"role": "user", "content": ask + "\n（上一版被六帽审查驳回，请按审查意见改正后重新输出完整材料。）"}],
                temperature=0.5, max_tokens=2600)
            regenerated = True
        sources = ctx.sources()
        aid = "asset_" + datetime.now().strftime("%Y%m%d%H%M%S%f")[:18]
        self._store.add_asset(aid, user_id, thread["thread_id"], sp, kind, ASSET_TYPES[kind], content, sources)
        pipeline = [dict(AGENT_META["retrieval"]), dict(AGENT_META["asset"])]
        if kind == "report":
            pipeline.insert(1, dict(AGENT_META["profile"]))
        pipeline += [{"id": h["id"], "name": h["name"], "icon": HAT_ICON.get(h["id"], "circle")} for h in review["hats"]]
        return {"asset_id": aid, "type": kind, "title": ASSET_TYPES[kind], "content": content,
                "evidence": sources, "review": {"verdict": review["verdict"], "regenerated": regenerated,
                "hats": review["hats"]}, "pipeline": pipeline}

    # ---------- 做题 ----------

    def judge_mastery(self, user_id: str, sp: str) -> dict:
        ctx = self.build_context(user_id, sp)
        data = self._require_llm().chat_json(
            [{"role": "system", "content": JUDGE_SYSTEM},
             {"role": "system", "content": "资料：\n\n" + ctx.render()},
             {"role": "user", "content": "请判断学员当前掌握度档位。"}],
            temperature=0.2, max_tokens=300)
        level = str(data.get("level") or "M1")
        try:
            score = float(data.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        return {"level": level, "score": score, "reason": str(data.get("reason", "")),
                "difficulty": _difficulty_of(level),
                "pipeline": [{"id": "judge", "name": "掌握度判档"}]}

    def pick_question(self, user_id: str, sp: str) -> dict:
        j = self.judge_mastery(user_id, sp)
        ctx = self.build_context(user_id, sp)
        q = self._require_llm().chat_json(
            [{"role": "system", "content": QUESTION_SYSTEM},
             {"role": "system", "content": "资料：\n\n" + ctx.render()},
             {"role": "user", "content": f"请出一档难度为 {j['difficulty']} 的题。"}],
            temperature=0.5, max_tokens=900)
        q["difficulty"] = j["difficulty"]
        q["judged_level"] = j["level"]
        q["question_id"] = f"{sp}-{int(datetime.now().timestamp()*1000)}"
        q["pipeline"] = [{"id": "judge", "name": "掌握度判档"}, {"id": "question", "name": "Rubric 出题"}]
        return q

    def submit_answer(self, user_id: str, sp: str, question: dict, answer: str) -> dict:
        correct = False
        explain = question.get("explain") or question.get("reference") or ""
        if question.get("type") == "choice":
            correct = str(answer).strip().upper()[:1] == str(question.get("answer", "")).strip().upper()[:1]
        else:
            res = self._require_llm().chat_json(
                [{"role": "system", "content": "你是实战评判老师。判断学员的简答是否达标，并给出针对性的讲解（错了讲清为什么、该怎么改）。输出 JSON：{\"correct\":true,\"reason\":\"\"}"},
                 {"role": "user", "content": f"题干：{question.get('stem')}\n参考答案：{question.get('reference')}\n学员答案：{answer}"}],
                temperature=0.1, max_tokens=320)
            correct = bool(res.get("correct"))
            explain = str(res.get("reason") or explain)
        score = 92.0 if correct else 40.0
        self._store.add_attempt(user_id, sp, question.get("question_id", ""), question, answer, correct, score)

        ab = self._store.abilities(user_id).get(sp, {})
        old = float(ab.get("teach") or 0)
        # 答对：掌握度升、难度跟着升；答错：给讲解、掌握度降、难度跟着降
        if old <= 0:
            new = 62.0 if correct else 28.0
        else:
            new = round(min(100.0, old + 7.0), 1) if correct else round(max(0.0, old - 9.0), 1)
        self._store.set_ability(user_id, sp, teach=new)
        if not correct:
            self._store.add_memory(user_id, "progress_note", f"{sp} 答错：{str(question.get('stem'))[:40]}", f"thread:{sp}")
        lvl = mastery_of(new)
        old_lvl = mastery_of(old)
        new_diff = _difficulty_of(lvl.value)
        old_diff = _difficulty_of(old_lvl.value)
        if new_diff != old_diff:
            trend = "up" if int(new_diff[1]) > int(old_diff[1]) else "down"
        else:
            trend = "flat"
        return {"correct": correct, "score": score, "explain": explain,
                "teach": new, "level": lvl.value,
                "difficulty": new_diff, "prev_difficulty": old_diff,
                "trend": trend,
                "reteach": (not correct),
                "pipeline": [dict(AGENT_META["answer"]), dict(AGENT_META["profile"])]}