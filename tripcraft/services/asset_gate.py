"""发布门控与材料版本 —— 六帽审查通过才落库，每次发布追加一个版本。

白帽/黑帽是硬门槛：任一「不通过」→ 不发布（version 0，asset / asset_version 都不写）。
发布通过时 asset 表保存最新正文，asset_version 表保存每次通过发布的正文快照；
同一 (user_id, sp, kind) 连续发布得到 version 1、2、3……，版本历史可查。
"""

from __future__ import annotations

HARD_HATS = ("white", "black")


class AssetGate:
    """资料发布前的最后一道门：审查结论 → 是否落库 + 版本号。"""

    def __init__(self, store) -> None:
        self._store = store

    def evaluate(self, review: dict) -> dict:
        """判定六帽审查结论；白/黑任一「不通过」或整体「需修改」都算未通过。"""
        data: dict = review if isinstance(review, dict) else {}
        hats = [h for h in (data.get("hats") or []) if isinstance(h, dict)]
        blocked = [
            h for h in hats
            if str(h.get("id") or "") in HARD_HATS
            and str(h.get("verdict") or "").strip() == "不通过"
        ]
        critical_fail = bool(blocked) or bool(data.get("critical_fail"))
        verdict = str(data.get("verdict") or "").strip()
        passed = not critical_fail and verdict != "需修改"
        return {
            "passed": passed,
            "reason": self._reason(blocked, hats, data, verdict),
            "critical_fail": critical_fail,
        }

    def publish(self, user_id: str, sp: str, kind: str, content: str, review: dict) -> dict:
        """通过审查才发布：写 asset + 追加一条 asset_version，返回资产与版本历史。"""
        gate = self.evaluate(review)
        if not gate["passed"]:
            return {
                "asset_id": "",
                "version": 0,
                "passed": False,
                "versions": [],
                "reason": gate["reason"],
                "critical_fail": gate["critical_fail"],
            }
        # 同一用户 + 技能点 + 资产类型共用一个 asset_id，重复发布即同一资产的新版本。
        asset_id = f"asset_{user_id}_{sp}_{kind}"
        self._store.add_asset(asset_id, user_id, "", sp, kind, kind, content)
        version = self._store.add_asset_version(asset_id, content)
        return {
            "asset_id": asset_id,
            "version": version,
            "passed": True,
            "versions": self._store.asset_versions(asset_id),
            "reason": gate["reason"],
            "critical_fail": False,
        }

    @staticmethod
    def _reason(blocked: list[dict], hats: list[dict], data: dict, verdict: str) -> str:
        """把审查结论压成一句可读理由；通过时顺带蓝帽意见。"""
        if blocked:
            return "；".join(
                f"{h.get('name') or h.get('id')}不通过：{h.get('note') or '未给理由'}"
                for h in blocked
            )
        blue = next((h for h in hats if h.get("id") == "blue"), None)
        blue_note = str((blue or {}).get("note") or "")
        if data.get("critical_fail"):
            return "六帽审查命中硬门槛" + (f"：{blue_note}" if blue_note else "")
        if verdict == "需修改":
            return blue_note or "蓝帽判定需修改"
        return "白帽/黑帽通过" + (f"：{blue_note}" if blue_note else "")
