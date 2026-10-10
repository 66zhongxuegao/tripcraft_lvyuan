<template>
  <div class="prof">
    <!-- 顶部：综合掌握度 + 关键指标 -->
    <section class="card hero-card rise">
      <div class="gauge">
        <svg viewBox="0 0 120 120" class="gauge-svg">
          <circle cx="60" cy="60" r="52" fill="none" stroke="#eef2f7" stroke-width="9" />
          <circle cx="60" cy="60" r="52" fill="none" stroke="#2577e3" stroke-width="9" stroke-linecap="round"
            :stroke-dasharray="C52" :stroke-dashoffset="off(52, animTeach)" transform="rotate(-90 60 60)" class="ring-fill" />
          <circle cx="60" cy="60" r="38" fill="none" stroke="#eef2f7" stroke-width="8" />
          <circle cx="60" cy="60" r="38" fill="none" stroke="#e08a1e" stroke-width="8" stroke-linecap="round"
            :stroke-dasharray="C38" :stroke-dashoffset="off(38, animReal)" transform="rotate(-90 60 60)" class="ring-fill" />
        </svg>
        <div class="gauge-txt">
          <div class="g-vals">
            <span class="v teach"><i class="dot" />教学 {{ overall.teach }}</span>
            <span class="v real"><i class="dot" />实战 {{ overall.real }}</span>
          </div>
        </div>
      </div>
      <div class="hero-mid">
        <div class="t">综合掌握度</div>
        <div class="hero-tags">
          <span class="chip"><i class="sw teach" />教学掌握度</span>
          <span class="chip"><i class="sw real" />实战掌握度</span>
        </div>
      </div>
      <div class="hero-stats">
        <div class="hs"><div class="n">{{ totalPoints }}</div><div class="l">技能点</div></div>
        <div class="hs"><div class="n warn">{{ weakPoints.length }}</div><div class="l">薄弱点</div></div>
        <div class="hs"><div class="n ok">{{ masteredPoints.length }}</div><div class="l">已熟练</div></div>
      </div>
    </section>

    <!-- 图表区：雷达 + 折线 -->
    <section class="charts">
      <div class="card panel rise">
        <div class="panel-head"><SIcon name="target" :size="15" /><span>能力雷达</span></div>
        <div ref="radarRef" class="chart radar"></div>
      </div>
      <div class="card panel rise">
        <div class="panel-head"><SIcon name="wave" :size="15" /><span>掌握度趋势</span></div>
        <div ref="lineRef" class="chart line"></div>
      </div>
    </section>

    <!-- 画像记忆：画像 Agent 的定性描述与学习建议 -->
    <section class="card panel rise memory">
      <div class="panel-head">
        <SIcon name="notebook" :size="15" /><span>画像记忆</span>
        <span v-if="report.kind" class="mem-kind">{{ report.kind === 'initial' ? '初始画像' : '动态刷新' }}</span>
        <span v-if="report.created_at" class="mem-time">{{ (report.created_at || '').replace('T', ' ') }}</span>
        <button class="mem-refresh" :disabled="refreshing" @click="refreshProfile">
          <SIcon name="refresh" :size="14" /><span>{{ refreshing ? '画像 Agent 更新中…' : '更新画像' }}</span>
        </button>
      </div>

      <template v-if="report.summary">
        <div class="mem-summary">{{ report.summary }}</div>

        <template v-if="(report.strengths || []).length">
          <div class="mem-label">长板</div>
          <div class="mem-strengths">
            <div v-for="(s, i) in report.strengths" :key="i" class="strength">
              <i class="st-dot" /><span>{{ s }}</span>
            </div>
          </div>
        </template>

        <div class="mem-label">学习建议</div>
        <div class="mem-sugs">
          <div v-for="(s, i) in report.suggestions || []" :key="i" class="mem-sug"
            :style="{ animationDelay: (0.05 * i) + 's' }">
            <div class="ms-head">
              <span class="ms-dim">{{ s.dim_name }}</span>
              <span class="ms-title">{{ s.title }}</span>
            </div>
            <div class="ms-line"><span class="ms-k">为什么</span><span class="ms-v">{{ s.why }}</span></div>
            <div class="ms-line"><span class="ms-k">怎么练</span><span class="ms-v">{{ s.how }}</span></div>
            <button v-if="s.skill_point_id" class="ms-go" @click="go(s.skill_point_id)">
              {{ s.skill_point_id }} 去学习 <SIcon name="right" :size="12" />
            </button>
          </div>
        </div>
      </template>

      <div v-else class="mem-empty">
        <div class="me-text">{{ canAssess
          ? '还没有画像记忆。先做一次初始画像测评，画像 Agent 会给出教学掌握度基线与学习建议。'
          : '还没有画像记忆。点右上角「更新画像」，让画像 Agent 读一遍掌握度与实战记录生成动态学情画像。' }}</div>
        <router-link v-if="canAssess" to="/profile/quiz" class="tc-btn">
          <SIcon name="sparkle" :size="15" /> 开始画像
        </router-link>
      </div>
    </section>

    <!-- 维度钻取 -->
    <section class="card panel rise">
      <div class="panel-head"><SIcon name="layers" :size="15" /><span>能力维度明细</span></div>
      <div class="dims">
        <div v-for="d in dims" :key="d.id" class="dim" :class="{ open: openSet.has(d.id) }">
          <div class="dim-head" @click="toggle(d.id)">
            <span class="tag">{{ d.id }}</span>
            <span class="dn">{{ d.name }}</span>
            <div class="dim-meters">
              <div class="meter"><span class="ml">教学</span><div class="track"><i class="teach" :style="{ width: d.teach + '%' }" /></div></div>
              <div class="meter"><span class="ml">实战</span><div class="track"><i class="real" :style="{ width: d.real + '%' }" /></div></div>
            </div>
            <span class="avg"><b>{{ d.teach }}</b> / <b class="real">{{ d.real }}</b></span>
            <SIcon :name="openSet.has(d.id) ? 'up' : 'right'" :size="16" class="chev" />
          </div>
          <transition name="expand">
            <div v-if="openSet.has(d.id)" class="expand-wrap">
              <div class="dim-body">
                <div v-for="p in d.points" :key="p.id" class="sp" @click="go(p.id)">
                  <span class="pid">{{ p.id }}</span>
                  <span class="pn">{{ p.name }}</span>
                  <span class="cp" :class="p.checkpoint">{{ p.checkpoint === 'B' ? '问题应对' : '动作' }}</span>
                  <div class="sp-bars">
                    <div class="track"><i class="teach" :style="{ width: p.teach + '%' }" /></div>
                    <div class="track"><i class="real" :style="{ width: p.real + '%' }" /></div>
                  </div>
                  <span class="lv" :class="'lv-' + masteryOf(p.real || p.teach)">{{ masteryOf(p.real || p.teach) }}</span>
                  <span class="go">去学习 ›</span>
                </div>
              </div>
            </div>
          </transition>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'
import SIcon from '@/components/SIcon.vue'

const router = useRouter()
const userStore = useUserStore()
const dims = ref<any[]>([])
const report = ref<any>({})
const canAssess = ref(false)
const refreshing = ref(false)
const overall = ref({ teach: 0, real: 0 })
const animTeach = ref(0)
const animReal = ref(0)
const openSet = ref(new Set<string>())

const SHORT: Record<string, string> = { C1: '沟通', C2: '需求', C3: '方案', C4: '资源', C5: '报价', C6: '应急', C7: '合规', C8: '跨文化' }

const radarRef = ref<HTMLElement | null>(null)
const lineRef = ref<HTMLElement | null>(null)
const trend = ref<any[]>([])
let radarChart: echarts.ECharts | null = null
let lineChart: echarts.ECharts | null = null

const C52 = 2 * Math.PI * 52
const C38 = 2 * Math.PI * 38
const off = (r: number, v: number) => 2 * Math.PI * r * (1 - Math.min(100, Math.max(0, v)) / 100)

const allPoints = computed(() => dims.value.flatMap((d: any) => d.points || []))
const totalPoints = computed(() => allPoints.value.length)
const weakPoints = computed(() => allPoints.value.filter((p: any) => (p.real || p.teach) < 70))
const masteredPoints = computed(() => allPoints.value.filter((p: any) => (p.real || p.teach) >= 90))

function masteryOf(v: number): string {
  if (v >= 90) return 'M5'
  if (v >= 80) return 'M4'
  if (v >= 70) return 'M3'
  if (v >= 60) return 'M2'
  return 'M1'
}

function toggle(id: string) {
  const s = new Set(openSet.value)
  if (s.has(id)) s.delete(id); else s.add(id)
  openSet.value = s
}
function go(id: string) { router.push(`/learn/thread/${id}`) }

function radarOption(): any {
  return {
    tooltip: { trigger: 'item' },
    legend: { top: 0, right: 4, itemWidth: 12, itemHeight: 8, textStyle: { color: '#6b7a90', fontSize: 14 } },
    radar: {
      indicator: dims.value.map((d: any) => ({ name: d.name, max: 100 })),
      radius: '64%', center: ['50%', '54%'],
      splitNumber: 5,
      axisName: { color: '#6b7a90', fontSize: 13 },
      splitArea: { areaStyle: { color: ['#ffffff', '#f5f9ff', '#ffffff', '#f5f9ff', '#ffffff'] } },
      axisLine: { lineStyle: { color: '#e3e9f1' } },
      splitLine: { lineStyle: { color: '#e3e9f1' } },
    },
    series: [{
      type: 'radar', symbol: 'circle', symbolSize: 4,
      data: [
        {
          name: '教学', value: dims.value.map((d: any) => d.teach),
          lineStyle: { color: '#2577e3', width: 2.4 },
          itemStyle: { color: '#2577e3' },
          areaStyle: { color: 'rgba(37,119,227,0.16)' },
        },
        {
          name: '实战', value: dims.value.map((d: any) => d.real),
          lineStyle: { color: '#e08a1e', width: 2.4 },
          itemStyle: { color: '#e08a1e' },
          areaStyle: { color: 'rgba(224,138,30,0.13)' },
        },
      ],
      animationDuration: 900, animationEasing: 'cubicOut',
    }],
  }
}

function lineOption(): any {
  const t = trend.value || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, right: 4, itemWidth: 12, itemHeight: 8, textStyle: { color: '#6b7a90', fontSize: 14 } },
    grid: { left: 36, right: 16, top: 34, bottom: 30 },
    xAxis: {
      type: 'category', data: t.map((x: any) => x.date), boundaryGap: false,
      axisLine: { lineStyle: { color: '#e3e9f1' } }, axisTick: { show: false },
      axisLabel: { color: '#6b7a90', fontSize: 13 },
    },
    yAxis: {
      type: 'value', max: 100, min: 0,
      splitLine: { lineStyle: { color: '#eef1f6' } },
      axisLabel: { color: '#9aa8bb', fontSize: 13 },
    },
    series: [
      {
        name: '教学', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
        data: t.map((x: any) => x.teach),
        lineStyle: { width: 2.5, color: '#2577e3' }, itemStyle: { color: '#2577e3' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(37,119,227,0.22)' }, { offset: 1, color: 'rgba(37,119,227,0)' }]) },
      },
      {
        name: '实战', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
        data: t.map((x: any) => x.real),
        lineStyle: { width: 2.5, color: '#e08a1e' }, itemStyle: { color: '#e08a1e' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(224,138,30,0.2)' }, { offset: 1, color: 'rgba(224,138,30,0)' }]) },
      },
    ],
    animationDuration: 900, animationEasing: 'cubicOut',
  }
}

function render() {
  if (radarChart && radarRef.value) radarChart.setOption(radarOption(), true)
  if (lineChart && lineRef.value) lineChart.setOption(lineOption(), true)
}
function resize() { radarChart?.resize(); lineChart?.resize() }

async function loadData() {
  try {
    const [r, t] = await Promise.all([
      client.get('/learn/map', { params: { user_id: userStore.userId } }),
      client.get(`/profiles/${userStore.userId}/trend`),
    ])
    dims.value = r.data.dimensions || []
    overall.value = r.data.overall || { teach: 0, real: 0 }
    trend.value = t.data.trend || []
  } catch { dims.value = [] }
  animTeach.value = 0
  animReal.value = 0
  requestAnimationFrame(() => requestAnimationFrame(() => {
    animTeach.value = overall.value.teach
    animReal.value = overall.value.real
  }))
  render()
}

async function loadReport() {
  try {
    const r = await client.get(`/profiles/${userStore.userId}/intake`)
    report.value = r.data.report || {}
    canAssess.value = !!r.data.can_assess
  } catch { report.value = {} }
}

/** 更新画像：画像 Agent 重读掌握度 / 实战 / 答题 / 旧报告，重出定性描述与建议。 */
async function refreshProfile() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    const r = await client.post(`/profiles/${userStore.userId}/refresh`)
    report.value = r.data.report || {}
    await loadData()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '更新画像失败')
  } finally { refreshing.value = false }
}

onMounted(async () => {
  await Promise.all([loadData(), loadReport()])
  radarChart = radarRef.value ? echarts.init(radarRef.value) : null
  lineChart = lineRef.value ? echarts.init(lineRef.value) : null
  render()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  radarChart?.dispose()
  lineChart?.dispose()
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.ring-fill { transition: stroke-dashoffset 1.2s cubic-bezier(.4,0,.2,1); }
@keyframes gaugeIn { from { opacity: 0; transform: scale(.7); } to { opacity: 1; transform: scale(1); } }
.prof { width: 100%; max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-lg; box-shadow: $shadow-card; }

/* 顶部总览 */
.hero-card { padding: 22px 26px; display: flex; align-items: center; gap: 28px; background: linear-gradient(135deg, #ffffff 0%, #f5f9ff 100%); }
.gauge { position: relative; width: 186px; height: 186px; flex-shrink: 0; animation: gaugeIn .7s cubic-bezier(.34,1.56,.64,1) both; }
.gauge-svg { width: 100%; height: 100%; }
.gauge-txt { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.g-vals { display: flex; flex-direction: column; gap: 3px; align-items: center; }
.v { font-size: 17px; font-weight: 800; line-height: 1.2; display: flex; align-items: center; gap: 5px; white-space: nowrap; }
.v .dot { width: 6px; height: 6px; border-radius: 50%; }
.v.teach .dot { background: #2577e3; }
.v.real .dot { background: #e08a1e; }
.v.teach { color: #2577e3; }
.v.real { color: #e08a1e; }
.hero-mid { flex: 1; }
.hero-mid .t { font-size: 26px; font-weight: 800; }
.hero-tags { display: flex; gap: 10px; margin-top: 12px; }
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 15px; color: $color-text-secondary; background: #fff; border: 1px solid $color-border; padding: 4px 12px; border-radius: 999px; }
.sw { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.sw.teach { background: #2577e3; }
.sw.real { background: #e08a1e; }
.hero-stats { display: flex; gap: 12px; }
.hs { min-width: 84px; text-align: center; padding: 12px 14px; border-radius: $radius-md; background: #fff; border: 1px solid $color-border; }
.hs .n { font-size: 30px; font-weight: 800; color: $color-primary; }
.hs .n.warn { color: #e08a1e; }
.hs .n.ok { color: #12a76a; }
.hs .l { margin-top: 4px; font-size: 15px; color: $color-text-secondary; }

/* 图表 */
.charts { display: grid; grid-template-columns: 1.15fr 1fr; gap: 16px; }
.panel { padding: 16px 18px 14px; }
.panel-head { display: flex; align-items: center; gap: 9px; font-size: 19px; font-weight: 700; color: $color-text; margin-bottom: 8px; }
.panel-head svg { color: $color-primary; }

.chart { width: 100%; }
.chart.radar { height: 320px; }
.chart.line { height: 320px; }

/* 维度钻取 */
.dims { display: flex; flex-direction: column; gap: 8px; }
.dim { border: 1px solid $color-border; border-radius: $radius-md; overflow: hidden; transition: box-shadow .2s ease, border-color .2s ease; }
.dim.open { border-color: #cfe0f7; box-shadow: 0 4px 16px rgba(37,119,227,0.08); }
.dim-head { display: flex; align-items: center; gap: 12px; padding: 11px 14px; cursor: pointer; user-select: none; }
.dim-head:hover { background: $color-primary-softer; }
.tag { font-size: 15px; font-weight: 700; color: $color-primary; background: $color-primary-soft; padding: 2px 8px; border-radius: 5px; }
.dn { font-size: 17.5px; font-weight: 700; width: 170px; }
.dim-meters { flex: 1; display: flex; gap: 16px; max-width: 360px; }
.meter { display: flex; align-items: center; gap: 7px; width: 100%; }
.ml { font-size: 14.5px; color: $color-text-secondary; width: 26px; }
.track { position: relative; flex: 1; height: 6px; border-radius: 999px; background: #eef1f5; overflow: hidden; }
.track i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; transition: width .6s cubic-bezier(.4,0,.2,1); }
.track i.teach { background: #2577e3; }
.track i.real { background: #e08a1e; }
.avg { font-size: 15px; color: $color-text-secondary; white-space: nowrap; }
.avg b { color: #2577e3; font-weight: 800; }
.avg b.real { color: #e08a1e; }
.chev { color: $color-text-muted; transition: transform .25s ease; }
.dim.open .chev { transform: rotate(90deg); }

.expand-wrap { display: grid; grid-template-rows: 1fr; }
.dim-body { overflow: hidden; min-height: 0; display: flex; flex-direction: column; gap: 3px; padding: 0 14px 12px; background: #fbfdff; border-top: 1px solid $color-border; }
.expand-enter-active, .expand-leave-active { transition: grid-template-rows .4s cubic-bezier(.4,0,.2,1), opacity .25s ease; }
.expand-enter-from, .expand-leave-to { grid-template-rows: 0fr; opacity: 0; }
.expand-enter-to, .expand-leave-from { grid-template-rows: 1fr; opacity: 1; }

.sp { display: flex; align-items: center; gap: 10px; padding: 9px 8px; border-radius: 6px; font-size: 15.5px; cursor: pointer; }
.sp:hover { background: $color-primary-softer; }
.pid { font-family: ui-monospace, monospace; font-size: 14.5px; color: $color-text-muted; width: 38px; }
.pn { flex: 1; font-weight: 500; }
.cp { font-size: 14px; padding: 1px 7px; border-radius: 999px; background: #eef1f5; color: $color-text-muted; white-space: nowrap; }
.cp.B { background: #fff3e0; color: #b8741a; }
.sp-bars { width: 180px; display: flex; flex-direction: column; gap: 3px; }
.lv { font-size: 14px; font-weight: 800; width: 28px; text-align: center; padding: 2px 0; border-radius: 5px; }
.lv-M1 { color: #e04b4b; background: #fdecec; }
.lv-M2 { color: #e08a1e; background: #fdf2e2; }
.lv-M3 { color: #4a8ff0; background: #eaf3fe; }
.lv-M4 { color: #2577e3; background: #e0edfc; }
.lv-M5 { color: #12a76a; background: #e5f7ee; }
.go { font-size: 14.5px; color: $color-primary; opacity: 0; }
.sp:hover .go { opacity: 1; }

/* 画像记忆 */
.memory .panel-head { align-items: center; flex-wrap: wrap; gap: 10px; }
.mem-kind { font-size: 13.5px; font-weight: 700; color: $color-primary; background: $color-primary-soft;
  padding: 3px 11px; border-radius: 999px; }
.mem-time { font-size: 14px; color: $color-text-muted; }
.mem-refresh { margin-left: auto; display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px;
  border: none; border-radius: 999px; cursor: pointer; color: #fff; font-size: 15px; font-weight: 700;
  background: linear-gradient(135deg, #2f7ff0, #1a63c4);
  box-shadow: 0 6px 16px rgba(37,119,227,0.26);
  transition: transform .18s cubic-bezier(.34,1.4,.6,1), box-shadow .18s ease, filter .18s ease; }
.mem-refresh:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 12px 26px rgba(37,119,227,0.34); filter: brightness(1.04); }
.mem-refresh:active:not(:disabled) { transform: translateY(0); }
.mem-refresh:disabled { background: linear-gradient(135deg, #8fbdf5, #6fa3e6); cursor: default; box-shadow: none; }
.mem-refresh:disabled svg { animation: memSpin .9s linear infinite; }
@keyframes memSpin { to { transform: rotate(360deg); } }

.mem-summary { position: relative; margin-top: 4px; padding: 16px 20px 16px 24px; border-radius: $radius-md;
  background: linear-gradient(135deg, #f7fbff, #f2f7ff); border: 1px solid #e4eefb;
  font-size: 17px; line-height: 2; letter-spacing: .2px; color: $color-text; }
.mem-summary::before { content: ''; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px;
  border-radius: 0 3px 3px 0; background: linear-gradient(180deg, $color-primary, #6aa9f7); }

.mem-label { margin: 20px 0 10px; font-size: 15px; font-weight: 700; color: $color-text-secondary;
  letter-spacing: .4px; }
.mem-label::after { content: ''; display: block; margin-top: 7px; height: 1px;
  background: linear-gradient(90deg, #e4eefb, rgba(228,238,251,0)); }

.mem-strengths { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 9px; }
.strength { display: flex; align-items: flex-start; gap: 10px; padding: 11px 14px; border-radius: $radius-md;
  background: #f6fbf8; border: 1px solid #e2f1e8; font-size: 15.5px; line-height: 1.75; color: $color-text; }
.st-dot { width: 7px; height: 7px; flex-shrink: 0; margin-top: 9px; border-radius: 50%; background: #12a76a; }

.mem-sugs { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 14px; }
.mem-sug { display: flex; flex-direction: column; border: 1px solid $color-border; border-radius: $radius-md;
  padding: 16px 18px 15px; background: #fff; box-shadow: 0 2px 10px rgba(23,52,94,0.04);
  animation: sugIn .46s cubic-bezier(.34,1.2,.6,1) both;
  transition: transform .18s cubic-bezier(.34,1.4,.6,1), box-shadow .18s ease, border-color .18s ease; }
.mem-sug:hover { transform: translateY(-2px); border-color: #cfe0f7; box-shadow: 0 12px 26px rgba(37,119,227,0.12); }
@keyframes sugIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.ms-head { display: flex; align-items: center; gap: 10px; padding-bottom: 11px; border-bottom: 1px dashed #e8eef7; }
.ms-dim { font-size: 13.5px; font-weight: 700; color: $color-primary; background: $color-primary-soft;
  padding: 3px 10px; border-radius: 6px; white-space: nowrap; }
.ms-title { font-size: 16.5px; font-weight: 800; line-height: 1.5; }
.ms-line { display: flex; gap: 10px; margin-top: 11px; }
.ms-k { flex-shrink: 0; width: 46px; font-size: 14px; font-weight: 700; color: $color-text-muted; line-height: 1.75; }
.ms-v { flex: 1; font-size: 15.5px; line-height: 1.8; color: $color-text-secondary; }
.ms-line:nth-of-type(3) .ms-v { color: $color-text; }
.ms-go { align-self: flex-start; margin-top: 14px; display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: 999px; cursor: pointer; font-size: 14.5px; font-weight: 700;
  color: $color-primary; background: $color-primary-softer; border: 1px solid #d8e7fa;
  transition: all .18s ease; }
.ms-go:hover { background: $color-primary; border-color: $color-primary; color: #fff; }
.ms-go svg { transition: transform .18s ease; }
.ms-go:hover svg { transform: translateX(3px); }

.mem-empty { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 8px 0 4px; }
.me-text { font-size: 16px; line-height: 1.8; color: $color-text-secondary; max-width: 820px; }
.mem-empty .tc-btn { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
</style>
