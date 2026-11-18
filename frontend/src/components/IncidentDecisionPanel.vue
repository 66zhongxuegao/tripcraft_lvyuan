<template>
  <section class="card inc-sec" data-testid="incidents">
    <div class="inc-h title-rule">
      <span>行中事件</span>
      <span class="inc-count"><b>{{ incidents.length }}</b> 起</span>
    </div>

    <div v-if="loadError" class="err-inline" data-testid="incident-error">
      <span class="err-msg">{{ loadError }}</span>
      <button class="tc-btn ghost sm" :disabled="loading" @click="loadTimeline">
        <SIcon name="refresh" :size="13" /> {{ loading ? '重试中…' : '重试' }}
      </button>
    </div>

    <div v-if="loading && !incidents.length" class="inc-empty">行中事件加载中…</div>
    <div v-else-if="!incidents.length" class="inc-empty">本单暂无行中事件</div>

    <div v-else class="inc-list">
      <article v-for="inc in incidents" :key="inc.incident_id" class="inc-item"
        :class="{ active: inc.incident_id === activeId }"
        :data-testid="`incident-${inc.incident_id}`">
        <button class="inc-head" type="button" :aria-expanded="inc.incident_id === activeId"
          @click="selectIncident(inc)">
          <span class="inc-title">{{ inc.title || inc.code || '行中事件' }}</span>
          <span v-if="inc.channel" class="inc-ch">{{ inc.channel }}</span>
          <span v-if="inc.step" class="inc-step">{{ inc.step }}</span>
          <span v-if="decisions[inc.incident_id]" class="inc-flag">已评审</span>
          <span class="inc-chev" :class="{ open: inc.incident_id === activeId }">
            <SIcon name="right" :size="13" />
          </span>
        </button>
        <div v-if="inc.body" class="inc-body">{{ inc.body }}</div>
        <div v-if="(inc.skill_points || []).length" class="inc-skills">
          <span v-for="sp in inc.skill_points" :key="sp" class="inc-sp">{{ sp }}</span>
        </div>

        <template v-if="inc.incident_id === activeId">
          <div class="plan">
            <textarea v-model="plan" class="plan-input" rows="3" :disabled="submitting"
              placeholder="写下处置方案：先安抚谁、怎么换、费用怎么摊、几点前给客户回话…"
              data-testid="incident-plan" />
            <div class="plan-foot">
              <button class="tc-btn" data-testid="incident-submit"
                :disabled="!plan.trim() || submitting" @click="submitDecision">
                <SIcon :name="submitting ? 'refresh' : 'users'" :size="14" />
                {{ submitting ? '评审中…' : '发起团队评审' }}
              </button>
              <span class="plan-hint">
                {{ submitting ? '5 个角色正在并行评审…' : '5 个角色并行评审，规则仲裁出最终裁定' }}
              </span>
            </div>
          </div>

          <div v-if="errorMsg" class="err-inline" data-testid="decision-error">
            <span class="err-msg">{{ errorMsg }}</span>
          </div>

          <div v-if="decision" class="dc" :class="verdictClass(decision.verdict)" data-testid="decision-card">
            <div class="dc-head">
              <span class="dc-badge" :class="verdictClass(decision.verdict)"
                data-testid="decision-verdict">{{ decision.verdict }}</span>
              <span class="dc-score">score {{ scoreText(decision) }}</span>
              <span v-if="decision.rules?.veto" class="dc-veto" data-testid="decision-veto">
                风控一票否决<template v-if="decision.rules?.veto_by">（{{ decision.rules.veto_by }}）</template>
              </span>
              <span v-else class="dc-noveto">无风控一票否决</span>
              <span v-if="parallelLabel(decision)" class="dc-batch" data-testid="decision-parallel">
                {{ parallelLabel(decision) }}
              </span>
            </div>

            <div class="dc-votes-wrap">
              <table class="dc-votes">
                <thead>
                  <tr>
                    <th style="width:132px">角色</th>
                    <th style="width:96px">立场</th>
                    <th style="width:62px" class="num">权重</th>
                    <th>理由</th>
                    <th style="width:190px">条件</th>
                    <th style="width:78px" class="num">耗时</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="v in decision.votes || []" :key="v.agent" :class="{ failed: !v.ok }">
                    <td class="v-role">
                      {{ v.role }}
                      <span v-if="!v.ok" class="v-fail">失败</span>
                    </td>
                    <td><span class="stance" :class="stanceClass(v.stance)">{{ v.stance }}</span></td>
                    <td class="num">{{ weightText(v.weight) }}</td>
                    <td class="why">{{ v.reason || '—' }}</td>
                    <td class="cond">{{ v.condition || '—' }}</td>
                    <td class="num ms">{{ v.ms }} ms</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-if="(decision.conditions || []).length" class="dc-conds" data-testid="decision-conditions">
              <div class="dc-conds-h">合并条件 · {{ (decision.conditions || []).length }} 条</div>
              <ul>
                <li v-for="(c, i) in decision.conditions" :key="i">{{ c }}</li>
              </ul>
            </div>

            <div class="dc-foot">
              <span>决策 <b class="mono">{{ decision.decision_id }}</b></span>
              <span v-if="decision.evidence_id">证据 <b class="mono">{{ decision.evidence_id }}</b></span>
            </div>
          </div>
        </template>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import SIcon from '@/components/SIcon.vue'
import client from '@/api/client'

interface Incident {
  incident_id: string
  code?: string
  title?: string
  step?: string
  channel?: string
  body?: string
  skill_points?: string[]
}

interface IncidentVote {
  agent: string
  role: string
  stance: string
  weight: number
  reason: string
  condition: string
  ok: boolean
  ms: number
}

interface TeamDecision {
  decision_id: string
  order_id?: string
  incident_id?: string
  verdict: string
  conditions?: string[]
  votes?: IncidentVote[]
  rules?: { veto?: boolean; veto_by?: string; score?: number }
  orchestra?: { run_id?: string; trace?: unknown[]; batches?: unknown[][]; parallel?: boolean }
  evidence_id?: string
}

const props = defineProps<{ orderId: string }>()

const incidents = ref<Incident[]>([])
const activeId = ref('')
const plan = ref('')
const decisions = ref<Record<string, TeamDecision>>({})
const loaded = ref<Record<string, boolean>>({})
const loading = ref(false)
const submitting = ref(false)
const loadError = ref('')
const errorMsg = ref('')

const decision = computed<TeamDecision | null>(() => decisions.value[activeId.value] || null)

function selectIncident(inc: Incident) {
  if (inc.incident_id !== activeId.value) {
    // 切换事件：先清空上一个事件的方案草稿与提示，再按事件回填已保存决策
    plan.value = ''
    errorMsg.value = ''
  }
  activeId.value = inc.incident_id
  if (!loaded.value[inc.incident_id]) loadDecision(inc.incident_id)
}

/** GET 命中口径：payload 自带 decision_id 才算已保存决策，`{"decision": null}` 视为未命中 */
async function loadDecision(incidentId: string) {
  const oid = props.orderId
  try {
    const r = await client.get(`/practice/orders/${oid}/incidents/${incidentId}/decision`)
    if (props.orderId !== oid) return
    const d = r.data as TeamDecision | null
    if (d && typeof d === 'object' && d.decision_id) {
      decisions.value = { ...decisions.value, [incidentId]: d }
    }
    loaded.value = { ...loaded.value, [incidentId]: true }
  } catch (e: any) {
    if (props.orderId !== oid) return
    if (incidentId === activeId.value) {
      errorMsg.value = e?.response?.data?.detail || '已保存决策读取失败，请重试'
    }
  }
}

async function loadTimeline() {
  const oid = props.orderId
  if (!oid) return
  loading.value = true
  loadError.value = ''
  errorMsg.value = ''
  incidents.value = []
  activeId.value = ''
  plan.value = ''
  decisions.value = {}
  loaded.value = {}
  try {
    const r = await client.get(`/practice/orders/${oid}/timeline`)
    if (props.orderId !== oid) return
    const list: Incident[] = Array.isArray(r.data?.incidents) ? r.data.incidents : []
    incidents.value = list
    if (!list.length) return
    // 进入页面时把每条事件已保存的决策回填出来，优先展开已评审的那条
    await Promise.all(list.map((inc) => loadDecision(inc.incident_id)))
    if (props.orderId !== oid) return
    const decided = list.find((inc) => decisions.value[inc.incident_id])
    selectIncident(decided || list[0])
  } catch (e: any) {
    if (props.orderId !== oid) return
    loadError.value = e?.response?.data?.detail
      || (e?.response ? '行中事件读取失败，请重试' : '行中事件加载失败，请检查网络后重试')
  } finally {
    if (props.orderId === oid) loading.value = false
  }
}

async function submitDecision() {
  const inc = incidents.value.find((i) => i.incident_id === activeId.value)
  const text = plan.value.trim()
  if (!inc || !text || submitting.value) return
  submitting.value = true
  errorMsg.value = ''
  try {
    const r = await client.post(
      `/practice/orders/${props.orderId}/incidents/${inc.incident_id}/decision`, { plan: text })
    const d = r.data as TeamDecision
    if (!d || !d.decision_id) throw new Error('团队评审未返回决策')
    decisions.value = { ...decisions.value, [inc.incident_id]: d }
    loaded.value = { ...loaded.value, [inc.incident_id]: true }
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail
      || (e?.response ? '团队评审失败，请重试' : '团队评审请求失败，请检查网络后重试')
  } finally {
    submitting.value = false
  }
}

function verdictClass(verdict?: string) {
  if (verdict === '接受') return 'accept'
  if (verdict === '有条件接受') return 'conditional'
  if (verdict === '驳回') return 'reject'
  return ''
}

function stanceClass(stance?: string) {
  if (stance === '接受') return 'accept'
  if (stance === '有条件接受') return 'conditional'
  if (stance === '不接受') return 'reject'
  return 'abstain'
}

function scoreText(d: TeamDecision) {
  const n = Number(d.rules?.score)
  return Number.isFinite(n) ? n.toFixed(2) : '—'
}

function weightText(w: number) {
  const n = Number(w)
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : '—'
}

/** 批次/并行标记：同批任务全部并行时明确写出 Agent 数量 */
function parallelLabel(d: TeamDecision) {
  const n = (d.votes || []).length
  const batches = (d.orchestra?.batches || []).length
  if (d.orchestra?.parallel) {
    return `${n} 个 Agent 并行评审${batches > 1 ? ` · ${batches} 批` : ''}`
  }
  if (batches > 0) return `${n} 个 Agent · ${batches} 批评审`
  return ''
}

onMounted(loadTimeline)
watch(() => props.orderId, () => loadTimeline())
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.inc-sec { padding: 16px 18px; }
.inc-h { display: flex; align-items: center; gap: 8px; font-size: 19px; font-weight: 800; margin-bottom: 12px; }
.inc-count { margin-left: auto; font-size: 14px; font-weight: 500; color: $color-text-secondary; }
.inc-count b { font-size: 16px; font-weight: 800; color: $color-primary; }
.inc-empty { font-size: 15px; color: $color-text-muted; }

.err-inline { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  background: #fdf1f0; border-radius: 8px; padding: 9px 12px; margin: 10px 0; }
.err-msg { font-size: 15.5px; color: $color-danger; }
.tc-btn.sm { min-height: 32px; padding: 5px 12px; font-size: 14px; }

.inc-list { display: flex; flex-direction: column; gap: 10px; }
.inc-item { border: 1px solid $color-border; border-radius: $radius-md; padding: 12px 14px; background: #fff;
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }
.inc-item.active { border-color: $color-primary; background: linear-gradient(180deg, #f7fbff, #fff);
  box-shadow: 0 6px 18px rgba(37,119,227,0.10); }
.inc-head { display: flex; align-items: baseline; gap: 9px; width: 100%; padding: 0; border: 0;
  background: none; font-family: inherit; text-align: left; cursor: pointer; }
.inc-title { font-size: 16px; font-weight: 700; }
.inc-ch { font-size: 13px; color: $color-primary; background: $color-primary-soft;
  border-radius: 999px; padding: 1px 9px; }
.inc-step { font-size: 13px; color: $color-text-muted; }
.inc-flag { margin-left: auto; font-size: 12px; font-weight: 600; color: $color-success;
  background: #e8f7ee; border-radius: 999px; padding: 2px 8px; white-space: nowrap; }
.inc-chev { display: inline-flex; margin-left: 8px; color: $color-text-muted; transition: transform .16s ease; }
.inc-chev.open { transform: rotate(90deg); }
.inc-body { margin-top: 8px; font-size: 15px; line-height: 1.6; color: $color-text-secondary; }
.inc-skills { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.inc-sp { font-size: 12px; color: $color-text-muted; background: #f2f4f7; border-radius: 4px; padding: 1px 7px; }

.plan { margin-top: 12px; }
.plan-input { width: 100%; resize: vertical; min-height: 78px; border: 1px solid $color-border-strong;
  border-radius: $radius-md; padding: 10px 12px; font-family: inherit; font-size: 15px; line-height: 1.6;
  color: $color-text; background: #fff; }
.plan-input:focus { outline: none; border-color: $color-primary; box-shadow: 0 0 0 3px rgba(37,119,227,0.12); }
.plan-input:disabled { background: #fafbfc; color: $color-text-muted; }
.plan-foot { margin-top: 8px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.plan-hint { font-size: 14px; color: $color-text-muted; }

.dc { margin-top: 14px; border: 1px solid $color-border; border-radius: $radius-md; overflow: hidden; }
.dc.accept { border-color: #bfe6cf; }
.dc.conditional { border-color: #f2d7a8; }
.dc.reject { border-color: #f3c9c4; }
.dc-head { display: flex; align-items: center; gap: 8px; padding: 10px 12px; background: #fafbfc;
  border-bottom: 1px solid $color-border; flex-wrap: wrap; }
.dc-badge { font-size: 14px; font-weight: 700; border-radius: 6px; padding: 3px 10px; }
.dc-badge.accept { background: #e8f7ee; color: $color-success; }
.dc-badge.conditional { background: #fdf3e6; color: $color-warning; }
.dc-badge.reject { background: #fdeceb; color: $color-danger; }
.dc-score { font-size: 15px; font-weight: 700; }
.dc-veto { font-size: 14px; font-weight: 600; color: $color-danger; background: #fdeceb;
  border-radius: 4px; padding: 2px 8px; }
.dc-noveto { font-size: 14px; color: $color-text-muted; }
.dc-batch { margin-left: auto; font-size: 13px; color: $color-primary; background: $color-primary-soft;
  border-radius: 999px; padding: 2px 10px; white-space: nowrap; }

.dc-votes-wrap { overflow-x: auto; }
.dc-votes { width: 100%; border-collapse: collapse; font-size: 15px; }
.dc-votes th { text-align: left; font-weight: 600; color: $color-text-secondary; font-size: 14px;
  padding: 8px 10px; border-bottom: 1px solid $color-border; background: #fff; }
.dc-votes td { padding: 9px 10px; border-bottom: 1px solid #f1f3f5; vertical-align: top; }
.dc-votes tr:last-child td { border-bottom: none; }
.dc-votes .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.v-role { font-weight: 600; }
.v-fail { font-size: 12px; font-weight: 600; color: $color-danger; background: #fdeceb;
  border-radius: 4px; padding: 1px 6px; margin-left: 6px; white-space: nowrap; }
.stance { font-size: 13px; border-radius: 4px; padding: 2px 8px; white-space: nowrap;
  background: #f2f4f7; color: $color-text-secondary; }
.stance.accept { background: #e8f7ee; color: $color-success; }
.stance.conditional { background: #fdf3e6; color: $color-warning; }
.stance.reject { background: #fdeceb; color: $color-danger; }
.stance.abstain { background: #f2f4f7; color: $color-text-muted; }
.why { color: $color-text-secondary; line-height: 1.55; }
.cond { color: $color-warning; line-height: 1.55; }
.ms { color: $color-text-muted; }
tr.failed .why { color: $color-danger; }

.dc-conds { padding: 10px 12px; border-top: 1px solid #f1f3f5; background: #fffdf8; }
.dc-conds-h { font-size: 14px; font-weight: 700; color: $color-warning; margin-bottom: 6px; }
.dc-conds ul { margin: 0; padding-left: 18px; }
.dc-conds li { font-size: 15px; line-height: 1.7; color: $color-text-secondary; }
.dc-foot { display: flex; gap: 14px; flex-wrap: wrap; padding: 8px 12px; border-top: 1px solid #f1f3f5;
  font-size: 13px; color: $color-text-muted; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
</style>
