<template>
  <div class="dock">
    <transition name="panel">
      <div v-if="open" class="panel card">
        <div class="p-order">
          <span class="po-label">当前订单</span>
          <select ref="selEl" class="po-sel" :value="oid" @change="pickOrder">
            <option v-for="o in orderList" :key="o.id" :value="o.order_id">
              {{ o.customer }} · {{ o.order_id.slice(-4) }} · {{ o.destination }}
            </option>
          </select>
        </div>

        <div class="p-tabs">
          <button class="p-tab" :class="{ on: tab === 'steps' }" @click="tab = 'steps'">流程进度</button>
          <button class="p-tab" :class="{ on: tab === 'gates' }" @click="tab = 'gates'">完成条件</button>
        </div>

        <div v-if="tab === 'steps'" class="p-body">
          <div v-for="(s, i) in STEPS" :key="s.id" class="s-row" :class="{ done: i < current, cur: i === current }">
            <span class="s-dot">{{ i + 1 }}</span>
            <span class="s-name">
              {{ s.name }}
              <span v-if="i === current && s.evidence" class="s-where">{{ s.evidence }}</span>
            </span>
            <span class="s-st">{{ i < current ? '已完成' : i === current ? '进行中' : '未开始' }}</span>
          </div>
        </div>

        <div v-else class="p-body">
          <div class="g-head">
            <span class="g-stage">{{ STEPS[current]?.name }}</span>
            <span class="g-cnt">{{ gateDone }}/{{ gates.length }}</span>
          </div>
          <div class="g-bar"><i :style="{ width: gatePct + '%' }" /></div>
          <div v-if="stepEvidence" class="g-where">
            <span class="gw-label">本步产出在哪里</span>{{ stepEvidence }}
          </div>
          <div v-for="g in gates" :key="g.label" class="g-row" :class="{ ok: g.ok }">
            <i class="gk" />
            <span class="g-mid">
              <span class="g-label">{{ g.label }}</span>
              <span v-if="!g.ok && g.where" class="g-where-line">去哪做：{{ g.where }}</span>
            </span>
            <button v-if="!g.ok && g.manual" class="g-do" :disabled="!!confirming" @click="confirmGate(g)">
              {{ confirming === g.action ? '登记中…' : '标记完成' }}
            </button>
          </div>
        </div>
      </div>
    </transition>

    <button class="fab" @click="toggle" :class="{ on: open }">
      <span class="fab-halo" />
      <svg class="fab-ring" viewBox="0 0 88 88">
        <circle cx="44" cy="44" r="37" fill="none" stroke="rgba(255,255,255,0.28)" stroke-width="6" />
        <circle cx="44" cy="44" r="37" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"
          :stroke-dasharray="C" :stroke-dashoffset="offset" transform="rotate(-90 44 44)" />
      </svg>
      <span class="fab-txt">{{ current + 1 }}<i>/13</i></span>
      <span class="fab-sub">流程进度</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import client from '@/api/client'
import { usePracticeStore } from '@/stores/practice'

const props = defineProps<{ orderId?: string }>()
const practice = usePracticeStore()

const open = ref(false)
const tab = ref<'steps' | 'gates'>('steps')
const STEPS = ref<{ id: string; name: string; state?: string; evidence?: string }[]>([])
const gates = ref<{ action: string; label: string; ok: boolean; where?: string; manual?: boolean }[]>([])
const stepEvidence = ref('')
const gateDone = ref(0)
const gateTotal = ref(0)
const orderList = ref<any[]>([])
const selEl = ref<HTMLSelectElement | null>(null)

const oid = computed(() => props.orderId || practice.activeOrderId)
const C = 2 * Math.PI * 37
const total = computed(() => STEPS.value.length || 13)
const current = computed(() => {
  const i = STEPS.value.findIndex((s) => s.state === 'current')
  return i < 0 ? 0 : i
})
const offset = computed(() => C * (1 - (current.value + 1) / total.value))
const gatePct = computed(() => (gateTotal.value ? Math.round((gateDone.value / gateTotal.value) * 100) : 0))

async function load() {
  const id = oid.value
  if (!id) { STEPS.value = []; gates.value = []; gateDone.value = 0; gateTotal.value = 0; return }
  try {
    const [f, g] = await Promise.all([
      client.get(`/practice/orders/${id}/flow`),
      client.get(`/practice/orders/${id}/gates`),
    ])
    STEPS.value = f.data.steps.map((s: any, i: number) => ({
      id: 'S' + i, name: s.name, state: s.state, evidence: s.evidence || '',
    }))
    gates.value = g.data.checks
    gateDone.value = g.data.done
    gateTotal.value = g.data.total
    stepEvidence.value = g.data.step_evidence || ''    // 本步产出该交在哪

  } catch { STEPS.value = [] }
}
watch(oid, () => { load(); loadOrders() }, { immediate: true })

// 订单列表是异步来的：列表到位后要把 select 的显示值补上（否则看起来没选订单）
watch([oid, orderList, open], () => {
  const el = selEl.value
  if (!el || !oid.value) return
  if (Array.from(el.options).some((o) => o.value === oid.value)) el.value = oid.value
}, { flush: 'post' })

// 学员每做完一件事（投递、加好友、推进阶段），门控就变了：
// 光在挂载时读一次会一直显示旧进度，所以打开面板时刷新 + 平时每 6 秒轮询一次。
let dockTimer = 0
function refresh() {
  if (document.visibilityState !== 'hidden') load()
}
onMounted(() => {
  window.addEventListener('hashchange', refresh)
  dockTimer = window.setInterval(refresh, 6000)
})
onUnmounted(() => {
  window.removeEventListener('hashchange', refresh)
  if (dockTimer) clearInterval(dockTimer)
})

async function loadOrders() {
  try { orderList.value = (await client.get('/practice/orders')).data } catch { orderList.value = [] }
}

const confirming = ref('')
/** 人工确认类门槛：客户认可、客户回签、定金到账、尾款结清——学员确认后才推进平台状态 */
async function confirmGate(g: { action: string }) {
  if (confirming.value || !oid.value) return
  confirming.value = g.action
  try {
    await client.post(`/practice/orders/${oid.value}/actions`, { action: g.action })
    await load()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '登记失败')
  } finally {
    confirming.value = ''
  }
}

function pickOrder(e: Event) {
  practice.setActiveOrder((e.target as HTMLSelectElement).value)
}
function toggle() {
  open.value = !open.value
  if (open.value) {
    load()          // 打开就拉一次，别让学员看到旧门控
    loadOrders()    // 订单列表同理：抢到的新单必须马上出现在下拉框里
  }
}
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.dock { position: fixed; right: 24px; bottom: 24px; z-index: 60; display: flex; flex-direction: column; align-items: flex-end; gap: 12px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: 14px; box-shadow: 0 18px 44px rgba(16,32,56,0.18); }

.panel { width: 360px; max-height: 500px; display: flex; flex-direction: column; overflow: hidden; }
.p-order { display: flex; align-items: center; gap: 9px; padding: 12px 12px 8px; }
.po-label { font-size: 15px; color: $color-text-muted; flex-shrink: 0; }
.po-sel { flex: 1; height: 36px; border: 1px solid $color-border; border-radius: 6px; padding: 0 10px; font-size: 15.5px; color: $color-text; background: #fff; outline: none; }
.po-sel:focus { border-color: $color-primary; }
.p-tabs { display: flex; gap: 4px; padding: 8px 8px 0; border-bottom: 1px solid $color-border; }
.p-tab { border: none; background: transparent; padding: 10px 15px; font-size: 16px; color: $color-text-secondary; cursor: pointer; border-bottom: 2px solid transparent; }
.p-tab.on { color: $color-primary; font-weight: 700; border-bottom-color: $color-primary; }
.p-body { padding: 10px 12px 14px; overflow-y: auto; }

.s-row { display: flex; align-items: center; gap: 10px; padding: 9px 8px; border-radius: 7px; font-size: 15.5px; color: $color-text-muted; }
.s-row.done { color: $color-text-secondary; }
.s-row.cur { background: $color-primary-soft; color: $color-primary; font-weight: 700; }
.s-dot { width: 20px; height: 20px; border-radius: 50%; background: #eef1f5; color: $color-text-muted; font-size: 13px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.s-row.done .s-dot { background: #e8f7ee; color: #12a76a; }
.s-row.cur .s-dot { background: $color-primary; color: #fff; }
.s-name { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.s-where { font-size: 14.5px; font-weight: 400; color: $color-text-muted; }
.s-st { font-size: 14.5px; }

.g-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.g-stage { font-size: 17px; font-weight: 700; }
.g-cnt { margin-left: auto; font-size: 16px; color: $color-primary; font-weight: 700; }
.g-bar { height: 5px; border-radius: 3px; background: #eef2f7; overflow: hidden; margin-bottom: 10px; }
.g-bar i { display: block; height: 100%; background: linear-gradient(90deg,#2577e3,#4a94ec); border-radius: 3px; transition: width .4s ease; }
.g-row { display: flex; align-items: flex-start; gap: 9px; font-size: 15.5px; color: $color-text-muted; padding: 5px 0; }
.g-mid { display: flex; flex-direction: column; gap: 2px; }
.g-label { color: $color-text-secondary; }
.g-where-line { font-size: 14.5px; color: $color-text-muted; }
.g-do { flex-shrink: 0; align-self: center; height: 28px; padding: 0 11px; border-radius: 7px;
  border: 1px solid $color-primary; background: $color-primary-softer; color: $color-primary;
  font-size: 14px; font-family: inherit; font-weight: 600; cursor: pointer; transition: all .16s ease; }
.g-do:hover:not(:disabled) { background: $color-primary; color: #fff; }
.g-do:disabled { opacity: .55; cursor: default; }
.g-where { font-size: 15px; color: $color-primary; background: $color-primary-softer; border-radius: 7px; padding: 6px 9px; margin-bottom: 8px; }
.gw-label { font-weight: 700; margin-right: 6px; }
.gk { width: 13px; height: 13px; border-radius: 4px; border: 1.5px solid #cfd9e6; flex-shrink: 0; }
.g-row.ok { color: $color-text; }
.g-row.ok .gk { background: #12a76a; border-color: #12a76a; position: relative; }
.g-row.ok .gk::after { content: ''; position: absolute; left: 4px; top: 1px; width: 3px; height: 6px; border: solid #fff; border-width: 0 1.5px 1.5px 0; transform: rotate(45deg); }

.fab {
  position: relative; width: 116px; height: 116px; border-radius: 50%; border: none; cursor: pointer;
  background: linear-gradient(135deg, #2f86ff, #1a63c4);
  box-shadow: 0 14px 34px rgba(37,119,227,0.5), 0 0 0 6px rgba(37,119,227,0.10);
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px;
  transition: transform .16s ease, box-shadow .2s ease;
}
.fab:hover { transform: translateY(-3px) scale(1.03); box-shadow: 0 18px 40px rgba(37,119,227,0.58), 0 0 0 8px rgba(37,119,227,0.14); }
.fab.on { background: linear-gradient(135deg, #1a63c4, #154f9e); }
.fab-halo {
  position: absolute; inset: -8px; border-radius: 50%;
  border: 2px solid rgba(37,119,227,0.35);
  will-change: transform, opacity;
  animation: halo 2.4s ease-in-out infinite;
}
@keyframes halo { 0%,100% { transform: scale(1); opacity: .55; } 50% { transform: scale(1.1); opacity: .15; } }
.fab-ring { position: absolute; inset: 0; width: 116px; height: 116px; }
.fab-txt { position: relative; color: #fff; font-size: 27px; font-weight: 800; line-height: 1; }
.fab-txt i { font-size: 15px; font-style: normal; opacity: .88; }
.fab-sub { position: relative; margin-top: 2px; font-size: 15px; color: rgba(255,255,255,0.9); }

.panel-enter-active { transition: all .2s ease; }
.panel-enter-from { opacity: 0; transform: translateY(10px) scale(.96); }
.panel-leave-active { transition: all .14s ease; }
.panel-leave-to { opacity: 0; transform: translateY(8px) scale(.96); }
</style>