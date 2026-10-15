# 旅鸢 TripCraft 停止服务（后端 / 前端）
$root = Split-Path -Parent $PSScriptRoot
function Line($t) { Write-Host $t }

Line ""
Line "正在停止旅鸢服务 ..."

$killed = 0

$py = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*tripcraft.api.app*" }
foreach ($p in $py) {
    # 先收它的子进程（uvicorn --reload 的 server 在子进程里，占着端口）
    $kids = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ParentProcessId -eq $p.ProcessId }
    foreach ($k in $kids) {
        Stop-Process -Id $k.ProcessId -Force -ErrorAction SilentlyContinue
        Line ("  · 已停止后端子进程 PID " + $k.ProcessId)
        $killed++
    }
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Line ("  · 已停止后端 PID " + $p.ProcessId)
    $killed++
}

$nd = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "node*" -and $_.CommandLine -like "*vite*" }
foreach ($p in $nd) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Line ("  · 已停止前端 PID " + $p.ProcessId)
    $killed++
}

# 兜底：端口还占着就按端口再收一次
Start-Sleep -Milliseconds 800
foreach ($port in 18010, 5180) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($proc -and ($proc.ProcessName -eq "python" -or $proc.ProcessName -eq "node")) {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
            Line ("  · 端口 $port 仍被占用，已停止 " + $proc.ProcessName + " PID " + $c.OwningProcess)
            $killed++
        } else {
            Line ("  ! 端口 $port 被其它程序占用（" + $proc.ProcessName + "），没有动它")
        }
    }
}

Line ""
if ($killed -gt 0) { Line ("已停止 $killed 个进程。") } else { Line "没有找到正在运行的旅鸢服务。" }
Read-Host "按回车退出"
