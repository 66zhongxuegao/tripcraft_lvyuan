/* 演示剧本（真实前端操作）
 * 每一步都是一次真实操作：指针移动 → 点真实按钮 → 在真实输入框逐字打字。
 * 字典：评测自动往后走（选完选项自己跳下一题），只有最后一题才点提交。 */

import type { Driver } from './driver'
import { findClickable } from './driver'

export interface Beat {
  id: string
  phase: string
  title: string
  action: string
  run: (d: Driver) => Promise<void>
}

const BRIDGE_THREAD = '/learn/thread/C8.2'

function optionNode(): HTMLElement | null {
  const els = Array.from(document.querySelectorAll<HTMLElement>('.opt, .option, .q-opt, .quiz-opt, .opts > *')) as HTMLElement[]
  const visible = els.filter((e) => e.getBoundingClientRect().height > 4)
  return visible[1] || visible[0] || null
}

export const BEATS: Beat[] = [
  {
    id: 'D1', phase: '画像自测', title: '从首页点「画像」',
    action: '首页点「画像」，开始初始能力测评',
    run: async (d) => {
      await d.goto('/', 1200)
      await d.sleep(500)
      await d.clickText(['画像'], { optional: true })
      await d.sleep(2000)
      d.top()
    },
  },
  {
    id: 'D2', phase: '画像自测', title: '逐题作答（自动往后）',
    action: '每题选一个选项，选完自己跳下一题；最后一题点提交',
    run: async (d) => {
      for (let i = 0; i < 20; i++) {
        if (!location.hash.includes('/quiz')) break
        const submit = findClickable(['提交', '查看结果', '生成画像', '完成测评'])
        if (submit) {
          await d.click(submit)
          break
        }
        const opt = optionNode()
        if (!opt) break
        await d.click(opt)
        await d.sleep(800)
      }
      await d.sleep(2200)
      d.top()
    },
  },
  {
    id: 'D3', phase: '画像自测', title: '测评完成 · 看画像',
    action: '看 8 维分值与待补强维度',
    run: async (d) => {
      await d.sleep(1600)
      d.top()
    },
  },
  {
    id: 'D4', phase: '学员练习', title: '学习地图 · 第一层选文化桥',
    action: '点左侧「学习地图」，再点「文化桥」节点',
    run: async (d) => {
      await d.clickText('学习地图', { optional: true })
      await d.waitFor('.node', 9000)
      await d.sleep(800)
      d.top()
      await d.clickText('文化桥', { optional: true })
      await d.sleep(1600)
      d.top()
    },
  },
  {
    id: 'D5', phase: '学员练习', title: '第二层选「中马文化桥」',
    action: '在第二层点「中马文化桥」，弹出技能卡片',
    run: async (d) => {
      await d.clickText(['中马文化桥', '中马', '马来西亚'], { optional: true })
      await d.sleep(1600)
      d.top()
    },
  },
  {
    id: 'D6', phase: '学员练习', title: '点「进入跨文化训练」',
    action: '在技能卡片里点「进入跨文化训练」，进 C8.2',
    run: async (d) => {
      const ok = await d.clickText(['进入跨文化训练'], { optional: true })
      if (!ok) await d.clickText(['看内容'], { optional: true })
      await d.sleep(1500)
      if (!location.hash.includes('/thread/')) await d.goto(BRIDGE_THREAD, 1800)
      await d.waitFor('textarea.ipt', 9000)
      await d.sleep(900)
      d.top()
    },
  },
  {
    id: 'D7', phase: '学员练习', title: '点提示词并发送',
    action: '点一条提示词自动填入问题，再点「发送」',
    run: async (d) => {
      await d.clickText(['讲解'], { optional: true })
      await d.sleep(900)
      await d.clickText(['发送'], { optional: true })
      await d.sleep(1500)
      d.top()
    },
  },
  {
    id: 'D8', phase: '学员练习', title: '司南多 Agent 调用过程',
    action: '知识回召与各角色依次进入工作中',
    run: async (d) => {
      await d.sleep(7000)
      d.top()
    },
  },
  {
    id: 'D9', phase: '学员练习', title: '资源点「展开溯源」',
    action: '个性化资源上点「展开溯源」，看知识点与实战来源',
    run: async (d) => {
      await d.clickText(['展开溯源'], { optional: true })
      await d.sleep(1800)
      d.top()
    },
  },
  {
    id: 'D10', phase: '学员练习', title: '看左侧个性化资源',
    action: '点左侧「讲义 / 实操指南」查看生成的资源',
    run: async (d) => {
      await d.clickText(['实操指南', '讲义', '学习报告'], { optional: true })
      await d.sleep(2000)
      d.top()
    },
  },
  {
    id: 'D11', phase: '学员练习', title: '做题',
    action: '点「做题」，系统按当前掌握度出题',
    run: async (d) => {
      await d.clickText('做题', { optional: true })
      await d.sleep(2800)
      d.top()
    },
  },
  {
    id: 'D12', phase: '学员练习', title: '在题卡上作答',
    action: '在固定选项上点击作答',
    run: async (d) => {
      const opt = optionNode()
      if (opt) await d.click(opt)
      await d.sleep(1600)
      const submit = findClickable(['提交', '确认', '下一题'])
      if (submit) await d.click(submit)
      await d.sleep(2800)
      d.top()
    },
  },
  {
    id: 'D13', phase: '学员练习', title: '掌握度与难度变化',
    action: '答对后教学掌握度上调，右侧难度曲线向上走',
    run: async (d) => {
      await d.sleep(3000)
      d.top()
    },
  },
  {
    id: 'P1', phase: '综合实战', title: '消息中心刷新派单',
    action: '点左侧「消息中心」，再点「刷新」拉新派单',
    run: async (d) => {
      await d.clickText('消息中心', { optional: true })
      await d.waitFor('button.refresh', 9000)
      await d.sleep(800)
      await d.clickText('刷新', { optional: true })
      await d.sleep(2800)
      d.top()
    },
  },
  {
    id: 'P2', phase: '综合实战', title: '倒计时内抢单',
    action: '点「抢单」，订单进入订单管理',
    run: async (d) => {
      await d.clickText('抢单', { optional: true })
      await d.sleep(2600)
      d.top()
    },
  },
]
