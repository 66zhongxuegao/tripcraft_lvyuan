# TripCraft · 旅鸢

> 入境游定制师全流程模拟实战系统：把接单、首呼、需求确认、方案报价、履约与复盘做成可重复练习的真实业务链路。

## 在线体验

> 本链接为临时演示地址，维护期间可能短暂不可用。

<!-- LIVE-DEMO:START -->
**https://running-successful-gear-taxes.trycloudflare.com**
<!-- LIVE-DEMO:END -->

## 功能概览

- 覆盖定制师从接单到复盘的完整工作流，关键步骤有完成条件与证据链。
- 8 维 61 技能点的原子评分，支持 Rubric 锚点、覆盖校验与学情画像。
- 客户、地接、酒店、车队、票务、司导、导演、评分、画像等多类 AI 角色协同。
- 需求确认单、逐日行程、分项报价、合同保险、出团通知、结算核对等交付物。
- 15 门语言 / 23 个客源市场的入境游训练口径。
- 演示模式使用固定案例与离线响应，适合本地演示和无密钥验收。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python、FastAPI、Uvicorn、SQLite |
| 前端 | Vue 3、TypeScript、Vite、Pinia、ECharts |
| 桌面 | Electron |
| 测试 | pytest |
| 演示隧道 | cloudflared quick tunnel（可选） |

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- Windows / PowerShell（桌面入口）

### 安装后端

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 安装前端

```powershell
cd frontend
npm ci
cd ..
```

### 配置

在项目根目录创建 `local.env`，按需配置：

```dotenv
DEEPSEEK_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
DASHSCOPE_API_KEY=
QWEN_OMNI_MODEL=qwen3.5-omni-flash-realtime
QWEN_OMNI_WS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/realtime
AMAP_API_KEY=
OPEN_METEO_BASE=https://api.open-meteo.com
```

`local.env` 已被 `.gitignore` 排除，请勿提交真实密钥。

### 启动

```powershell
# 一键启动普通模式
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1

# 或分别启动
python -m uvicorn tripcraft.api.app:create_app --factory --reload --host 127.0.0.1 --port 18020
cd frontend; npm run dev
```

演示模式：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\desktop_launch.ps1 -Mode Demo -WebOnly
```

### 临时公网演示与巡检

```powershell
# 安装开机自启的巡检程序（当前用户登录后启动，每 20 分钟检查一次）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_tunnel_watchdog.ps1
```

巡检程序会自动拉起演示服务、检查 README 中的临时链接；链接失效时重建 cloudflared tunnel，并通过 GitHub API 更新 README 的 LIVE-DEMO 区块。日志位于 `logs/tunnel-watchdog.log`。

## 测试

```powershell
python -m pytest
```

## 目录结构

```text
tripcraft/      后端、领域服务、Agent、MCP、语音与存储
frontend/       Vue 前端与 Electron 桌面入口
data/           固定案例、知识与校准数据
tests/          自动化测试
scripts/        启动、验收、数据生成与隧道巡检脚本
tools/          本地排查与验收工具
```

## 仓库说明

本仓库只保留运行所需源码、前端资源、测试和固定案例数据；演示录屏、截图、内部交接文档、字体包、构建产物与本机密钥不纳入仓库。
