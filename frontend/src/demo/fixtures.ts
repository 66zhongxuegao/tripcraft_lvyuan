/* 演示剧本层：真前端 + 剧本接口
 *
 * 页面、组件、路由、交互全部是产品本来的，不改一行页面代码。
 * 只在演示账户打开时，把几个「AI 现场生成」的接口响应换成写好的剧本，
 * 这样演示每次看到的话术一致，其余接口（抢单、订单、交付物、评分、画像）仍走真实后端。
 */

import client from '@/api/client'

export interface ChatLine { reply: string; sender?: string }

export interface DemoScript {
  /** 聊天：按发送顺序排队，学员每发一条，对方回一条剧本 */
  chat: ChatLine[]
  /** 技能点线程：掌握度与老师最后一句话 */
  thread: {
    sp: string
    mastery: { teach: number; real: number; level: string }
    aiLast: string
  }
}

export const SCRIPT: DemoScript = {
  chat: [
    { reply: '收到。日期是 10 月 21 日中午到、24 日走，8 个人，里面有 2 个孩子。另外我太太不吃猪肉，周日请不要安排购物。' },
    { reply: '收到。8 人 4 天明细：双语导游 1 名 + 19 座用车全程 + 4 正餐，小计 12,800，不含房、门票、高铁。酒店这边外滩店 10/21 起只剩 4 间双床，2,180 元/间/晚，10/19 18:00 前可免费取消。' },
    { reply: '可以。乌镇景区内只剩 2 间，8 人 4 间不够，我们按景区外四星 4 间走，西栅夜游和次日二次入园保留，报价里都写清楚。' },
  ],
  thread: {
    sp: 'C1.1',
    mastery: { teach: 42, real: 0, level: 'M3' },
    aiLast: '本次练 C1.1 开场与身份确认（S2 首呼）。当前教学掌握度 42，按 M3 档出题：\n\n- M1 接通后未自报公司/姓名/身份，直接问需求\n- M2 自报姓名但未报公司或未说明定制师身份\n- M3 自报公司+姓名+身份，但未确认是否方便通话或未约定下次联系时间\n- M4 自报公司+姓名+身份，确认称呼与是否方便，但未约定下次联系时间点\n- M5 五项齐全，并给出「今天 18 点前加您微信发初稿」这样的具体时间点\n\n答完我会写回画像，并按掌握度调整下一题难度。',
  },
}

const num = (v: any) => (typeof v === 'number' ? v : Number(v) || 0)

export function installFixtures(script: DemoScript = SCRIPT) {
  const usedIds = new Set<string>()
  let queue = [...script.chat]
  let pendingSid = ''

  const reqId = client.interceptors.request.use((cfg) => {
    const m = /\/practice\/im\/sessions\/([^/]+)\/messages/.exec(cfg.url || '')
    if (m && String(cfg.method || '').toLowerCase() === 'post') pendingSid = m[1]
    return cfg
  })

  const resId = client.interceptors.response.use((res) => {
    try {
      const url = res.config?.url || ''
      const data: any = res.data

      // 聊天：把刚发出去那条的「对方回复」换成剧本，并让该会话的最新消息一致
      if (url.includes('/practice/im/sessions')) {
        const rooms = Array.isArray(data) ? data : (data?.sessions || data?.rooms || [])
        if (pendingSid) {
          const room = rooms.find((r: any) => r.session_id === pendingSid)
          if (room && Array.isArray(room.messages)) {
            const others = room.messages.filter((m: any) => m.role === 'other')
            const last = others[others.length - 1]
            const next = queue[0]
            if (last && next) {
              last.content = next.reply
              if (next.sender) last.sender = next.sender
              queue = queue.slice(1)
            }
          }
          pendingSid = ''
        }
      }

      // 技能点线程：掌握度与老师的话
      if (url.includes('/threads/')) {
        const sp = url.split('/threads/')[1]?.split(/[/?]/)[0] || ''
        if (sp === script.thread.sp && data && typeof data === 'object' && !Array.isArray(data)) {
          if (data.mastery) {
            data.mastery = {
              ...data.mastery,
              teach: num(script.thread.mastery.teach),
              real: num(script.thread.mastery.real),
              level: script.thread.mastery.level,
            }
          }
          const ai = (data.messages || []).filter((m: any) => m.role === 'ai')
          const lastAi = ai[ai.length - 1]
          if (lastAi) {
            const key = 'ai:' + String(lastAi.created_at)
            if (!usedIds.has(key)) {
              usedIds.add(key)
              lastAi.content = script.thread.aiLast
            }
          }
        }
      }
    } catch (e) {
      console.warn('[demo] 剧本层跳过一条：', e)
    }
    return res
  })

  /** 演示重跑时把剧本队列复位 */
  function reset() {
    queue = [...script.chat]
    usedIds.clear()
    pendingSid = ''
  }

  function dispose() {
    client.interceptors.request.eject(reqId)
    client.interceptors.response.eject(resId)
  }

  return { reset, dispose }
}
