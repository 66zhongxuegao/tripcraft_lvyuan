<template>
  <div class="quiz">
    <!-- 闸门：已有画像数据的用户不再开放初始画像 -->
    <section v-if="blocked" class="card panel rise blocked">
      <div class="bk-icon"><SIcon name="lock" :size="26" /></div>
      <div class="bk-title">初始画像只对新用户开放</div>
      <div class="bk-desc">当前账号已有画像数据。请到学情画像页用「更新画像」刷新动态学情画像。</div>
      <router-link to="/profile" class="tc-btn"><SIcon name="chart" :size="15" /> 去学情画像</router-link>
    </section>

    <template v-else>
      <!-- 顶部进度 -->
      <section class="card panel head">
        <div class="head-left">
          <div class="head-title">初始画像测评</div>
          <div class="head-sub">{{ phase === 'quiz' ? `第 ${idx + 1} / ${total} 题` : '画像 Agent 判定你的教学掌握度基线' }}</div>
        </div>
        <div class="head-bar"><i :style="{ width: progress + '%' }" /></div>
        <div class="head-pct">{{ Math.round(progress) }}%</div>
      </section>

      <!-- 答题 -->
      <section v-if="phase === 'quiz'" class="card panel qcard">
        <transition name="swap" mode="out-in">
          <div :key="cur.id" class="qbody">
            <div class="q-dim"><i class="q-dot" />{{ cur.dim_name }}</div>
            <div class="q-title">{{ cur.title }}</div>
            <div class="opts">
              <button v-for="(o, i) in cur.options" :key="o.key" class="opt"
                :class="{ on: answers[cur.id] === o.key }" :style="{ animationDelay: (0.04 * i) + 's' }"
                @click="choose(o.key)">
                <span class="opt-key">{{ 'ABCD'[i] }}</span>
                <span class="opt-label">{{ o.label }}</span>
                <span class="opt-check"><SIcon name="check" :size="14" /></span>
              </button>
            </div>
          </div>
        </transition>
        <div class="qfoot">
          <button class="btn-ghost" :disabled="idx === 0" @click="prev"><SIcon name="back" :size="14" /> 上一题</button>
          <div class="dots">
            <i v-for="(q, i) in questions" :key="q.id" :class="{ done: answered(q.id), cur: i === idx }" />
          </div>
          <button class="tc-btn" :disabled="!answers[cur.id]" @click="next">
            {{ idx === total - 1 ? '提交并生成画像' : '下一题' }} <SIcon name="right" :size="14" />
          </button>
        </div>
      </section>

      <!-- 分析中 -->
      <section v-else-if="phase === 'analyzing'" class="card panel analyzing">
        <div class="ring-analyze">
          <svg viewBox="0 0 120 120">
            <circle cx="60" cy="60" r="52" fill="none" stroke="#eef2f7" stroke-width="7" />
            <circle cx="60" cy="60" r="52" fill="none" stroke="#2577e3" stroke-width="7" stroke-linecap="round"
              stroke-dasharray="80 246" transform="rotate(-90 60 60)" class="spin-arc" />
            <circle cx="60" cy="60" r="38" fill="none" stroke="#eef2f7" stroke-width="6" />
            <circle cx="60" cy="60" r="38" fill="none" stroke="#e08a1e" stroke-width="6" stroke-linecap="round"
              stroke-dasharray="60 179" transform="rotate(-90 60 60)" class="spin-arc rev" />
          </svg>
          <div class="ring-core"><SIcon name="sparkle" :size="22" /></div>
        </div>
        <div class="an-title">画像 Agent 正在生成你的初始画像</div>
        <div class="an-steps">
          <div v-for="(s, i) in analyzeSteps" :key="s" class="an-step" :class="{ on: i <= anIdx }">
            <i class="an-dot" />{{ s }}
          </div>
        </div>
      </section>

      <!-- 结果 -->
      <template v-else-if="phase === 'done'">
        <section class="card panel result-top">
          <div class="gauge">
            <svg viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="52" fill="none" stroke="#eef2f7" stroke-width="9" />
              <circle cx="60" cy="60" r="52" fill="none" stroke="#2577e3" stroke-width="9" stroke-linecap="round"
                :stroke-dasharray="C52" :stroke-dashoffset="off52" transform="rotate(-90 60 60)" class="ring-anim" />
            </svg>
            <div class="gauge-txt">
              <div class="g-num">{{ Math.round(animOverall) }}</div>
              <div class="g-cap">教学掌握度基线</div>
            </div>
          </div>
          <div class="result-mid">
            <div class="rm-title">初始画像已写入画像记忆</div>
            <div class="rm-desc">{{ report.summary }}</div>
            <div class="rm-tags">
              <span v-for="d in focusDims" :key="d" class="tag-focus">{{ d }}</span>
            </div>
          </div>
          <div class="radar">
            <svg viewBox="0 0 220 220" class="radar-svg" :class="{ on: radarOn }">
              <g v-for="l in [25, 50, 75, 100]" :key="'g' + l">
                <polygon :points="ringPoints(l)" fill="none" :stroke="l === 100 ? '#d6e0ed' : '#eef2f7'" stroke-width="1" />
              </g>
              <line v-for="(p, i) in axes" :key="'a' + i" x1="110" y1="110" :x2="p.x" :y2="p.y" stroke="#eef2f7" stroke-width="1" />
              <polygon :points="shapePoints" fill="rgba(37,119,227,0.22)" stroke="#2577e3" stroke-width="2" />
              <circle v-for="(p, i) in shapeDots" :key="'d' + i" :cx="p.x" :cy="p.y" r="3" fill="#2577e3" />
              <text v-for="(p, i) in labels" :key="'t' + i" :x="p.x" :y="p.y" class="radar-label"
                text-anchor="middle" dominant-baseline="middle">{{ p.text }}</text>
            </svg>
          </div>
        </section>

        <section class="result-grid">
          <div class="card panel">
            <div class="panel-head"><SIcon name="target" :size="15" /><span>维度点评</span></div>
            <div class="dimrows">
              <div v-for="d in dimRows" :key="d.id" class="dimrow">
                <span class="dr-id">{{ d.id }}</span>
                <span class="dr-name">{{ d.name }}</span>
                <div class="dr-track"><i :style="{ width: d.score + '%' }" /></div>
                <span class="dr-score">{{ d.score }}</span>
                <span class="dr-comment">{{ d.comment }}</span>
              </div>
            </div>
          </div>
          <div class="card panel">
            <div class="panel-head"><SIcon name="flame" :size="15" /><span>学习建议</span></div>
            <div class="sugs">
              <div v-for="(s, i) in report.suggestions || []" :key="i" class="sug" :style="{ animationDelay: (0.06 * i) + 's' }">
                <div class="sug-head">
                  <span class="sug-dim">{{ s.dim_name }}</span>
                  <span class="sug-title">{{ s.title }}</span>
                </div>
                <div class="sug-line"><span class="sug-k">为什么</span><span class="sug-v">{{ s.why }}</span></div>
                <div class="sug-line"><span class="sug-k">怎么练</span><span class="sug-v">{{ s.how }}</span></div>
                <button v-if="s.skill_point_id" class="sug-go" @click="goLearn(s.skill_point_id)">
                  {{ s.skill_point_id }} 去学习 <SIcon name="right" :size="12" />
                </button>
              </div>
            </div>
          </div>
        </section>

        <div class="result-foot">
          <router-link to="/profile" class="tc-btn"><SIcon name="chart" :size="15" /> 进入学情画像</router-link>
          <router-link to="/learn" class="tc-btn ghost"><SIcon name="book" :size="15" /> 去学习地图</router-link>
        </div>
      </template>

      <div v-if="error" class="err card panel">{{ error }}</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

const blocked = ref(false)
const questions = ref<any[]>([])
const answers = ref<Record<string, string>>({})
const idx = ref(0)
const phase = ref<'quiz' | 'analyzing' | 'done'>('quiz')
const report = ref<any>({})
const error = ref('')
const anIdx = ref(0)
let anTimer = 0

const total = computed(() => questions.value.length || 12)
const cur = computed(() => questions.value[idx.value] || { id: '', dim_name: '', title: '', options: [] })
const answeredCount = computed(() => questions.value.filter((q) => answers.value[q.id]).length)
const progress = computed(() => (phase.value === 'quiz' ? (answeredCount.value / total.value) * 100 : 100))
function answered(id: string) { return !!answers.value[id] }

const analyzeSteps = ['读取你的测评选择', '对齐 8 维能力基线', '生成定性描述与学习建议', '写入画像记忆']
const C52 = 2 * Math.PI * 52
const animOverall = ref(0)
const radarOn = ref(false)

const DIMS = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8']
const SHORT: Record<string, string> = { C1: '沟通', C2: '需求', C3: '方案', C4: '资源', C5: '报价', C6: '应急', C7: '合规', C8: '跨文化' }
const DIM_NAMES: Record<string, string> = { C1: '沟通信任', C2: '需求洞察', C3: '方案能力', C4: '资源整合', C5: '报价利润', C6: '应急解决', C7: '合规效率', C8: '跨文化入境游沟通' }

const scores = computed<Record<string, number>>(() => report.value.scores || {})
const overall = computed(() => {
  const v = DIMS.map((d) => scores.value[d] || 0)
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0
})
const off52 = computed(() => C52 * (1 - Math.min(100, animOverall.value) / 100))
const focusDims = computed(() => (report.value.focus || []).map((d: string) => `${d} ${SHORT[d] || d}`))
const dimRows = computed(() => DIMS.map((id) => ({
  id, name: DIM_NAMES[id], score: Math.round(scores.value[id] || 0),
  comment: (report.value.dimensions || {})[id] || '',
})))

function polar(i: number, r: number) {
  const a = (Math.PI * 2 * i) / 8 - Math.PI / 2
  return { x: 110 + r * Math.cos(a), y: 110 + r * Math.sin(a) }
}
const axes = computed(() => DIMS.map((_, i) => polar(i, 78)))
function ringPoints(level: number) {
  return DIMS.map((_, i) => { const p = polar(i, (78 * level) / 100); return `${p.x.toFixed(1)},${p.y.toFixed(1)}` }).join(' ')
}
const shapePoints = computed(() => DIMS.map((d, i) => {
  const p = polar(i, (78 * Math.max(6, scores.value[d] || 0)) / 100)
  return `${p.x.toFixed(1)},${p.y.toFixed(1)}`
}).join(' '))
const shapeDots = computed(() => DIMS.map((d, i) => polar(i, (78 * Math.max(6, scores.value[d] || 0)) / 100)))
const labels = computed(() => DIMS.map((d, i) => {
  const p = polar(i, 96)
  return { x: p.x, y: p.y, text: SHORT[d] }
}))

async function load() {
  try {
    const gate = await client.get(`/profiles/${userStore.userId}/intake`)
    if (!gate.data.can_assess) { blocked.value = true; return }
  } catch { blocked.value = true; return }
  try {
    const r = await client.get('/profile/quiz')
    questions.value = r.data.questions || []
  } catch { error.value = '题目加载失败，请返回总览重试。' }
}

function choose(key: string) {
  answers.value = { ...answers.value, [cur.value.id]: key }
  if (idx.value < total.value - 1) {
    window.setTimeout(() => { if (answers.value[cur.value.id] === key) next() }, 280)
  }
}
function next() {
  if (!answers.value[cur.value.id]) return
  if (idx.value < total.value - 1) { idx.value += 1; return }
  submit()
}
function prev() { if (idx.value > 0) idx.value -= 1 }

async function submit() {
  phase.value = 'analyzing'
  anIdx.value = 0
  anTimer = window.setInterval(() => { anIdx.value = Math.min(analyzeSteps.length - 1, anIdx.value + 1) }, 900)
  const payload = { user_id: userStore.userId, language: '中文',
    answers: questions.value.map((q) => ({ qid: q.id, key: answers.value[q.id] })) }
  try {
    const r = await client.post('/profile/assessment', payload)
    report.value = r.data.report || {}
    await new Promise((res) => window.setTimeout(res, 600))
    phase.value = 'done'
    requestAnimationFrame(() => {
      const target = overall.value
      let cur01 = 0
      const tick = () => {
        cur01 = Math.min(target, cur01 + Math.max(0.8, target / 40))
        animOverall.value = cur01
        if (cur01 < target) requestAnimationFrame(tick)
      }
      tick()
      radarOn.value = true
    })
  } catch (e: any) {
    phase.value = 'quiz'
    error.value = e?.response?.data?.detail || '生成画像失败，请重试。'
  }
}

function goLearn(sp: string) { router.push(`/learn/thread/${sp}`) }

onMounted(load)
onUnmounted(() => { if (anTimer) clearInterval(anTimer) })
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.quiz { width: 100%; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; max-width: 1240px; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-lg; box-shadow: $shadow-card; }
.panel { padding: 20px 22px; }

.blocked { display: flex; flex-direction: column; align-items: flex-start; gap: 12px; padding: 34px 32px; }
.bk-icon { width: 52px; height: 52px; border-radius: 14px; display: flex; align-items: center; justify-content: center;
  background: $color-primary-soft; color: $color-primary; }
.bk-title { font-size: 21px; font-weight: 800; }
.bk-desc { font-size: 16px; line-height: 1.75; color: $color-text-secondary; max-width: 720px; }

.head { display: flex; align-items: center; gap: 18px; padding: 16px 22px; }
.head-left { min-width: 220px; }
.head-title { font-size: 19px; font-weight: 800; }
.head-sub { margin-top: 4px; font-size: 15px; color: $color-text-secondary; }
.head-bar { flex: 1; height: 8px; border-radius: 999px; background: #eef2f7; overflow: hidden; }
.head-bar i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #2577e3, #6aa9f7);
  transition: width .45s cubic-bezier(.34,1.1,.5,1); }
.head-pct { min-width: 54px; text-align: right; font-size: 17px; font-weight: 800; color: $color-primary; }

.qcard { padding: 26px 30px 20px; }
.q-dim { display: inline-flex; align-items: center; gap: 7px; font-size: 14.5px; font-weight: 600; color: $color-primary;
  background: $color-primary-soft; padding: 4px 12px; border-radius: 999px; }
.q-dot { width: 6px; height: 6px; border-radius: 50%; background: $color-primary; }
.q-title { margin: 16px 0 20px; font-size: 25px; font-weight: 800; line-height: 1.45; }
.opts { display: flex; flex-direction: column; gap: 11px; }
.opt { display: flex; align-items: center; gap: 14px; text-align: left; padding: 16px 18px; cursor: pointer;
  border: 1px solid $color-border; border-radius: $radius-md; background: #fff; font-size: 16.5px; line-height: 1.6;
  color: $color-text; animation: optIn .34s cubic-bezier(.34,1.3,.6,1) both;
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s cubic-bezier(.34,1.4,.6,1), background .16s ease; }
@keyframes optIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.opt:hover { border-color: $color-primary; transform: translateY(-2px); box-shadow: 0 8px 20px rgba(37,119,227,0.12); }
.opt.on { border-color: $color-primary; background: $color-primary-softer; box-shadow: 0 0 0 3px rgba(37,119,227,0.12); }
.opt-key { width: 28px; height: 28px; flex-shrink: 0; border-radius: 8px; display: flex; align-items: center; justify-content: center;
  font-size: 15px; font-weight: 800; color: $color-text-secondary; background: #f1f5fa; transition: all .16s ease; }
.opt.on .opt-key { background: $color-primary; color: #fff; }
.opt-label { flex: 1; }
.opt-check { color: $color-primary; opacity: 0; transform: scale(.6); transition: all .2s cubic-bezier(.34,1.56,.64,1); }
.opt.on .opt-check { opacity: 1; transform: scale(1); }

.qfoot { margin-top: 22px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.dots { display: flex; gap: 5px; }
.dots i { width: 7px; height: 7px; border-radius: 50%; background: #e3e9f2; transition: all .2s ease; }
.dots i.done { background: #9fc4f2; }
.dots i.cur { width: 20px; border-radius: 999px; background: $color-primary; }
.btn-ghost { display: inline-flex; align-items: center; gap: 6px; padding: 9px 16px; border-radius: 999px; cursor: pointer;
  border: 1px solid $color-border; background: #fff; color: $color-text-secondary; font-size: 15.5px; }
.btn-ghost:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; }
.btn-ghost:disabled { opacity: .45; cursor: default; }
.qcard .tc-btn { display: inline-flex; align-items: center; gap: 6px; }
.qcard .tc-btn:disabled { opacity: .5; cursor: default; }
.swap-enter-active, .swap-leave-active { transition: opacity .22s ease, transform .22s cubic-bezier(.34,1.2,.6,1); }
.swap-enter-from { opacity: 0; transform: translateX(24px); }
.swap-leave-to { opacity: 0; transform: translateX(-24px); }

.analyzing { display: flex; flex-direction: column; align-items: center; gap: 20px; padding: 52px 24px 56px; }
.ring-analyze { position: relative; width: 150px; height: 150px; animation: breathe 3.2s ease-in-out infinite; }
@keyframes breathe { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.045); } }
.ring-analyze svg { width: 100%; height: 100%; }
.spin-arc { transform-origin: 60px 60px; animation: arcSpin 1.5s linear infinite; }
.spin-arc.rev { animation: arcSpin 2.3s linear infinite reverse; }
@keyframes arcSpin { to { transform: rotate(360deg); } }
.ring-core { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: $color-primary; }
.an-title { font-size: 22px; font-weight: 800; }
.an-steps { display: flex; flex-direction: column; gap: 10px; min-width: 320px; }
.an-step { display: flex; align-items: center; gap: 10px; font-size: 16px; color: $color-text-muted; transition: color .3s ease; }
.an-step .an-dot { width: 8px; height: 8px; border-radius: 50%; background: #dbe3ee; transition: all .3s ease; }
.an-step.on { color: $color-text; }
.an-step.on .an-dot { background: $color-primary; box-shadow: 0 0 0 4px rgba(37,119,227,0.14); }

.result-top { display: flex; align-items: center; gap: 32px; padding: 26px 30px; }
.gauge { position: relative; width: 186px; height: 186px; flex-shrink: 0; }
.gauge svg { width: 100%; height: 100%; }
.ring-anim { transition: stroke-dashoffset 1.1s cubic-bezier(.4,0,.2,1); }
.gauge-txt { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; }
.g-num { font-size: 44px; font-weight: 900; color: $color-primary; line-height: 1.1; }
.g-cap { font-size: 15px; color: $color-text-secondary; }
.result-mid { flex: 1; min-width: 0; }
.rm-title { font-size: 21px; font-weight: 800; }
.rm-desc { position: relative; margin-top: 14px; padding: 15px 18px 15px 22px; border-radius: $radius-md;
  background: linear-gradient(135deg, #f7fbff, #f2f7ff); border: 1px solid #e4eefb;
  font-size: 16.5px; line-height: 2; letter-spacing: .2px; color: $color-text; }
.rm-desc::before { content: ''; position: absolute; left: 0; top: 13px; bottom: 13px; width: 3px;
  border-radius: 0 3px 3px 0; background: linear-gradient(180deg, $color-primary, #6aa9f7); }
.rm-tags { margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap; }
.tag-focus { font-size: 14.5px; font-weight: 700; color: #b3730f; background: #fdf3e3; border: 1px solid #f2dcb6;
  padding: 4px 12px; border-radius: 999px; }
.radar { width: 240px; height: 240px; flex-shrink: 0; }
.radar-svg { width: 100%; height: 100%; transform: scale(.25); opacity: 0;
  transition: transform .9s cubic-bezier(.34,1.3,.5,1), opacity .5s ease; }
.radar-svg.on { transform: scale(1); opacity: 1; }
.radar-label { font-size: 11.5px; fill: #6b7a90; }

.result-grid { display: grid; grid-template-columns: 1.05fr 1fr; gap: 16px; }
.panel-head { display: flex; align-items: center; gap: 9px; font-size: 18px; font-weight: 700; margin-bottom: 12px; }
.panel-head svg { color: $color-primary; }
.dimrows { display: flex; flex-direction: column; gap: 12px; }
.dimrow { display: grid; grid-template-columns: 40px 120px 90px 40px; align-items: center; gap: 10px; }
.dr-id { font-size: 14.5px; font-weight: 800; color: $color-primary; }
.dr-name { font-size: 15.5px; font-weight: 600; }
.dr-track { height: 7px; border-radius: 999px; background: #eef2f7; overflow: hidden; }
.dr-track i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #e08a1e, #2577e3);
  transition: width 1s cubic-bezier(.4,0,.2,1); }
.dr-score { font-size: 15.5px; font-weight: 800; text-align: right; }
.dr-comment { grid-column: 1 / -1; font-size: 15px; line-height: 1.7; color: $color-text-muted; }

.sugs { display: flex; flex-direction: column; gap: 12px; }
.sug { border: 1px solid $color-border; border-radius: $radius-md; padding: 16px 18px 15px; background: #fff;
  box-shadow: 0 2px 10px rgba(23,52,94,0.04); animation: optIn .46s cubic-bezier(.34,1.2,.6,1) both;
  transition: transform .18s cubic-bezier(.34,1.4,.6,1), box-shadow .18s ease, border-color .18s ease; }
.sug:hover { transform: translateY(-2px); border-color: #cfe0f7; box-shadow: 0 12px 26px rgba(37,119,227,0.12); }
.sug-head { display: flex; align-items: center; gap: 10px; padding-bottom: 11px; border-bottom: 1px dashed #e8eef7; }
.sug-dim { font-size: 13.5px; font-weight: 700; color: $color-primary; background: $color-primary-soft; padding: 3px 10px; border-radius: 6px; white-space: nowrap; }
.sug-title { font-size: 16.5px; font-weight: 800; line-height: 1.5; }
.sug-line { display: flex; gap: 10px; margin-top: 11px; }
.sug-k { flex-shrink: 0; width: 46px; font-size: 14px; font-weight: 700; color: $color-text-muted; line-height: 1.8; }
.sug-v { flex: 1; font-size: 15.5px; line-height: 1.8; color: $color-text-secondary; }
.sug-line:nth-of-type(3) .sug-v { color: $color-text; }
.sug-go { align-self: flex-start; margin-top: 14px; display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border-radius: 999px; cursor: pointer; font-size: 14.5px; font-weight: 700;
  color: $color-primary; background: $color-primary-softer; border: 1px solid #d8e7fa; transition: all .18s ease; }
.sug-go:hover { background: $color-primary; border-color: $color-primary; color: #fff; }
.sug-go svg { transition: transform .18s ease; }
.sug-go:hover svg { transform: translateX(3px); }

.result-foot { display: flex; gap: 12px; }
.result-foot .tc-btn { display: inline-flex; align-items: center; gap: 6px; }
.result-foot .tc-btn.ghost { background: #fff; color: $color-primary; border: 1px solid $color-border; }
.err { color: #c0392b; font-size: 16px; }
</style>
