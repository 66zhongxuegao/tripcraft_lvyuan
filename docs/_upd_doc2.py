# -*- coding: utf-8 -*-
import io
p = r"D:\lvyuan-main\TripCraft\_lvyuan\docs\演示视频-修复记录-20261010.md"
s = io.open(p, encoding="utf-8").read()
anchor = "## 五、待办 / 已知问题"
i = s.index(anchor)
add = u"""## 五、成片位置与规格（2026-10-10 15:00 终版）

| 路径 | 说明 |
| --- | --- |
| `D:\\lvyuan-main\\tripcraft-demo.mp4` | **用户直接看的路径**，每次重录后同步覆盖 |
| `D:\\lvyuan-main\\TripCraft\\_lvyuan\\tripcraft-demo.mp4` | 同一份的副本 |
| `D:\\lvyuan-main\\TripCraft\\_lvyuan\\video\\web-story\\tripcraft-demo.mp4` | 渲染产物本体 |

规格：1920×1080 / 25fps / **6 分 41 秒（401.76s）** h264 + AAC，23.3 MB。
音频时间轴 = `ΣDUR + 45×0.5s`，与播放器换镜时刻逐段对齐（每段偏差 < 0.06s）。

"""
s = s[:i] + add + s[i:]
s = s.replace("## 五、待办 / 已知问题", "## 六、待办 / 已知问题", 1)
io.open(p, "w", encoding="utf-8").write(s)
print("ok")
