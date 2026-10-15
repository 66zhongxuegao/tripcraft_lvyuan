# 旅鸢 TripCraft 一键启动（后端 18010 + 前端 5180）
# 双击 一键启动.bat 即可；也可执行 powershell -ExecutionPolicy Bypass -File scripts\start.ps1
param(
    [switch]$Keep,
    [switch]$NoBrowser,
    [switch]$NoReload
)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$BACKEND_PORT = 18010
$FRONTEND_PORT = 5180
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Line($t) { Write-Host $t }
function Blank() { Write-Host "" }
function Get-Listener($port) {
    return Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
}
function Wait-Http($url, $seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
        } catch { }
        Start-Sleep -Seconds 1
        Write-Host "." -NoNewline
    }
    return $false
}

Blank
Line "============================================================"
Line "   旅鸢 TripCraft · 定制师全流程模拟实战系统"
Line "   项目目录  $root"
Line "============================================================"
Blank

Line "【1/4】检查运行环境"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Line "  [x] 找不到 python，请先安装 Python 3.11+ 并加入 PATH"; Read-Host "按回车退出"; exit 1 }
Line ("  [ok] Python  " + ((& python --version 2>&1) -join " "))

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Line "  [x] 找不到 node，请先安装 Node.js 20+ 并加入 PATH"; Read-Host "按回车退出"; exit 1 }
Line ("  [ok] Node    " + ((& node --version 2>&1) -join " "))

if (Test-Path (Join-Path $root "local.env")) {
    Line "  [ok] local.env 已配置"
} else {
    Line "  [!] 缺少 local.env（大模型/语音/地图密钥），服务能起来但对话与评分会失败"
}

$depsOk = $true
& python -c "import fastapi, uvicorn, pydantic" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { $depsOk = $false }
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) { $depsOk = $false }

if (-not $depsOk) {
    Blank
    Line "  [x] 依赖没有装齐，需要先执行："
    Line "        后端：python -m pip install -e . --index-url https://pypi.tuna.tsinghua.edu.cn/simple"
    Line "        前端：cd frontend; npm install --registry=https://registry.npmmirror.com"
    Blank
    $ans = Read-Host "  现在自动安装吗？(y/N)"
    if ($ans -eq "y" -or $ans -eq "Y") {
        Line "  · 安装后端依赖..."
        & python -m pip install -e . --index-url https://pypi.tuna.tsinghua.edu.cn/simple
        Line "  · 安装前端依赖..."
        Push-Location (Join-Path $root "frontend")
        & npm install --registry=https://registry.npmmirror.com
        Pop-Location
    } else {
        Line "  已取消。装好依赖后再双击一次即可。"
        Read-Host "按回车退出"
        exit 1
    }
}
Line "  [ok] 依赖检查通过"

Blank
if ($Keep) {
    Line "【2/4】保留已在运行的服务（-Keep）"
} else {
    Line "【2/4】清理上一次启动的服务（改完代码直接双击就行）"
    $killed = 0
    # 先收子进程：uvicorn --reload 的 server 跑在 fork 出的子进程里，
    # 它的命令行不含 tripcraft.api.app，光按命令行匹配会杀掉父级却留下占着端口的子级
    $matched = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*tripcraft.api.app*" }
    foreach ($par in $matched) {
        $kids = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ParentProcessId -eq $par.ProcessId }
        foreach ($k in $kids) { Stop-Process -Id $k.ProcessId -Force -ErrorAction SilentlyContinue; $killed++ }
        Stop-Process -Id $par.ProcessId -Force -ErrorAction SilentlyContinue
        $killed++
    }
    $oldNode = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "node*" -and $_.CommandLine -like "*vite*" }
    foreach ($p in $oldNode) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; $killed++ }

    # uvicorn --reload 会 fork 出子进程（真正的 server 在子进程里），
    # 它的命令行不含 tripcraft.api.app，所以还要按端口占用者再收一遍
    Start-Sleep -Milliseconds 600
    foreach ($port in $BACKEND_PORT, $FRONTEND_PORT) {
        $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($c) {
            $owner = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
            if ($owner -and ($owner.ProcessName -eq "python" -or $owner.ProcessName -eq "node")) {
                Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
                $killed++
            }
        }
    }
    if ($killed -gt 0) { Start-Sleep -Milliseconds 900; Line "  · 已停止 $killed 个旧进程" }
    else { Line "  · 没有正在运行的服务" }
}

Blank
Line "【3/4】启动服务"

if (Get-Listener $BACKEND_PORT) {
    Line "  · 后端已在运行（端口 $BACKEND_PORT），跳过启动"
} else {
    $uvicorn = "-m uvicorn tripcraft.api.app:create_app --factory --host 127.0.0.1 --port $BACKEND_PORT"
    if (-not $NoReload) { $uvicorn = $uvicorn + " --reload" }
    $backendCmd = "cd /d `"$root`" && python -X utf8 $uvicorn > `"$logDir\backend.log`" 2>&1"
    Start-Process -FilePath "cmd" -ArgumentList "/c", $backendCmd -WindowStyle Hidden
    Line "  · 后端启动中（端口 $BACKEND_PORT，日志 logs\backend.log）"
}

if (Get-Listener $FRONTEND_PORT) {
    Line "  · 前端已在运行（端口 $FRONTEND_PORT），跳过启动"
} else {
    $frontendCmd = "cd /d `"$root\frontend`" && npm run dev > `"$logDir\frontend.log`" 2>&1"
    Start-Process -FilePath "cmd" -ArgumentList "/c", $frontendCmd -WindowStyle Hidden
    Line "  · 前端启动中（端口 $FRONTEND_PORT，日志 logs\frontend.log）"
}

Blank
Line "【4/4】等待服务就绪"

Write-Host "  后端 " -NoNewline
$backOk = Wait-Http "http://127.0.0.1:$BACKEND_PORT/" 40
Write-Host ""
if ($backOk) {
    Line "  [ok] 后端就绪  http://127.0.0.1:$BACKEND_PORT/"
} else {
    Line "  [x] 后端 40 秒内没有就绪，最后 12 行日志："
    if (Test-Path "$logDir\backend.log") { Get-Content "$logDir\backend.log" -Tail 12 | ForEach-Object { Line ("      " + $_) } }
}

Write-Host "  前端 " -NoNewline
$frontOk = Wait-Http "http://127.0.0.1:$FRONTEND_PORT/" 60
Write-Host ""
if ($frontOk) {
    Line "  [ok] 前端就绪  http://127.0.0.1:$FRONTEND_PORT/"
} else {
    Line "  [x] 前端 60 秒内没有就绪，最后 12 行日志："
    if (Test-Path "$logDir\frontend.log") { Get-Content "$logDir\frontend.log" -Tail 12 | ForEach-Object { Line ("      " + $_) } }
}

$url = "http://127.0.0.1:$FRONTEND_PORT/"
Blank
if ($frontOk) {
    Line "============================================================"
    Line "   可以直接用了：$url"
    Line "   接口文档：http://127.0.0.1:$BACKEND_PORT/docs"
    Line "   日志：logs\backend.log  logs\frontend.log"
    Line "   停止：双击 停止服务.bat"
    Line "   改代码不用重启：后端自动重载，前端自动刷新"
    Line "============================================================"
    if (-not $NoBrowser) { Start-Process $url }
} else {
    Line "  服务没有完全起来，请把上面的日志发给开发同学。"
}

Blank
Line "这个窗口可以关掉，服务在后台继续跑。"
Read-Host "按回车退出"
