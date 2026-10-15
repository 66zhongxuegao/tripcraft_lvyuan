<template>
  <div class="prac">
    <div class="head">
      <div class="h-l"><h2>我的订单</h2><span class="h-sub">{{ list.length }} 单进行中</span></div>
      <div class="h-tabs">
        <button v-for="t in TABS" :key="t" class="tab" :class="{ on: tab === t }" @click="tab = t">{{ t }}</button>
      </div>
    </div>

    <div class="orders">
      <div v-for="o in list" :key="o.order_id" class="order card" :class="{ hl: o.order_id === highlighted }" @click="open(o)">
        <div class="o-top">
          <i v-if="hasNew(o)" class="dot-new" title="订单状态有变化" />
          <span class="o-id">{{ o.order_id }}</span>
          <span class="o-cust">{{ o.customer }} · {{ o.destination }}</span>
          <span class="o-tag" :class="o.status === '正常' ? 'ok' : 'bad'">{{ o.status }}</span>
        </div>

        <div class="o-stage">
          <Countdown v-if="o.dispatch && !o.dispatch.claimed && !o.dispatch.lost"
            :until="o.dispatch.window_end" prefix="抢单剩" class="cd" />
          <span v-else-if="o.dispatch && o.dispatch.first_call && !o.dispatch.first_call.done"
            class="cd-wrap"><Countdown :until="o.dispatch.first_call.due_at" prefix="首呼剩" /></span>
          <span class="dots">
            <i v-for="(s, i) in steps" :key="s" class="dot"
              :class="{ done: i < o.stage_index, cur: i === o.stage_index }" />
          </span>
          <span class="stage-name">{{ o.stage_name }}</span>
          <span v-if="o.urgent" class="urgent">急需处理</span>
        </div>

        <div class="o-foot">
          <span class="hint"><SIcon name="sparkle" :size="12" />{{ o.hint || '' }}</span>
          <span class="acts">
            <button class="act" @click.stop="goto(o, 'deliverables')">
              <SIcon name="filetext" :size="12" />交付物
            </button>
            <button class="act" @click.stop="goto(o, 'finance')">
              <SIcon name="calc" :size="12" />成本与结算
            </button>
            <button class="act" @click.stop="goto(o, 'score')">
              <SIcon name="chart" :size="12" />评分复盘
            </button>
            <span class="go">进入订单 <SIcon name="right" :size="12" /></span>
          </span>
        </div>
      </div>
      <div v-if="!list.length" class="empty">暂无订单</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import Countdown from '@/components/Countdown.vue'
import client from '@/api/client'

const router = useRouter()
const tab = ref('进行中')
const ORDERS = ref<any[]>([])
const steps = ref<string[]>([])
const TABS = ['进行中', '已完成', '已取消']

const list = computed(() => {
  const rows = ORDERS.value
  if (tab.value === '已完成') return rows.filter((o) => o.stage_index >= 7)
  if (tab.value === '已取消') return rows.filter((o) => o.status === '禁用')
  return rows.filter((o) => o.stage_index < 7 && o.status !== '禁用')
})
const route = useRoute()
const highlighted = computed(() => String(route.query.grabbed || ''))

onMounted(async () => {
  try {
    const [o, st] = await Promise.all([client.get('/practice/orders'), client.get('/practice/steps')])
    ORDERS.value = o.data
    steps.value = st.data.steps
  } catch { ORDERS.value = [] }
})
function seenKey(id: string) { return 'order_seen_' + id }
function stamp(o: any) { return `${o.stage_index}|${o.status}|${o.urgent ? 1 : 0}` }
function hasNew(o: any) {
  const seen = localStorage.getItem(seenKey(o.order_id))
  return !!seen && seen !== stamp(o)
}
function open(o: any) {
  localStorage.setItem(seenKey(o.order_id), stamp(o))
  router.push(`/practice/orders/${o.order_id}`)
}
function goto(o: any, tab: string) { router.push(`/practice/orders/${o.order_id}/${tab}`) }
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.prac { max-width: 1100px; display: flex; flex-direction: column; gap: 14px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.head { display: flex; align-items: flex-end; justify-content: space-between; }
.h-l h2 { font-size: 22px; font-weight: 800; }
.h-sub { font-size: 16px; color: $color-text-secondary; margin-left: 8px; }
.h-tabs { display: flex; gap: 6px; }
.tab { border: 1px solid $color-border; background: #fff; border-radius: 999px; padding: 5px 14px; font-size: 14px; color: $color-text-secondary; cursor: pointer; }
.tab.on { background: $color-primary; border-color: $color-primary; color: #fff; font-weight: 600; }

.orders { display: flex; flex-direction: column; gap: 10px; }
.order { padding: 15px 18px; cursor: pointer; transition: all .16s ease; }
.order:hover { border-color: $color-primary; box-shadow: $shadow-hover; transform: translateY(-2px); }
.order.hl { border-color: $color-primary; box-shadow: 0 0 0 3px rgba(37,119,227,0.16); }
.cd { margin-right: 4px; }
.o-top { display: flex; align-items: center; gap: 12px; }
.dot-new { width: 8px; height: 8px; border-radius: 50%; background: #2577e3; flex-shrink: 0; }
.o-id { font-family: ui-monospace, monospace; font-size: 15px; color: #e04b4b; font-weight: 600; }
.o-cust { font-size: 15.5px; font-weight: 600; }
.o-tag { margin-left: auto; font-size: 14px; padding: 2px 9px; border-radius: 4px; }
.o-tag.ok { background: #e8f7ee; color: #12a76a; }
.o-tag.bad { background: #fdeceb; color: #e04b4b; }

.o-stage { display: flex; align-items: center; gap: 10px; margin: 12px 0 10px; }
.dots { display: flex; gap: 5px; }
.dot { width: 22px; height: 4px; border-radius: 2px; background: #e3e9f2; display: inline-block; }
.dot.done { background: #12a76a; }
.dot.cur { background: #e04b4b; }
.stage-name { font-size: 14px; font-weight: 700; color: $color-text; }
.urgent { font-size: 13px; background: #e04b4b; color: #fff; border-radius: 8px; padding: 1px 8px; }

.o-foot { display: flex; align-items: center; justify-content: space-between; }
.hint { display: inline-flex; align-items: center; gap: 5px; font-size: 14px; color: $color-text-secondary; }
.acts { display: inline-flex; align-items: center; gap: 8px; }
.act { display: inline-flex; align-items: center; gap: 4px; font-size: 14px; color: $color-text-secondary; background: #fff; border: 1px solid $color-border; border-radius: 6px; padding: 4px 9px; cursor: pointer; }
.act:hover { border-color: $color-primary; color: $color-primary; }
.go { display: inline-flex; align-items: center; gap: 3px; font-size: 14px; color: $color-primary; }
.empty { padding: 40px; text-align: center; color: $color-text-muted; font-size: 15px; }
</style>