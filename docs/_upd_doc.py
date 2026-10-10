# -*- coding: utf-8 -*-
import io
p = r"D:\lvyuan-main\TripCraft\_lvyuan\docs\演示视频-修复记录-20261010.md"
s = io.open(p, encoding="utf-8").read()
marker = "## 四、待办 / 已知问题"
i = s.index(marker)
add = u"""## 四、第二轮修复（2026-10-10 下午）

用户逐句核对后提出 11 处「文不对题 / 没演示出来」。逐条定位结果与处理：

| # | 用户反馈 | 原因 | 处理 |
| --- | --- | --- | --- |
| 1 | 2:27 生成画像时停在测评题页 | 用户看的是 `D:\\lvyuan-main\\tripcraft-demo.mp4`，是 9:10 的旧成片 | 新成片交付时同时覆盖这个路径 |
| 2 | 2:46 学习地图只有第二层 | 分镜 21/22 都取在 `t2-map.webm` 的第一层区间 | 重录 `t2-map`：第一层总览 → 点「文化桥」→ 第二层 6 条国别文化桥 → 点开「中美文化桥 C9.1」卡片。分镜 21 取 0.9–13.4s，22 取 13.4–21.0s |
| 3 | 3:17 六帽只有司南判断页 | 分镜 25 取 12.0–18.55s，弹窗刚出现 | 重录 `t3-agents`，分镜 25 改取 16.0–22.6s（六帽逐个转圈 → 对钩） |
| 4 | 3:32 讲义没有滚动 markdown | 分镜 26 取在对话窗口区间 | 重录 `t4-asset`：先对话工作台，再打开讲义弹窗并向下滚动正文。分镜 26 取 15.5–23.8s |
| 5 | 3:36 讲 13 步却是教学画面 | 同 #1（旧成片） | 分镜 27–30 全部换成新录的 `s27-orders / s28-detail / s29-dispatch / s30-call` |
| 6 | 4:18 双层拦截网没演出来 | 分镜 31 取 12–29.5s，前半段还在填表 | 改取 18.0–31.3s（提交后出现「四分类齐全 + 语义合规」校验卡）；左侧说明换成「确定性校验 + 语义合规校验 → 通过才投递」双卡 |
| 7 | 4:27 资源询价 / 未确认不给死报价没演出来 | 旧录制滚到会话底部，看到的是出团通知书 | 重录 `p2-imres`：顶部逐家询价 → 地接回执 → 票务「先别跟客人报死价，要锁今天先付 80% 预留」。分镜 32 取 4.5–20.5s |
| 8 | 4:38 客户已读反馈没演出来 | 分镜 33 取到提交前就结束 | 改取 20.0–32.0s，收在「客户反馈 / 客户追问」 |
| 9 | 5:20 出团通知书同步 / 司导反向确认 | 分镜 37 取 14–24.27s，没到结果卡 | 改取 16.0–29.6s |
| 10 | 5:35 并行协调资源 | 分镜 38 已含司导群内容 | 起点从 4.0s 改到 5.5s（避开切会话的空白），并复核内容 |
| 11 | 5:44 计算实际利润 | 分镜 39 取 13.5–22.09s，已含「实际成本 → 实际毛利」 | 保留并复核 |

### 本轮同时修掉的一致性与正确性问题

1. **六帽颜色没渲染**：`index.html` 里 `J["25"].html` 被多转义了一层，浏览器把它当普通文本，六帽只能显示成 6 行黑字。已修成正常的 `class="hat-grid"`，现在六顶帽子各有配色圆点。
2. **「8 维 61 技能点」与系统不一致**（加入 C9 文化桥后是 9 维 / 67 技能点）：
   - 副本前端 `App.vue`（侧栏卡片 + 学习地图标题）、`HomeView.vue`、`ProfileQuizView.vue`、`PracticeView.vue` 文案改成 9 维 / 67；
   - 解说词第 **18、21、40** 句的数字同步改掉，用讯飞 TTS 重合成 `audio-45/18.mp3`、`21.mp3`、`40.mp3`，重拼 `narration-full.mp3`（**401.72s**），更新 `audio-45/durations.json` 与 `index.html` 的 `DUR`；
   - 旧录屏里残留的小字通过重录素材消化：`t1-profile / t2-map / t4-asset / t3-agents / t5-rings / t6-profile-update` 重录，第 27–30 步改用新录的 `s27–s30`，练习段 11 支素材整体重跑。
3. **分镜 20「两类掌握度」原本停在讲义弹窗上**：改用新录的 `tch/t5-rings.webm`（学情画像页：教学 68.9 / 实战 53.9 双环 + 雷达 + 趋势），左侧双环数字同步改成 69 / 54。
4. **分镜 35 客户单聊点错会话**：原脚本用「客户T」匹配会话行，命中的是「司导沟通群」。改成按 `.ri-name` 精确匹配后重录 `p8-imcust`（18.8s）。
5. **换镜白屏**：视频分镜切换时新建的 `<video>` 还没解码，开头会有 0.4~1s 纯白。已在播放器里加 `warmVid() / primeVid()`：启动时把每个素材预热到它的起始帧，正式连播时提前 1.7s 预热下一分镜。`_vfy3.mjs` 抽查 16 个分镜的 +0.42s 帧，全部有画面。
6. **分镜 20 视频越界**：`teaching.webm` 只有 100.68s，而 loopEnd 写成 103.4s，尾部会冻结。该素材已整体弃用。

### 复现命令

```powershell
# 0) 依赖服务：副本前端 5181、副本后端 18011、静态服务器 8971
cd "D:\\lvyuan-main\\TripCraft - 副本\\_lvyuan"
python -X utf8 -m uvicorn tripcraft.api.app:create_app --factory --host 127.0.0.1 --port 18011
cd "D:\\lvyuan-main\\TripCraft\\_lvyuan\\video\\web-story"
python -X utf8 serve_range.py 8971

# 1) 重录素材（可选）
cd "D:\\lvyuan-main\\TripCraft\\_lvyuan\\video"
node _recteach8.mjs      # t1-profile / t2-map
node _recteach9.mjs      # t4-asset（讲义滚动）
node _recteach10.mjs     # t5-rings / t3-agents / t6-profile-update
node _recpractice3.mjs   # 练习段 11 支
node _rectepp4.mjs       # s27-s30（订单管理 / 订单详情 / 消息中心 / 通话）
node _recp8.mjs          # p8-imcust（客户单聊）
node _recp2d.mjs         # p2-imres（资源大群询价）

# 2) 录播放器（约 7 分钟 / 411s）
node _rec5.mjs

# 3) 合成
cd "D:\\lvyuan-main\\TripCraft\\_lvyuan\\video\\web-story"
C:\\ffmpeg\\bin\\ffmpeg.exe -y -ss 2.35 -i "full-rec5\\<最新 webm>" -i narration-full.mp3 `
  -c:v libx264 -crf 20 -preset veryfast -pix_fmt yuv420p -c:a aac -b:a 192k `
  -shortest -movflags +faststart tripcraft-demo.mp4

# 4) 逐句抽帧 + 视觉核对（每句开始/中间/结束三点）
cd "D:\\lvyuan-main\\TripCraft\\_lvyuan\\video"
python -X utf8 _verify3.py      # 报告：web-story/qa3/report.md
```

"""
new_todo = u"""## 五、待办 / 已知问题

1. 换镜仍有播放器 `show()` 里的 320ms 交叉过渡，已与配音对齐；如需更紧可降到 200ms。
2. `scripts/record_steps13.py` 在 2026-10-10 下午重跑失败（司导群 / 出团通知书 / 结算单等 20+ 项校验不通过），失败产物已用 `web-story/steps13.webm` 还原。第 27–30 步现已改为 `pw/s27-s30` 单独重录，不再依赖这段整段素材；如后续要修脚本，先确认演示库状态。
3. `docs/` 下 `HANDOFF.md / PROJECT_STATUS.md / DECISIONS.md` 记录的是主程序进度，演示视频只以本文件为准。
"""
s = s[:i] + add + new_todo
io.open(p, "w", encoding="utf-8").write(s)
print("doc updated", len(s))
