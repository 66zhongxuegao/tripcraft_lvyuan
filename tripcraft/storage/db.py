"""SQLite 存储层 —— 线程 / 资产 / 答题 / 订单 / 会话 / 画像。

不引入重框架，用标准库 sqlite3。服务层只通过本模块读写。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "tripcraft.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
  user_id TEXT PRIMARY KEY, level TEXT DEFAULT 'L1',
  deals INTEGER DEFAULT 0, lost INTEGER DEFAULT 0, complaints INTEGER DEFAULT 0, updated_at TEXT);
CREATE TABLE IF NOT EXISTS ability (
  user_id TEXT, skill_point_id TEXT, teach REAL DEFAULT 0, real_v REAL DEFAULT 0, updated_at TEXT,
  PRIMARY KEY (user_id, skill_point_id));
CREATE TABLE IF NOT EXISTS thread (
  thread_id TEXT PRIMARY KEY, user_id TEXT, skill_point_id TEXT, created_at TEXT, last_active_at TEXT);
CREATE TABLE IF NOT EXISTS thread_message (
  msg_id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT, role TEXT, content TEXT, evidence TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS asset (
  asset_id TEXT PRIMARY KEY, user_id TEXT, thread_id TEXT, skill_point_id TEXT,
  type TEXT, title TEXT, content TEXT, evidence TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS quiz_attempt (
  attempt_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, skill_point_id TEXT, question_id TEXT,
  question TEXT, answer TEXT, correct INTEGER, score REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS memory (
  memory_id TEXT PRIMARY KEY, user_id TEXT, type TEXT, content TEXT,
  importance REAL DEFAULT 0.6, source_thread TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS biz_order (
  order_id TEXT PRIMARY KEY, user_id TEXT, customer TEXT, destination TEXT,
  status TEXT, stage_index INTEGER DEFAULT 0, payload TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS im_session (
  session_id TEXT PRIMARY KEY, user_id TEXT, name TEXT, kind TEXT, members TEXT, created_at TEXT,
  order_id TEXT DEFAULT '', code TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS contact (
  contact_id TEXT PRIMARY KEY, order_id TEXT, user_id TEXT, name TEXT, kind TEXT,
  phone TEXT DEFAULT '', source TEXT DEFAULT '', note TEXT DEFAULT '',
  added_at TEXT DEFAULT '', session_id TEXT DEFAULT '', remark TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS supplier_quote (
  order_id TEXT, kind TEXT, payload TEXT, updated_at TEXT,
  PRIMARY KEY (order_id, kind));
CREATE TABLE IF NOT EXISTS im_message (
  msg_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, sender TEXT, role TEXT, content TEXT,
  created_at TEXT, kind TEXT DEFAULT 'text', payload TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS order_contact (
  contact_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, kind TEXT, at TEXT,
  status TEXT, has_record INTEGER DEFAULT 0, detail TEXT);
CREATE TABLE IF NOT EXISTS notice (
  notice_id TEXT PRIMARY KEY, user_id TEXT, group_key TEXT, title TEXT, body TEXT,
  at TEXT, starred INTEGER DEFAULT 0, order_id TEXT);
CREATE TABLE IF NOT EXISTS finance_entry (
  entry_id TEXT PRIMARY KEY, order_id TEXT, code TEXT, label TEXT, category TEXT,
  amount REAL DEFAULT 0, bearer TEXT DEFAULT '\u5f85\u5b9a', ours REAL DEFAULT 0,
  supplier_kind TEXT DEFAULT '', source TEXT DEFAULT '', ref TEXT DEFAULT '',
  note TEXT DEFAULT '', status TEXT DEFAULT '\u5f85\u5904\u7406', at TEXT);
CREATE TABLE IF NOT EXISTS doc_template (
  template_id TEXT PRIMARY KEY, user_id TEXT, name TEXT, kind TEXT DEFAULT 'plan',
  sections TEXT DEFAULT '[]', updated_at TEXT);
CREATE TABLE IF NOT EXISTS plan_version (
  plan_id TEXT PRIMARY KEY, order_id TEXT, user_id TEXT, version INTEGER DEFAULT 1,
  title TEXT DEFAULT '', days TEXT DEFAULT '', quote TEXT DEFAULT '', note TEXT DEFAULT '',
  status TEXT DEFAULT '草稿', channels TEXT DEFAULT '', created_at TEXT, sent_at TEXT,
  read_at TEXT, read_due_at TEXT, feedback TEXT DEFAULT '', confirm_at TEXT,
  values_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS order_settlement (
  order_id TEXT PRIMARY KEY, revenue REAL DEFAULT 0, cost REAL DEFAULT 0,
  loss REAL DEFAULT 0, profit REAL DEFAULT 0, margin REAL DEFAULT 0,
  grade TEXT DEFAULT '', detail TEXT DEFAULT '', updated_at TEXT);
CREATE TABLE IF NOT EXISTS supplier_state (
  user_id TEXT, kind TEXT, order_id TEXT DEFAULT '', payload TEXT, updated_at TEXT,
  PRIMARY KEY (user_id, kind, order_id));
CREATE TABLE IF NOT EXISTS order_evidence (
  evidence_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, kind TEXT, step TEXT,
  ref TEXT, text TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS order_score (
  order_id TEXT, skill_point_id TEXT, score REAL, level TEXT,
  hit_negative INTEGER DEFAULT 0, evidence TEXT, comment TEXT, source TEXT, created_at TEXT,
  confidence REAL DEFAULT 0, status TEXT DEFAULT '\u5df2\u5165\u5e93', review_reason TEXT DEFAULT '',
  PRIMARY KEY (order_id, skill_point_id));
CREATE TABLE IF NOT EXISTS call_session (
  session_id TEXT PRIMARY KEY, order_id TEXT, user_id TEXT, customer TEXT,
  destination TEXT, mode TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS call_line (
  msg_id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, who TEXT, text TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS order_target (
  order_id TEXT, skill_point_id TEXT, checkpoint TEXT, step TEXT,
  trigger_state TEXT DEFAULT 'pending', covered INTEGER DEFAULT 0,
  reason TEXT DEFAULT '', updated_at TEXT,
  PRIMARY KEY (order_id, skill_point_id));
CREATE TABLE IF NOT EXISTS director_event (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, type TEXT, payload TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS deliverable_doc (
  order_id TEXT, deliverable_id TEXT, version INTEGER DEFAULT 1,
  values_json TEXT, rendered TEXT, audience TEXT, guard_json TEXT,
  file_ids TEXT, at TEXT, PRIMARY KEY (order_id, deliverable_id));
CREATE TABLE IF NOT EXISTS deliverable_file (
  file_id TEXT PRIMARY KEY, order_id TEXT, deliverable_id TEXT,
  filename TEXT, mime TEXT, size INTEGER, data BLOB, at TEXT);
CREATE TABLE IF NOT EXISTS order_action (
  action_id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, action TEXT,
  payload TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS calibration_run (
  run_id TEXT PRIMARY KEY, samples INTEGER, predictions INTEGER, agreement REAL,
  evidence_accuracy REAL, stability REAL, threshold_conf REAL, threshold_delta REAL,
  passed INTEGER, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS incident (
  incident_id TEXT PRIMARY KEY, order_id TEXT, code TEXT, step TEXT, title TEXT,
  channel TEXT, session_id TEXT, speaker TEXT, body TEXT, skill_points TEXT,
  rule TEXT, at TEXT);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path | None = None) -> None:
        # 允许用 TRIPCRAFT_DB 指定库文件：测试用临时库，不碰演示库
        self.path = str(path or os.environ.get("TRIPCRAFT_DB") or DEFAULT_DB)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._migrate_supplier_state()
        self._conn.commit()

    # 轻量迁移：老库缺列时补齐（不引入迁移框架）
    _MIGRATIONS: dict[str, dict[str, str]] = {
        "im_session": {"order_id": "TEXT DEFAULT ''", "code": "TEXT DEFAULT ''"},
        "im_message": {"kind": "TEXT DEFAULT 'text'", "payload": "TEXT DEFAULT ''"},
        "contact": {"remark": "TEXT DEFAULT ''", "session_id": "TEXT DEFAULT ''"},
        "order_score": {
            "confidence": "REAL DEFAULT 0",
            "status": "TEXT DEFAULT '\u5df2\u5165\u5e93'",
            "review_reason": "TEXT DEFAULT ''",
        },
    }

    def _migrate(self) -> None:
        for table, cols in self._MIGRATIONS.items():
            have = {r["name"] for r in self._all(f"PRAGMA table_info({table})")}
            if not have:
                continue
            for name, ddl in cols.items():
                if name not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def _migrate_supplier_state(self) -> None:
        """supplier_state 升级为「全局默认 + 按订单覆盖」：主键要加 order_id，只能重建表。"""
        have = {r["name"] for r in self._all("PRAGMA table_info(supplier_state)")}
        if not have or "order_id" in have:
            return
        with self._lock:
            self._conn.execute("ALTER TABLE supplier_state RENAME TO supplier_state_legacy")
            self._conn.execute(
                "CREATE TABLE supplier_state ("
                "user_id TEXT, kind TEXT, order_id TEXT DEFAULT '', payload TEXT, updated_at TEXT, "
                "PRIMARY KEY (user_id, kind, order_id))")
            self._conn.execute(
                "INSERT INTO supplier_state(user_id, kind, order_id, payload, updated_at) "
                "SELECT user_id, kind, '', payload, updated_at FROM supplier_state_legacy")
            self._conn.execute("DROP TABLE supplier_state_legacy")
            self._conn.commit()

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self._all(sql, args)
        return rows[0] if rows else None

    def close(self) -> None:
        self._conn.close()

    # 画像
    def ensure_profile(self, user_id: str) -> dict:
        self._exec("INSERT OR IGNORE INTO profile(user_id, updated_at) VALUES(?,?)", (user_id, now()))
        return self._one("SELECT * FROM profile WHERE user_id=?", (user_id,))  # type: ignore

    def get_profile(self, user_id: str) -> dict | None:
        return self._one("SELECT * FROM profile WHERE user_id=?", (user_id,))

    def set_ability(self, user_id: str, sp: str, teach: float | None = None, real_v: float | None = None) -> None:
        self.ensure_profile(user_id)
        row = self._one("SELECT * FROM ability WHERE user_id=? AND skill_point_id=?", (user_id, sp))
        t = row["teach"] if (row and teach is None) else (teach if teach is not None else 0)
        r = row["real_v"] if (row and real_v is None) else (real_v if real_v is not None else 0)
        if row:
            self._exec("UPDATE ability SET teach=?, real_v=?, updated_at=? WHERE user_id=? AND skill_point_id=?",
                       (t, r, now(), user_id, sp))
        else:
            self._exec("INSERT INTO ability(user_id, skill_point_id, teach, real_v, updated_at) VALUES(?,?,?,?,?)",
                       (user_id, sp, t, r, now()))

    def abilities(self, user_id: str) -> dict[str, dict]:
        return {r["skill_point_id"]: r for r in self._all("SELECT * FROM ability WHERE user_id=?", (user_id,))}

    def has_profile_data(self, user_id: str) -> bool:
        """是否已有画像数据 —— 决定「初始画像」还能不能做。

        有非零掌握度 / 做过题 / 有实战评分，任一条成立即视为已建档。
        新用户（刚建号、没有能力行）才可以做初始画像。
        """
        row = self._one("SELECT COUNT(*) AS n FROM ability WHERE user_id=? AND (teach > 0 OR real_v > 0)",
                        (user_id,))
        if row and int(row["n"] or 0) > 0:
            return True
        row = self._one("SELECT COUNT(*) AS n FROM quiz_attempt WHERE user_id=?", (user_id,))
        if row and int(row["n"] or 0) > 0:
            return True
        row = self._one("""SELECT COUNT(*) AS n FROM order_score os
            JOIN biz_order o ON o.order_id = os.order_id WHERE o.user_id=?""", (user_id,))
        return bool(row and int(row["n"] or 0) > 0)

    def latest_memory(self, user_id: str, type_: str) -> dict | None:
        return self._one("""SELECT * FROM memory WHERE user_id=? AND type=?
            ORDER BY created_at DESC, rowid DESC LIMIT 1""", (user_id, type_))

    # 线程
    def get_or_create_thread(self, user_id: str, sp: str) -> dict:
        tid = "thread:" + sp
        self._exec("INSERT OR IGNORE INTO thread(thread_id, user_id, skill_point_id, created_at, last_active_at) VALUES(?,?,?,?,?)",
                   (tid, user_id, sp, now(), now()))
        return self._one("SELECT * FROM thread WHERE thread_id=?", (tid,))  # type: ignore

    def touch_thread(self, tid: str) -> None:
        self._exec("UPDATE thread SET last_active_at=? WHERE thread_id=?", (now(), tid))

    def add_message(self, tid: str, role: str, content: str, evidence: list | None = None) -> int:
        cur = self._exec("INSERT INTO thread_message(thread_id, role, content, evidence, created_at) VALUES(?,?,?,?,?)",
                         (tid, role, content, json.dumps(evidence or [], ensure_ascii=False), now()))
        return int(cur.lastrowid)

    def messages(self, tid: str, limit: int = 60) -> list[dict]:
        rows = self._all("SELECT * FROM thread_message WHERE thread_id=? ORDER BY msg_id DESC LIMIT ?", (tid, limit))
        return list(reversed(rows))

    # 资产
    def add_asset(self, asset_id: str, user_id: str, tid: str, sp: str, type_: str,
                  title: str, content: str, evidence: list | None = None) -> None:
        self._exec("INSERT OR REPLACE INTO asset(asset_id, user_id, thread_id, skill_point_id, type, title, content, evidence, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (asset_id, user_id, tid, sp, type_, title, content, json.dumps(evidence or [], ensure_ascii=False), now()))

    def assets(self, user_id: str, sp: str | None = None) -> list[dict]:
        if sp:
            return self._all("SELECT * FROM asset WHERE user_id=? AND skill_point_id=? ORDER BY created_at DESC", (user_id, sp))
        return self._all("SELECT * FROM asset WHERE user_id=? ORDER BY created_at DESC", (user_id,))

    def asset(self, asset_id: str) -> dict | None:
        return self._one("SELECT * FROM asset WHERE asset_id=?", (asset_id,))

    # 答题
    def add_attempt(self, user_id: str, sp: str, qid: str, question: dict, answer: str, correct: bool, score: float) -> int:
        cur = self._exec("INSERT INTO quiz_attempt(user_id, skill_point_id, question_id, question, answer, correct, score, created_at) VALUES(?,?,?,?,?,?,?,?)",
                         (user_id, sp, qid, json.dumps(question, ensure_ascii=False), answer, 1 if correct else 0, score, now()))
        return int(cur.lastrowid)

    def attempts(self, user_id: str, sp: str) -> list[dict]:
        return self._all("SELECT * FROM quiz_attempt WHERE user_id=? AND skill_point_id=? ORDER BY attempt_id", (user_id, sp))

    def all_attempts(self, user_id: str) -> list[dict]:
        return self._all("SELECT * FROM quiz_attempt WHERE user_id=? ORDER BY created_at", (user_id,))

    def order_scores_all(self, user_id: str) -> list[dict]:
        return self._all("""SELECT os.* FROM order_score os JOIN biz_order o ON o.order_id=os.order_id
            WHERE o.user_id=? ORDER BY os.created_at""", (user_id,))

    # 记忆
    def add_memory(self, user_id: str, type_: str, content: str, source_thread: str = "", importance: float = 0.6) -> None:
        self._exec("INSERT INTO memory(memory_id, user_id, type, content, importance, source_thread, created_at) VALUES(?,?,?,?,?,?,?)",
                   (f"mem_{int(datetime.now().timestamp()*1000)}", user_id, type_, content, importance, source_thread, now()))

    def memories(self, user_id: str, limit: int = 20) -> list[dict]:
        return self._all("SELECT * FROM memory WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit))

    # 订单
    def upsert_order(self, order_id: str, user_id: str, customer: str, destination: str,
                     status: str, stage_index: int, payload: dict | None = None) -> None:
        self._exec("INSERT OR REPLACE INTO biz_order(order_id, user_id, customer, destination, status, stage_index, payload, created_at) VALUES(?,?,?,?,?,?,?,?)",
                   (order_id, user_id, customer, destination, status, stage_index, json.dumps(payload or {}, ensure_ascii=False), now()))

    def orders(self, user_id: str | None = None) -> list[dict]:
        if user_id:
            return self._all("SELECT * FROM biz_order WHERE user_id=? ORDER BY created_at DESC", (user_id,))
        return self._all("SELECT * FROM biz_order ORDER BY created_at DESC")

    def order(self, order_id: str) -> dict | None:
        return self._one("SELECT * FROM biz_order WHERE order_id=?", (order_id,))

    def set_stage(self, order_id: str, stage_index: int) -> None:
        self._exec("UPDATE biz_order SET stage_index=? WHERE order_id=?", (stage_index, order_id))

    # IM
    def upsert_session(self, session_id: str, user_id: str, name: str, kind: str, members: list,
                       order_id: str = "", code: str = "") -> None:
        self._exec("INSERT OR REPLACE INTO im_session(session_id, user_id, name, kind, members,"
                   " created_at, order_id, code) VALUES(?,?,?,?,?,?,?,?)",
                   (session_id, user_id, name, kind, json.dumps(members, ensure_ascii=False),
                    now(), order_id, code))

    def sessions(self, user_id: str, order_id: str | None = None) -> list[dict]:
        if order_id is not None:
            return self._all("SELECT * FROM im_session WHERE user_id=? AND order_id=? ORDER BY code",
                             (user_id, order_id))
        return self._all("SELECT * FROM im_session WHERE user_id=? ORDER BY created_at", (user_id,))

    def session(self, session_id: str) -> dict | None:
        return self._one("SELECT * FROM im_session WHERE session_id=?", (session_id,))

    # 资源方事实数据（硬编码基准 + 情景约束推导，落库保证前后一致）

    def save_quote(self, order_id: str, kind: str, payload: dict) -> None:
        self._exec("INSERT OR REPLACE INTO supplier_quote(order_id, kind, payload, updated_at)"
                   " VALUES(?,?,?,?)",
                   (order_id, kind, json.dumps(payload, ensure_ascii=False), now()))

    def quote(self, order_id: str, kind: str) -> dict | None:
        row = self._one("SELECT * FROM supplier_quote WHERE order_id=? AND kind=?", (order_id, kind))
        if not row:
            return None
        try:
            return json.loads(row["payload"] or "{}")
        except Exception:
            return None

    def quotations(self, order_id: str) -> dict[str, dict]:
        out = {}
        for r in self._all("SELECT * FROM supplier_quote WHERE order_id=?", (order_id,)):
            try:
                out[r["kind"]] = json.loads(r["payload"] or "{}")
            except Exception:
                pass
        return out

    def add_im_message(self, session_id: str, sender: str, role: str, content: str,
                       kind: str = "text", payload: dict | None = None) -> None:
        """写一条消息。kind: text / file / card / system（系统消息用于加人、改名、建群）。"""
        self._exec("INSERT INTO im_message(session_id, sender, role, content, created_at, kind, payload)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (session_id, sender, role, content, now(), kind,
                    json.dumps(payload or {}, ensure_ascii=False)))

    def im_messages(self, session_id: str) -> list[dict]:
        return self._all("SELECT * FROM im_message WHERE session_id=? ORDER BY msg_id", (session_id,))

    def rename_session(self, session_id: str, name: str) -> None:
        self._exec("UPDATE im_session SET name=? WHERE session_id=?", (name, session_id))

    def set_session_members(self, session_id: str, members: list) -> None:
        self._exec("UPDATE im_session SET members=? WHERE session_id=?",
                   (json.dumps(members, ensure_ascii=False), session_id))

    # 文档模板（学员自己写的小节标题，存下来下次直接用）

    def save_doc_template(self, template_id: str, user_id: str, name: str, sections: list,
                          kind: str = "plan") -> None:
        self._exec("INSERT OR REPLACE INTO doc_template(template_id, user_id, name, kind,"
                   " sections, updated_at) VALUES(?,?,?,?,?,?)",
                   (template_id, user_id, name, kind,
                    json.dumps(sections, ensure_ascii=False), now()))

    def doc_templates(self, user_id: str, kind: str = "plan") -> list[dict]:
        return self._all("SELECT * FROM doc_template WHERE user_id=? AND kind=? ORDER BY updated_at DESC",
                         (user_id, kind))

    def doc_template(self, template_id: str) -> dict | None:
        return self._one("SELECT * FROM doc_template WHERE template_id=?", (template_id,))

    # 方案版本（创建方案 → 发送方案 → 客户已读）

    def save_plan(self, plan_id: str, order_id: str, user_id: str, version: int, title: str,
                  days: list, quote: list, note: str = "", status: str = "草稿",
                  channels: list | None = None, created_at: str = "", sent_at: str = "",
                  read_at: str = "", read_due_at: str = "", feedback: str = "",
                  confirm_at: str = "", values: dict | None = None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO plan_version(plan_id, order_id, user_id, version, title, days,"
            " quote, note, status, channels, created_at, sent_at, read_at, read_due_at, feedback,"
            " confirm_at, values_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (plan_id, order_id, user_id, version, title,
             json.dumps(days or [], ensure_ascii=False), json.dumps(quote or [], ensure_ascii=False),
             note, status, json.dumps(channels or [], ensure_ascii=False), created_at, sent_at,
             read_at, read_due_at, feedback, confirm_at,
             json.dumps(values or {}, ensure_ascii=False)))

    def plan(self, plan_id: str) -> dict | None:
        return self._one("SELECT * FROM plan_version WHERE plan_id=?", (plan_id,))

    def plans(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM plan_version WHERE order_id=? ORDER BY version", (order_id,))

    def update_plan(self, plan_id: str, **kv) -> None:
        cols = ", ".join(f"{k}=?" for k in kv)
        self._exec(f"UPDATE plan_version SET {cols} WHERE plan_id=?", (*kv.values(), plan_id))

    # 联系人簿（每单一套：客户 / 地接 / 酒店 / 车队 / 导游 / 司机；票务走平台不用加）

    def save_contact(self, contact_id: str, order_id: str, user_id: str, name: str, kind: str,
                     phone: str = "", source: str = "", note: str = "",
                     added_at: str = "", session_id: str = "", remark: str = "") -> None:
        row = self._one("SELECT * FROM contact WHERE contact_id=?", (contact_id,))
        if row and not remark:
            remark = row.get("remark") or ""
        self._exec("INSERT OR REPLACE INTO contact(contact_id, order_id, user_id, name, kind, phone,"
                   " source, note, added_at, session_id, remark) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (contact_id, order_id, user_id, name, kind, phone, source, note,
                    added_at, session_id, remark))

    def contacts_of(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM contact WHERE order_id=? ORDER BY kind, contact_id",
                         (order_id,))

    def contacts_for_user(self, user_id: str) -> list[dict]:
        """学员级通讯录：跨订单只有一份，谁加过就是加过。"""
        return self._all("SELECT * FROM contact WHERE user_id=? ORDER BY added_at, contact_id",
                         (user_id,))

    def update_contact(self, contact_id: str, **kv) -> None:
        if not kv:
            return
        cols = ", ".join(f"{k}=?" for k in kv)
        self._exec(f"UPDATE contact SET {cols} WHERE contact_id=?", (*kv.values(), contact_id))

    def contact(self, contact_id: str) -> dict | None:
        return self._one("SELECT * FROM contact WHERE contact_id=?", (contact_id,))

    # 订单联系记录

    def add_contact(self, order_id: str, kind: str, at: str, status: str,
                    has_record: bool = False, detail: str = "") -> None:
        self._exec("INSERT INTO order_contact(order_id, kind, at, status, has_record, detail) VALUES(?,?,?,?,?,?)",
                   (order_id, kind, at, status, 1 if has_record else 0, detail))

    def contacts(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_contact WHERE order_id=? ORDER BY contact_id", (order_id,))

    def has_contacts(self, order_id: str) -> bool:
        return bool(self._all("SELECT 1 FROM order_contact WHERE order_id=? LIMIT 1", (order_id,)))

    # 平台通知（消息中心）

    def upsert_notice(self, notice_id: str, user_id: str, group_key: str, title: str,
                      body: str, at: str, starred: bool = False, order_id: str = "") -> None:
        self._exec("INSERT OR REPLACE INTO notice(notice_id, user_id, group_key, title, body, at, starred, order_id)"
                   " VALUES(?,?,?,?,?,?,?,?)",
                   (notice_id, user_id, group_key, title, body, at, 1 if starred else 0, order_id))

    def notices(self, user_id: str) -> list[dict]:
        return self._all("SELECT * FROM notice WHERE user_id=? ORDER BY at DESC", (user_id,))

    # 成本 / 损失 / 结算台账

    def add_finance_entry(self, entry_id: str, order_id: str, code: str, label: str,
                          category: str, amount: float, supplier_kind: str = "",
                          source: str = "", ref: str = "", note: str = "",
                          bearer: str = "待定", ours: float = 0,
                          status: str = "待处理") -> None:
        self._exec("INSERT OR REPLACE INTO finance_entry(entry_id, order_id, code, label, category,"
                   " amount, bearer, ours, supplier_kind, source, ref, note, status, at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (entry_id, order_id, code, label, category, float(amount or 0), bearer,
                    float(ours or 0), supplier_kind, source, ref, note, status, now()))

    def finance_entries(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM finance_entry WHERE order_id=? ORDER BY at, entry_id",
                         (order_id,))

    def finance_entry(self, entry_id: str) -> dict | None:
        return self._one("SELECT * FROM finance_entry WHERE entry_id=?", (entry_id,))

    def update_finance_entry(self, entry_id: str, **kv) -> None:
        if not kv:
            return
        cols = ", ".join(f"{k}=?" for k in kv)
        self._exec(f"UPDATE finance_entry SET {cols} WHERE entry_id=?",
                   tuple(kv.values()) + (entry_id,))

    def save_settlement(self, order_id: str, payload: dict) -> None:
        self._exec("INSERT OR REPLACE INTO order_settlement(order_id, revenue, cost, loss, profit,"
                   " margin, grade, detail, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (order_id, float(payload.get("revenue") or 0), float(payload.get("cost") or 0),
                    float(payload.get("loss") or 0), float(payload.get("profit") or 0),
                    float(payload.get("margin") or 0), payload.get("grade", ""),
                    json.dumps(payload.get("detail") or {}, ensure_ascii=False), now()))

    def settlement(self, order_id: str) -> dict | None:
        row = self._one("SELECT * FROM order_settlement WHERE order_id=?", (order_id,))
        if not row:
            return None
        try:
            row["detail"] = json.loads(row.get("detail") or "{}")
        except Exception:
            row["detail"] = {}
        return row

    # 资源方情景状态（导演控制）

    def set_supplier_state(self, user_id: str, kind: str, payload: dict,
                           order_id: str = "") -> None:
        """写情景约束。`order_id=""` 是导演的全局默认；传订单号则只覆盖这一单。"""
        self._exec("INSERT OR REPLACE INTO supplier_state(user_id, kind, order_id, payload, updated_at)"
                   " VALUES(?,?,?,?,?)",
                   (user_id, kind, order_id or "", json.dumps(payload, ensure_ascii=False), now()))

    def supplier_state_for(self, user_id: str, kind: str, order_id: str = "") -> dict:
        """取该单该资源方的有效约束：全局默认打底，订单级覆盖优先。"""
        out: dict = {}
        keys = ["", order_id] if order_id else [""]
        for oid in keys:
            row = self._one("SELECT payload FROM supplier_state WHERE user_id=? AND kind=? AND order_id=?",
                            (user_id, kind, oid))
            if row:
                try:
                    out.update(json.loads(row["payload"] or "{}"))
                except Exception:
                    pass
        return out

    # 实战证据

    def add_evidence(self, order_id: str, kind: str, step: str, ref: str, text: str) -> int:
        cur = self._exec("INSERT INTO order_evidence(order_id, kind, step, ref, text, created_at) VALUES(?,?,?,?,?,?)",
                         (order_id, kind, step, ref, text, now()))
        return int(cur.lastrowid)

    def evidence(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_evidence WHERE order_id=? ORDER BY evidence_id", (order_id,))

    def has_evidence(self, order_id: str, kind: str, ref: str) -> bool:
        return bool(self._all("SELECT 1 FROM order_evidence WHERE order_id=? AND kind=? AND ref=? LIMIT 1",
                              (order_id, kind, ref)))

    # 实战评分

    def upsert_order_score(self, order_id: str, sp: str, score: float, level: str,
                           hit_negative: bool, evidence: list, comment: str, source: str,
                           confidence: float = 0.0, status: str = "\u5df2\u5165\u5e93",
                           review_reason: str = "") -> None:
        self._exec("INSERT OR REPLACE INTO order_score(order_id, skill_point_id, score, level, hit_negative,"
                   " evidence, comment, source, created_at, confidence, status, review_reason)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (order_id, sp, score, level, 1 if hit_negative else 0,
                    json.dumps(evidence, ensure_ascii=False), comment, source, now(),
                    float(confidence or 0), status, review_reason))

    def order_scores(self, order_id: str) -> dict[str, dict]:
        return {r["skill_point_id"]: r for r in self._all("SELECT * FROM order_score WHERE order_id=?", (order_id,))}

    def pending_reviews(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_score WHERE order_id=? AND status=? ORDER BY skill_point_id",
                         (order_id, "待复核"))

    def set_score_status(self, order_id: str, sp: str, status: str) -> None:
        self._exec("UPDATE order_score SET status=? WHERE order_id=? AND skill_point_id=?", (status, order_id, sp))

    # 考核目标 / 覆盖

    def upsert_target(self, order_id: str, sp: str, checkpoint: str, step: str,
                      trigger_state: str = "pending", covered: bool = False, reason: str = "") -> None:
        self._exec("INSERT OR REPLACE INTO order_target(order_id, skill_point_id, checkpoint, step,"
                   " trigger_state, covered, reason, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                   (order_id, sp, checkpoint, step, trigger_state, 1 if covered else 0, reason, now()))

    def targets(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_target WHERE order_id=? ORDER BY skill_point_id", (order_id,))

    def target(self, order_id: str, sp: str) -> dict | None:
        return self._one("SELECT * FROM order_target WHERE order_id=? AND skill_point_id=?", (order_id, sp))

    # 导演总线

    def add_event(self, order_id: str, type_: str, payload: dict | None = None) -> int:
        cur = self._exec("INSERT INTO director_event(order_id, type, payload, at) VALUES(?,?,?,?)",
                         (order_id, type_, json.dumps(payload or {}, ensure_ascii=False), now()))
        return int(cur.lastrowid)

    def events(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM director_event WHERE order_id=? ORDER BY event_id", (order_id,))

    def add_incident(self, incident_id: str, order_id: str, code: str, step: str, title: str,
                     channel: str, session_id: str, speaker: str, body: str,
                     skill_points: list, rule: str) -> None:
        self._exec("INSERT OR REPLACE INTO incident(incident_id, order_id, code, step, title, channel,"
                   " session_id, speaker, body, skill_points, rule, at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (incident_id, order_id, code, step, title, channel, session_id, speaker, body,
                    json.dumps(skill_points, ensure_ascii=False), rule, now()))

    def incidents(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM incident WHERE order_id=? ORDER BY at", (order_id,))

    def has_incident(self, order_id: str, code: str) -> bool:
        return bool(self._all("SELECT 1 FROM incident WHERE order_id=? AND code=? LIMIT 1", (order_id, code)))

    # 交付物文档

    def save_deliverable(self, order_id: str, deliverable_id: str, values: dict, rendered: str,
                         audience: list, guard: dict, file_ids: list) -> int:
        row = self._one("SELECT version FROM deliverable_doc WHERE order_id=? AND deliverable_id=?",
                        (order_id, deliverable_id))
        version = int((row or {}).get("version") or 0) + 1
        self._exec("INSERT OR REPLACE INTO deliverable_doc(order_id, deliverable_id, version, values_json,"
                   " rendered, audience, guard_json, file_ids, at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (order_id, deliverable_id, version, json.dumps(values, ensure_ascii=False), rendered,
                    json.dumps(audience, ensure_ascii=False), json.dumps(guard, ensure_ascii=False),
                    json.dumps(file_ids, ensure_ascii=False), now()))
        return version

    def deliverable(self, order_id: str, deliverable_id: str) -> dict | None:
        return self._one("SELECT * FROM deliverable_doc WHERE order_id=? AND deliverable_id=?",
                         (order_id, deliverable_id))

    def deliverables(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM deliverable_doc WHERE order_id=? ORDER BY at", (order_id,))

    def save_file(self, file_id: str, order_id: str, deliverable_id: str, filename: str,
                  mime: str, size: int, data: bytes) -> None:
        self._exec("INSERT OR REPLACE INTO deliverable_file(file_id, order_id, deliverable_id, filename,"
                   " mime, size, data, at) VALUES(?,?,?,?,?,?,?,?)",
                   (file_id, order_id, deliverable_id, filename, mime, size, data, now()))

    def file(self, file_id: str) -> dict | None:
        return self._one("SELECT * FROM deliverable_file WHERE file_id=?", (file_id,))

    @staticmethod
    def file_meta(row: dict) -> dict:
        return {k: row[k] for k in ("file_id", "filename", "mime", "size", "deliverable_id") if k in row}

    # 学员动作账本（流程通关驱动）

    def add_action(self, order_id: str, action: str, payload: dict | None = None) -> None:
        self._exec("INSERT INTO order_action(order_id, action, payload, at) VALUES(?,?,?,?)",
                   (order_id, action, json.dumps(payload or {}, ensure_ascii=False), now()))

    def has_action(self, order_id: str, action: str) -> bool:
        return bool(self._all("SELECT 1 FROM order_action WHERE order_id=? AND action=? LIMIT 1",
                              (order_id, action)))

    def action_at(self, order_id: str, action: str) -> str | None:
        row = self._one("SELECT at FROM order_action WHERE order_id=? AND action=? ORDER BY action_id LIMIT 1",
                        (order_id, action))
        return row["at"] if row else None

    def actions(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM order_action WHERE order_id=? ORDER BY action_id", (order_id,))

    def action_keys(self, order_id: str) -> set[str]:
        return {r["action"] for r in self.actions(order_id)}

    # 校准基线

    def add_calibration_run(self, run_id: str, samples: int, predictions: int, agreement: float,
                            evidence_accuracy: float, stability: float, threshold_conf: float,
                            threshold_delta: float, passed: bool, detail: dict) -> None:
        self._exec("INSERT OR REPLACE INTO calibration_run(run_id, samples, predictions, agreement,"
                   " evidence_accuracy, stability, threshold_conf, threshold_delta, passed, detail, created_at)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, samples, predictions, agreement, evidence_accuracy, stability,
                    threshold_conf, threshold_delta, 1 if passed else 0,
                    json.dumps(detail, ensure_ascii=False), now()))

    def latest_calibration(self) -> dict | None:
        return self._one("SELECT * FROM calibration_run ORDER BY created_at DESC, run_id DESC LIMIT 1")

    def calibration_runs(self, limit: int = 10) -> list[dict]:
        return self._all("SELECT * FROM calibration_run ORDER BY created_at DESC LIMIT ?", (limit,))

    def incidents_by_session(self, session_id: str) -> list[dict]:
        return self._all("SELECT * FROM incident WHERE session_id=?", (session_id,))

    # 通话持久化

    def save_call_session(self, session_id: str, order_id: str, user_id: str, customer: str,
                          destination: str, mode: str = "text") -> None:
        self._exec("INSERT OR REPLACE INTO call_session(session_id, order_id, user_id, customer, destination, mode, created_at)"
                   " VALUES(?,?,?,?,?,?,?)",
                   (session_id, order_id, user_id, customer, destination, mode, now()))

    def add_call_line(self, session_id: str, who: str, text: str) -> None:
        self._exec("INSERT INTO call_line(session_id, who, text, created_at) VALUES(?,?,?,?)",
                   (session_id, who, text, now()))

    def call_lines(self, session_id: str) -> list[dict]:
        return self._all("SELECT * FROM call_line WHERE session_id=? ORDER BY msg_id", (session_id,))

    def call_sessions_for_order(self, order_id: str) -> list[dict]:
        return self._all("SELECT * FROM call_session WHERE order_id=? ORDER BY created_at", (order_id,))

    def supplier_states(self, user_id: str, order_id: str = "") -> dict[str, dict]:
        """默认返回全局默认档（导演台用）；传订单号则返回该单的有效值。"""
        out: dict[str, dict] = {}
        for r in self._all("SELECT * FROM supplier_state WHERE user_id=?", (user_id,)):
            if order_id:
                out[r["kind"]] = self.supplier_state_for(user_id, r["kind"], order_id)
                continue
            if r.get("order_id"):
                continue
            try:
                out[r["kind"]] = json.loads(r["payload"] or "{}")
            except Exception:
                out[r["kind"]] = {}
        return out