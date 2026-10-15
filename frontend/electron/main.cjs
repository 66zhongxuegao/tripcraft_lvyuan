// 旅鸢桌面版：Electron 主进程（Vue3 + TS 前端 + Python 后端）
// 打开时自动拉起后端 18010 与前端 5180（已在跑的就复用），退出时只关掉自己拉起的进程。
const { app, BrowserWindow, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const http = require('http')
const fs = require('fs')

const ROOT = path.resolve(__dirname, '..', '..')          // _lvyuan
const FRONT = path.join(ROOT, 'frontend')
const LOG_DIR = path.join(ROOT, 'logs')
const LOG = path.join(LOG_DIR, 'electron.log')
const BACKEND = 'http://127.0.0.1:18010'
const FRONTEND = 'http://127.0.0.1:5180'
const started = []

function log(msg) {
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true })
    fs.appendFileSync(LOG, `[${new Date().toISOString()}] ${msg}\n`)
  } catch (e) {}
}

function alive(url, timeout = 1500) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => { res.resume(); resolve(true) })
    req.on('error', () => resolve(false))
    req.setTimeout(timeout, () => { req.destroy(); resolve(false) })
  })
}

async function waitFor(url, label, seconds = 60) {
  for (let i = 0; i < seconds * 2; i++) {
    if (await alive(url)) return true
    await new Promise((r) => setTimeout(r, 500))
  }
  log(`等待 ${label} 超时：${url}`)
  return false
}

function start(cmd, args, cwd, label) {
  const p = spawn(cmd, args, { cwd, shell: true, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1' } })
  p.stdout.on('data', (d) => log(`[${label}] ${d.toString().trim()}`))
  p.stderr.on('data', (d) => log(`[${label}] ${d.toString().trim()}`))
  started.push({ p, label })
  log(`拉起 ${label}: ${cmd} ${args.join(' ')}`)
  return p
}

async function ensureServices() {
  if (!(await alive(BACKEND + '/practice/steps'))) {
    start('python', ['-X', 'utf8', '-m', 'uvicorn', 'tripcraft.api.app:create_app', '--factory',
                     '--host', '127.0.0.1', '--port', '18010'], ROOT, 'backend')
  } else { log('后端已在运行，复用') }
  if (!(await alive(FRONTEND))) {
    start('npm', ['run', 'dev'], FRONT, 'frontend')
  } else { log('前端已在运行，复用') }
  await waitFor(BACKEND + '/practice/steps', '后端')
  await waitFor(FRONTEND, '前端')
}

async function createWindow() {
  const win = new BrowserWindow({
    width: 1440, height: 940, minWidth: 1180, minHeight: 760,
    backgroundColor: '#f5f6f8',
    title: '旅鸢 · 定制师全流程模拟实战系统',
    icon: path.join(FRONT, 'src', 'assets', 'logo-tripcraft.png'),
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false,
                      preload: path.join(__dirname, 'preload.cjs') },
  })
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' } })
  await win.loadURL(FRONTEND)
  log('窗口已加载 ' + FRONTEND)
}

app.whenReady().then(async () => {
  log('--- 启动 ---')
  await ensureServices()
  await createWindow()
  app.on('activate', () => { if (!BrowserWindow.getAllWindows().length) createWindow() })
})

app.on('window-all-closed', () => {
  for (const { p, label } of started) {
    try { log(`关闭 ${label}`); process.kill(p.pid) } catch (e) {}
  }
  app.quit()
})
