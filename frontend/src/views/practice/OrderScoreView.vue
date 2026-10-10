<template>
  <div class="oscore">
    <div class="card head">
      <div class="h-l">
        <button class="back" @click="router.push(`/practice/orders/${orderId}`)"><SIcon name="back" :size="13" /> 返回订单</button>
        <span class="oid">{{ orderId }}</span>
        <span class="ocust">{{ summary?.customer }} · {{ summary?.destination }}</span>
        <span v-if="summary?.source_market" class="otag inbound">{{ summary.source_market }} · 入境接待 · {{ summary?.language }}</span>
      </div>
      <div class="h-r">
        <div class="avg-wrap">
          <template v-if="summary?.average !== null && summary?.average !== undefined">
            <span class="avg">{{ summary.average }}</span>
            <span class="avg-u">平均分<br />已评 {{ summary.evaluated }}/{{ summary.total }}</span>
          </template>
          <template v-else>
            <span class="avg none">未评分</span>
            <span class="avg-u">本单暂无评分<br />证据 {{ evidence.length }} 条</span>
          </template>
        </div>
        <button class="run" :disabled="running" @click="runScore">
          <SIcon :name="running ? 'refresh' : 'sparkle'" :size="13" />
          {{ running ? '评分中…' : summary?.average == null ? '生成本单评分' : '重新评分' }}
        </button>
      </div>
    </div>

    <div class="card stage">
      <span class="st-label">当前订单状态</span>
      <span class="st-name">{{ summary?.stage_name || '—' }}</span>
      <span class="st-gates">完成条件 {{ gateDone }}/{{ gateTotal }}</span>
      <span class="st-ev">可评分证据</span>
      <span v-for="e in evidence" :key="e.ref" class="ev-chip">{{ e.kind }} · {{ e.chars }}字</span>
      <span v-if="!evidence.length" class="st-ev muted">暂无（先拨打电话或投递交付物）</span>
    </div>

    <div v-if="coverage" class="card cover" :class="{ pass: coverage.passed }">
      <div class="cv-left">
        <span class="cv-title">覆盖校验</span>
        <span class="cv-num">{{ coverage.covered }}<i>/{{ coverage.targets }}</i></span>
        <span class="cv-pct">覆盖度 {{ Math.round(coverage.ratio * 100) }}%</span>
      </div>
      <div class="cv-bar"><i :style="{ width: Math.round(coverage.ratio * 100) + '%' }" /></div>
      <div class="cv-right">
        <span class="cv-state" :class="coverage.passed ? 'ok' : 'bad'">
          {{ coverage.passed ? '达到门槛，本次可写画像' : `低于 ${Math.round(coverage.threshold * 100)}% 门槛，本次不写画像` }}
        </span>
        <button class="lnk" @click="showGaps = !showGaps">{{ showGaps ? '收起未覆盖项' : '查看未覆盖项' }}</button>
      </div>
      <div v-if="showGaps" class="cv-gaps">
        <div v-for="g in uncovered" :key="g.skill_point_id" class="gap">
          <span class="gap-id">{{ g.skill_point_id }}</span>
          <span class="gap-name">{{ g.name }}</span>
          <span class="gap-kind">{{ g.checkpoint }} 型</span>
          <span class="gap-reason">{{ g.reason }}</span>
          <button class="tc-btn ghost p-btn" @click="review(g.skill_point_id)">去补考</button>
        </div>
        <div v-if="!uncovered.length" class="gap none">全部目标技能点均已覆盖</div>
      </div>
    </div>

    <div v-if="cal" class="card cal" :class="cal.gate?.passed ? 'ok' : 'warn'">
      <span class="cal-tag">校准基线</span>
      <template v-if="cal.gate?.passed">
        <span class="cal-txt">评分 Agent 已通过校准（一致率 {{ pct(cal.gate.agreement) }}／证据准确率 {{ pct(cal.gate.evidence_accuracy) }}，样本 {{ cal.gate.samples }} 条）</span>
      </template>
      <template v-else-if="cal.gate?.baseline">
        <span class="cal-txt">未达标（{{ pct(cal.gate.agreement) }}）→ 本次按降权写入：只下调、不上调</span>
      </template>
      <template v-else>
        <span class="cal-txt">无校准基线 → 评分 Agent 未经校准集验证，本次不写画像</span>
      </template>
      <span class="cal-th">阈值：置信 ≥ {{ cal.thresholds?.confidence }} / 边界 ±{{ cal.thresholds?.boundary_delta }}（{{ cal.thresholds?.source }}）</span>
    </div>

    <div v-if="notice" class="card notice" :class="notice.kind">{{ notice.text }}</div>

    <div v-if="reviews.length" class="card reviews">
      <div class="rv-head">
        <span class="rv-title">待人工复核</span>
        <span class="rv-sub">低置信度或贴近档位边界的判定不写入画像</span>
      </div>
      <div v-for="r in reviews" :key="r.skill_point_id" class="rv-row">
        <span class="rv-id">{{ r.skill_point_id }}</span>
        <span class="rv-score">{{ r.score }}<i>{{ r.level }}</i></span>
        <span class="rv-conf">置信 {{ r.confidence }}</span>
        <span class="rv-why">{{ r.review_reason }}</span>
        <span class="rv-ops">
          <button class="tc-btn ghost p-btn" @click="resolve(r, 'accept')">采纳</button>
          <button class="tc-btn ghost p-btn" @click="resolve(r, 'reject')">驳回</button>
        </span>
      </div>
    </div>

    <div class="dims">
      <div v-for="d in dims" :key="d.id" class="card dim">
        <div class="d-head" @click="openId = openId === d.id ? '' : d.id">
          <span class="d-dot" :style="{ background: color(d.id) }" />
          <span class="d-id">{{ d.id }}</span>
          <span class="d-name">{{ d.name }}</span>
          <span class="d-cnt">{{ d.evaluated }}/{{ d.total }}</span>
          <span class="d-score" :style="{ color: d.score == null ? '#a9b4c2' : color(d.id) }">
            {{ d.score == null ? '未评估' : d.score }}
          </span>
          <SIcon class="d-arrow" :class="{ on: openId === d.id }" name="right" :size="14" />
        </div>
        <transition name="fold">
          <div v-if="openId === d.id" class="d-body">
            <div v-for="p in d.points" :key="p.id" class="p-row" :class="{ dimmed: !p.evaluated && !p.pending }">
              <span class="p-id">{{ p.id }}</span>
              <span class="p-name">{{ p.name }}</span>
              <span v-if="p.status === '待复核'" class="p-lv pending">待复核</span>
              <span v-else-if="p.evaluated" class="p-lv" :class="p.level">{{ p.level }}</span>
              <span v-else class="p-lv none">未评估</span>
              <span class="p-score">{{ p.evaluated ? p.score : '—' }}</span>
              <button v-if="p.evaluated" class="tc-btn ghost p-btn" @click.stop="toggleEvidence(p.id)">依据</button>
              <button class="tc-btn ghost p-btn" @click.stop="review(p.id)">{{ p.evaluated ? '复盘' : '去练习' }}</button>
            </div>
            <div v-if="openEvidence" class="ev-box">
              <template v-for="p in d.points" :key="'ev' + p.id">
                <div v-if="openEvidence === p.id && p.evaluated" class="ev-detail">
                  <div class="ev-comment">{{ p.comment }}</div>
                  <div v-for="(e, i) in p.evidence" :key="i" class="ev-quote">
                    <span class="ev-kind">{{ e.kind || 'message' }}</span>「{{ e.quote }}」
                  </div>
                </div>
              </template>
            </div>
          </div>
        </transition>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'

const route = useRoute()
const router = useRouter()
const orderId = computed(() => String(route.params.id || ''))
const summary = ref<any>(null)
const gates = ref<any>({ done: 0, total: 0 })
const evidence = ref<any[]>([])
const coverage = ref<any>(null)
const reviews = ref<any[]>([])
const cal = ref<any>(null)
const dims = ref<any[]>([])
const openId = ref('C1')
const openEvidence = ref('')
const showGaps = ref(false)
const running = ref(false)
const notice = ref<{ kind: string; text: string } | null>(null)

const COLORS: Record<string, string> = {
  C1: '#2577e3', C2: '#12a76a', C3: '#7a5af8', C4: '#e08a1e',
  C5: '#e0567a', C6: '#0ea5b7', C7: '#64748b', C8: '#8b5cf6',
}
function color(id: string) { return COLORS[id] || '#2577e3' }

const gateDone = computed(() => gates.value.done || 0)
const gateTotal = computed(() => gates.value.total || 0)
const uncovered = computed<any[]>(() => (coverage.value?.items || []).filter((i: any) => !i.covered))

async function load() {
  try {
    const [s, g, e, c, r, cl] = await Promise.all([
      client.get(`/practice/orders/${orderId.value}/scores`),
      client.get(`/practice/orders/${orderId.value}/gates`),
      client.get(`/practice/orders/${orderId.value}/evidence`),
      client.get(`/practice/orders/${orderId.value}/coverage`),
      client.get(`/practice/orders/${orderId.value}/reviews`),
      client.get('/calibration'),
    ])
    cal.value = cl.data
    summary.value = s.data
    gates.value = g.data
    evidence.value = e.data
    coverage.value = c.data
    reviews.value = r.data
    // 待复核的点也显示出来
    for (const d of s.data.dimensions) {
      for (const p of d.points) {
        const rv = r.data.find((x: any) => x.skill_point_id === p.id)
        if (rv) { p.pending = true; p.score = rv.score; p.level = rv.level }
      }
    }
    dims.value = s.data.dimensions
  } catch { dims.value = [] }
}

async function runScore() {
  running.value = true
  notice.value = { kind: 'info', text: '评分 Agent 正在对照 Rubric 逐点判定，每条判定都要引用证据，请稍候…' }
  try {
    const r = (await client.post(`/practice/orders/${orderId.value}/score`)).data
    const bits = [`本单评出 ${r.scored} 个技能点（平均 ${r.average ?? '—'}）`]
    if (r.dropped?.length) bits.push(`${r.dropped.length} 个因拿不到证据未给分`)
    if (r.escalated?.length) bits.push(`${r.escalated.length} 个转人工复核`)
    if (r.written) bits.push(`已写回画像 ${r.written} 项`)
    if (r.deferred) bits.push('覆盖度不足，本次未写画像')
    notice.value = { kind: r.deferred || r.escalated?.length ? 'warn' : 'ok', text: bits.join('；') + '。' }
    await load()
  } catch (e: any) {
    notice.value = { kind: 'bad', text: e?.response?.data?.detail || '评分失败，请稍后重试' }
  } finally {
    running.value = false
  }
}

async function resolve(r: any, decision: string) {
  try {
    await client.post(`/practice/orders/${orderId.value}/reviews/${r.skill_point_id}`, { decision })
    await load()
  } catch (e: any) {
    notice.value = { kind: 'bad', text: e?.response?.data?.detail || '操作失败' }
  }
}

function pct(v: number | undefined) { return v === undefined ? '—' : Math.round(v * 100) + '%' }
function toggleEvidence(id: string) { openEvidence.value = openEvidence.value === id ? '' : id }
function review(id: string) { router.push(`/learn/thread/${id}`) }

onMounted(load)
watch(orderId, () => {
  summary.value = null
  dims.value = []
  reviews.value = []
  notice.value = null
  load()
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.oscore { max-width: 1000px; display: flex; flex-direction: column; gap: 12px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 18px; }
.h-l { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.back { display: inline-flex; align-items: center; gap: 4px; border: 1px solid $color-border; background: #fff; border-radius: 999px; padding: 5px 13px; font-size: 15.5px; color: $color-primary; cursor: pointer; }
.back:hover { background: $color-primary-softer; }
.oid { font-family: ui-monospace, monospace; font-size: 15px; color: #e04b4b; font-weight: 600; }
.ocust { font-size: 15.5px; font-weight: 600; }
.otag { font-size: 15.5px; padding: 2px 9px; border-radius: 4px; }
.otag.inbound { background: #efe9fe; color: #7a5af8; }
.h-r { display: flex; align-items: center; gap: 14px; }
.avg-wrap { display: flex; align-items: center; gap: 7px; }
.avg { font-size: 26px; font-weight: 800; color: $color-primary; }
.avg.none { font-size: 16px; color: $color-text-muted; }
.avg-u { font-size: 15px; color: $color-text-muted; line-height: 1.4; }
.run {
  display: inline-flex; align-items: center; gap: 6px; border: none; cursor: pointer;
  border-radius: 999px; padding: 9px 18px; font-size: 15px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, #2577e3, #1a63c4); box-shadow: 0 6px 16px rgba(37,119,227,0.28);
}
.run:hover { filter: brightness(1.06); }
.run:disabled { opacity: .7; cursor: default; }

.stage { display: flex; align-items: center; gap: 10px; padding: 12px 18px; flex-wrap: wrap; }
.st-label { font-size: 15.5px; color: $color-text-muted; }
.st-name { font-size: 15.5px; font-weight: 700; }
.st-gates { font-size: 15.5px; color: $color-primary; background: $color-primary-soft; border-radius: 999px; padding: 3px 12px; }
.st-ev { margin-left: 8px; font-size: 15.5px; color: $color-text-muted; }
.st-ev.muted { color: $color-text-muted; }
.ev-chip { font-size: 15.5px; background: $color-primary-softer; color: $color-text-secondary; border-radius: 999px; padding: 3px 11px; }

.cover { display: grid; grid-template-columns: 260px 1fr; grid-template-areas: "left bar" "gaps gaps"; align-items: center; gap: 10px 16px; padding: 13px 18px; border-left: 4px solid #e04b4b; }
.cover.pass { border-left-color: #12a76a; }
.cv-left { grid-area: left; display: flex; align-items: baseline; gap: 10px; }
.cv-title { font-size: 15px; font-weight: 700; }
.cv-num { font-size: 20px; font-weight: 800; color: $color-primary; }
.cv-num i { font-size: 15.5px; color: $color-text-muted; font-style: normal; }
.cv-pct { font-size: 15.5px; color: $color-text-secondary; }
.cv-bar { grid-area: bar; height: 8px; border-radius: 999px; background: #eef1f5; overflow: hidden; }
.cv-bar i { display: block; height: 100%; background: linear-gradient(90deg, #2577e3, #4f9bf5); }
.cover.pass .cv-bar i { background: linear-gradient(90deg, #12a76a, #35c084); }
.cv-right { grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; }
.cv-state { font-size: 15.5px; }
.cv-state.ok { color: #0d8a55; }
.cv-state.bad { color: #c0392b; }
.cv-gaps { grid-area: gaps; border-top: 1px dashed #eef1f5; padding-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.gap { display: flex; align-items: center; gap: 10px; font-size: 15.5px; padding: 4px 0; }
.gap.none { color: $color-text-muted; }
.gap-id { font-family: ui-monospace, monospace; color: $color-text-muted; width: 46px; }
.gap-name { font-weight: 600; }
.gap-kind { font-size: 14.5px; background: #eef1f5; border-radius: 4px; padding: 1px 6px; color: $color-text-secondary; }
.gap-reason { color: $color-text-secondary; }

.cal { display: flex; align-items: center; gap: 12px; padding: 10px 16px; font-size: 15.5px; flex-wrap: wrap; }
.cal.ok { background: #f2fbf5; border-color: #cdeada; }
.cal.warn { background: #fffaf0; border-color: #f3e0bd; }
.cal-tag { font-size: 14.5px; border-radius: 4px; padding: 1px 7px; background: $color-primary-soft; color: $color-primary; }
.cal-txt { flex: 1; color: $color-text-secondary; }
.cal-th { color: $color-text-muted; font-size: 15px; }

.notice { padding: 11px 16px; font-size: 15.5px; line-height: 1.7; }
.notice.info { background: $color-primary-softer; color: $color-text-secondary; }
.notice.ok { background: #e8f7ee; color: #0d8a55; }
.notice.warn { background: #fff6e8; color: #a3620c; }
.notice.bad { background: #fdeceb; color: #c0392b; }

.reviews { padding: 13px 18px; }
.rv-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.rv-title { font-size: 15.5px; font-weight: 700; }
.rv-sub { font-size: 15.5px; color: $color-text-muted; }
.rv-row { display: flex; align-items: center; gap: 12px; padding: 7px 0; border-top: 1px dashed #f1f3f5; font-size: 15.5px; }
.rv-id { font-family: ui-monospace, monospace; color: #d98324; font-weight: 600; width: 50px; }
.rv-score { font-weight: 700; }
.rv-score i { font-style: normal; font-size: 14.5px; color: $color-text-muted; margin-left: 4px; }
.rv-conf { font-size: 15px; color: $color-text-muted; }
.rv-why { flex: 1; color: $color-text-secondary; }
.rv-ops { display: flex; gap: 6px; }

.dims { display: flex; flex-direction: column; gap: 10px; }
.dim { overflow: hidden; }
.d-head { display: flex; align-items: center; gap: 11px; padding: 13px 18px; cursor: pointer; }
.d-head:hover { background: $color-primary-softer; }
.d-dot { width: 9px; height: 9px; border-radius: 50%; }
.d-id { font-family: ui-monospace, monospace; font-size: 15.5px; color: $color-text-muted; }
.d-name { font-size: 16px; font-weight: 700; }
.d-cnt { font-size: 15px; color: $color-text-muted; }
.d-score { margin-left: auto; font-size: 17px; font-weight: 800; }
.d-arrow { color: $color-text-muted; transition: transform .2s ease; }
.d-arrow.on { transform: rotate(90deg); }
.d-body { border-top: 1px solid #f1f3f5; padding: 8px 18px 12px; }
.p-row { display: flex; align-items: center; gap: 11px; padding: 8px 0; font-size: 15px; border-bottom: 1px dashed #f4f6f9; }
.p-row:last-child { border-bottom: none; }
.p-row.dimmed { opacity: .55; }
.p-id { font-family: ui-monospace, monospace; font-size: 15.5px; color: $color-text-muted; width: 44px; }
.p-name { flex: 1; }
.p-lv { font-size: 15.5px; font-weight: 700; }
.p-lv.none { color: $color-text-muted; font-weight: 500; }
.p-lv.pending { color: #d98324; }
.p-lv.M1 { color: #e04b4b; } .p-lv.M2 { color: #d98324; } .p-lv.M3 { color: #2577e3; } .p-lv.M4 { color: #12a76a; } .p-lv.M5 { color: #0d8a55; }
.p-score { font-weight: 700; width: 34px; text-align: right; }
.p-btn { padding: 4px 12px; font-size: 15.5px; }
.ev-box { margin-top: 6px; }
.ev-detail { background: $color-primary-softer; border-radius: 8px; padding: 10px 13px; }
.ev-comment { font-size: 15.5px; color: $color-text; line-height: 1.7; margin-bottom: 6px; }
.ev-quote { font-size: 15.5px; color: $color-text-secondary; line-height: 1.8; }
.ev-kind { font-size: 14.5px; background: #fff; border: 1px solid $color-border; border-radius: 4px; padding: 1px 6px; margin-right: 6px; }
.lnk { border: none; background: none; color: $color-primary; font-size: 15.5px; cursor: pointer; padding: 0; }
.fold-enter-active, .fold-leave-active { transition: opacity .18s ease; }
.fold-enter-from, .fold-leave-to { opacity: 0; }
</style>