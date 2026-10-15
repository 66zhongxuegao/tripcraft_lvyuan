import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { BEATS } from './beats'
import { createDriver, cursor } from './driver'
import { installFixtures } from './fixtures'

/** 演示账户：在真实前端上播放编排好的操作序列 */

const LS_DEMO = 'tc-demo-account'
const LS_USER = 'tc-user'
const LS_USERS = 'tc-users'
const LS_PREV = 'tc-demo-prev-user'
const DEMO_UID = 'u-show'
const DEMO_NAME = '演示账户'

function readFlag(): boolean {
  try { return localStorage.getItem(LS_DEMO) === '1' } catch { return false }
}

export const useDemoStore = defineStore('demo', () => {
  const active = ref(readFlag())
  const index = ref(0)
  const playing = ref(false)
  const running = ref(false)
  const driver = createDriver()

  const beats = BEATS
  const total = beats.length
  const beat = computed(() => beats[Math.min(Math.max(index.value, 0), total - 1)])

  let fx: ReturnType<typeof installFixtures> | null = null
  let booted = false
  let blankHandler: ((e: MouseEvent) => void) | null = null

  /* 演示期间：真人点击只能推进，不能操作页面（遮罩在 App.vue） */
  function bindBlank() {
    unbindBlank()
    blankHandler = (e: MouseEvent) => {
      if (!e.isTrusted) return
      const el = e.target as HTMLElement | null
      if (el && el.closest('button, a, input, textarea, select, [data-demo-stop]')) return
      if (!running.value) next()
    }
    document.addEventListener('click', blankHandler, true)
  }
  function unbindBlank() {
    if (blankHandler) { document.removeEventListener('click', blankHandler, true); blankHandler = null }
  }

  function ensureFixtures() {
    fx?.dispose()
    fx = installFixtures()
  }

  async function runAt(i: number) {
    const b = beats[Math.min(Math.max(i, 0), total - 1)]
    index.value = Math.min(Math.max(i, 0), total - 1)
    if (!b) return
    running.value = true
    ;(window as any).__demo = { index: index.value + 1, total, id: b.id, title: b.title, running: true }
    console.log('[demo] 第', index.value + 1, '步：', b.title)
    try {
      await b.run(driver)
    } catch (e) {
      console.warn('[demo] 步骤执行失败：', b.id, e)
    }
    running.value = false
    if (playing.value && index.value < total - 1) {
      setTimeout(() => { if (playing.value && !running.value) void runAt(index.value + 1) }, 1400)
    } else if (playing.value && index.value >= total - 1) {
      playing.value = false
    }
  }

  function next() { if (!running.value) void runAt(index.value + 1) }
  function prev() { if (!running.value) void runAt(index.value - 1) }
  function replay() { if (!running.value) void runAt(index.value) }

  /** 进入演示：切到独立演示账户 → 回首页 → 整页重载（让所有页面都读演示账户的数据） */
  function start() {
    try {
      const raw = localStorage.getItem(LS_USERS) || '[]'
      const parsed = JSON.parse(raw)
      const all: any[] = Array.isArray(parsed) ? parsed : []
      // 每次进演示都用一个全新的演示账号：保证画像从零开始，不带上一次的数据
      const users = all.filter((u: any) => !String(u && u.id || '').startsWith(DEMO_UID))
      const uid = DEMO_UID + '-' + Date.now().toString(36).slice(-4)
      users.push({ id: uid, name: DEMO_NAME })
      localStorage.setItem(LS_USERS, JSON.stringify(users))
      localStorage.setItem(LS_PREV, localStorage.getItem(LS_USER) || '')
      localStorage.setItem(LS_USER, uid)
      localStorage.setItem(LS_DEMO, '1')
    } catch (e) {
      console.warn('[demo] 切演示账户失败', e)
    }
    window.location.hash = '#/'
    window.location.reload()
  }

  /** 退出演示：还原原账户并回首页 */
  function stop() {
    running.value = false
    playing.value = false
    cursor.visible = false
    cursor.label = ''
    cursor.typing = false
    unbindBlank()
    fx?.dispose()
    fx = null
    try {
      localStorage.removeItem(LS_DEMO)
      const prev = localStorage.getItem(LS_PREV)
      if (prev) localStorage.setItem(LS_USER, prev)
    } catch { /* 无痕模式忽略 */ }
    active.value = false
    window.location.hash = '#/'
    window.location.reload()
  }

  function togglePlay() {
    playing.value = !playing.value
    if (playing.value && !running.value) void runAt(index.value)
  }

  /** 页面加载完成后调用：只要演示模式开着，就从第 1 步开始跑 */
  function boot() {
    if (booted) return false
    booted = true
    if (!active.value) return false
    index.value = 0
    running.value = false
    ;(window as any).__demo = { index: 1, total, id: beats[0] && beats[0].id, title: beats[0] && beats[0].title, running: false, booted: true }
    cursor.visible = true
    playing.value = false
    bindBlank()
    ensureFixtures()
    setTimeout(() => { void runAt(0) }, 900)
    return true
  }

  return { active, index, total, beat, beats, playing, running, next, prev, replay, start, stop, togglePlay, boot }
})
