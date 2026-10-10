# -*- coding: utf-8 -*-
import io
p = r"D:\lvyuan-main\TripCraft\_lvyuan\docs\HANDOFF.md"
s = io.open(p, encoding="utf-8").read()
old = "> 最后更新：2026-10-10\n> 状态与变更记录见 `PROJECT_STATUS.md`；决策见 `DECISIONS.md`。\n> 密钥只存 `local.env`（已 gitignore）；文档只写变量名。"
new = ("> 最后更新：2026-10-10\n"
       "> 状态与变更记录见 `PROJECT_STATUS.md`；决策见 `DECISIONS.md`。\n"
       "> 密钥只存 `local.env`（已 gitignore）；文档只写变量名。\n"
       "> **演示视频（6:41 成片）单独一份交接：`docs/演示视频-修复记录-20261010.md`** —— 成片路径、逐句分镜表、素材录制脚本、复现命令与已知问题都在那里，改视频只看这份。")
assert old in s
s = s.replace(old, new, 1)
io.open(p, "w", encoding="utf-8").write(s)
print("handoff updated")
