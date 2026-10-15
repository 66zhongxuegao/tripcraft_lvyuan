/* 演示驱动：在真实前端上模拟人工操作（移动鼠标 / 点击 / 逐字输入）
 * 不使用任何模拟界面，全部作用在产品的真实 DOM 与真实接口上。 */

import { reactive } from 'vue'

export const cursor = reactive({
  x: typeof window !== 'undefined' ? window.innerWidth / 2 : 600,
  y: typeof window !== 'undefined' ? window.innerHeight * 0.4 : 400,
  visible: false,
  clicking: false,
  label: '',
  typing: false,
})

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

function ease(t: number) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2 }

export function isVisible(el: HTMLElement) {
  const r = el.getBoundingClientRect()
  if (r.width < 2 || r.height < 2) return false
  const s = getComputedStyle(el)
  return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' && s.pointerEvents !== 'none'
}

const CLICKABLE = 'a, button, [role="button"], .node, .row-item, .tab, .act, .qbtn, .tc-btn, .grp-title, .child, .msg-card, .dw-doc, .mini, .icon-btn'

export function findClickable(text: string | string[]): HTMLElement | null {
  const list = Array.isArray(text) ? text : [text]
  const nodes = Array.from(document.querySelectorAll<HTMLElement>(CLICKABLE))
  for (const raw of list) {
    const t = raw.replace(/\s+/g, '')
    const hit = nodes.find((el) => isVisible(el) && (el.innerText || '').replace(/\s+/g, '').includes(t))
    if (hit) return hit
  }
  return null
}

async function moveToPoint(x: number, y: number, ms = 460) {
  const x0 = cursor.x
  const y0 = cursor.y
  const t0 = performance.now()
  await new Promise<void>((resolve) => {
    const tick = () => {
      const k = Math.min(1, (performance.now() - t0) / ms)
      const e = ease(k)
      cursor.x = x0 + (x - x0) * e
      cursor.y = y0 + (y - y0) * e
      if (k < 1) requestAnimationFrame(tick)
      else resolve()
    }
    requestAnimationFrame(tick)
  })
}

export interface Driver {
  sleep(ms: number): Promise<void>
  moveTo(target: string | HTMLElement, nth?: number): Promise<boolean>
  click(target: string | HTMLElement, nth?: number): Promise<boolean>
  clickText(text: string | string[], opt?: { optional?: boolean }): Promise<boolean>
  type(selector: string, text: string, cps?: number): Promise<boolean>
  goto(route: string, ms?: number): Promise<void>
  waitFor(selector: string, timeout?: number): Promise<boolean>
  top(): void
  textOf(selector: string): string
  label(t: string): void
}

export function createDriver(): Driver {
  const api: Driver = {
    sleep,

    label(t: string) { cursor.label = t },

    async moveTo(target, nth = 0) {
      const el = typeof target === 'string'
        ? document.querySelectorAll<HTMLElement>(target)[nth]
        : target
      if (!el) return false
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      await sleep(220)
      const r = el.getBoundingClientRect()
      cursor.visible = true
      await moveToPoint(r.left + Math.min(r.width / 2, 60), r.top + r.height / 2)
      await sleep(120)
      return true
    },

    async click(target, nth = 0) {
      const el = typeof target === 'string'
        ? document.querySelectorAll<HTMLElement>(target)[nth]
        : target
      if (!el) return false
      await api.moveTo(el)
      cursor.clicking = true
      await sleep(150)
      cursor.clicking = false
      el.click()
      await sleep(260)
      return true
    },

    async clickText(text, opt) {
      const el = findClickable(text)
      if (!el) {
        if (!opt?.optional) console.warn('[demo] 找不到可点元素：', text)
        return false
      }
      await api.click(el)
      return true
    },

    async type(selector, text, cps = 42) {
      const el = document.querySelector(selector) as HTMLTextAreaElement | HTMLInputElement | null
      if (!el) return false
      await api.moveTo(el)
      el.focus()
      cursor.typing = true
      await sleep(160)
      for (const ch of Array.from(text)) {
        el.value = (el.value || '') + ch
        el.dispatchEvent(new Event('input', { bubbles: true }))
        await sleep(Math.max(28, 1000 / cps))
      }
      cursor.typing = false
      await sleep(200)
      return true
    },

    async goto(route, ms = 900) {
      window.location.hash = '#' + route
      await sleep(ms)
    },

    async waitFor(selector, timeout = 8000) {
      const t0 = performance.now()
      while (performance.now() - t0 < timeout) {
        const el = document.querySelector<HTMLElement>(selector)
        if (el && isVisible(el)) return true
        await sleep(200)
      }
      return false
    },

    top() {
      window.scrollTo(0, 0)
      const c = document.querySelector('.content') as HTMLElement | null
      if (c) c.scrollTop = 0
    },

    textOf(selector) {
      return (document.querySelector(selector)?.textContent || '').trim()
    },
  }
  return api
}
