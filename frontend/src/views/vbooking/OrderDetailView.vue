<template>
  <div class="vb">
    <div class="vb-crumb">
      <span class="lnk" @click="router.push('/practice')">订单管理</span> &gt; 订单详情 &gt;
      <span class="mono">{{ orderId }}</span>
    </div>

    <div class="vb-body">
      <!-- 左主区 -->
      <section class="main-col">
        <div class="card head">
          <div class="head-left">
            <div class="row"><span class="k">提交时间</span><span class="v mono">{{ order?.created_at || '—' }}</span></div>
            <div class="row"><span class="k">需求单号</span><span class="v mono red">{{ orderId }}</span></div>
            <div class="row"><span class="k">客户</span><span class="v">{{ order?.customer || '客户' }}（{{ order?.destination || '—' }}）</span></div>
            <div class="row"><span class="k">客源地</span><span class="v">{{ order?.source_market || '—' }}<span class="src-tag">入境接待</span></span></div>
          </div>
          <div class="head-right">
            <button class="tc-btn head-cta" @click="openWorkbench()">
              <SIcon name="filetext" :size="15" /> 产出与投递
            </button>
          </div>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>客户通话</span></div>
          <div class="call-row">
            <div class="call-info">
              <div class="ci-name">{{ order?.customer || '客户' }}</div>
              <div class="ci-hint">接通后按流程完成需求挖掘</div>
            </div>
            <button class="tc-btn call-btn" @click="startCall()"><SIcon name="mic" :size="14" /> 拨打电话</button>
          </div>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>基础信息</span></div>
          <div class="grid2">
            <div class="row"><span class="k">服务语言</span><span class="v">{{ order?.language || '中文' }}</span></div>
            <div class="row"><span class="k">商家服务人员</span><span class="v">定制师 · {{ user.consultantName }}<template v-if="user.companyName"> · {{ user.companyName }}</template></span></div>
          </div>
          <div class="row mt"><span class="k">入境证件</span><span class="v">{{ order?.documents || '—' }}</span></div>
          <div class="row mt"><span class="k">用户信息备注</span>
            <span class="v muted">客户希望行程轻松，带一位老人；预算偏紧【可编辑】</span></div>
        </div>

        <div v-if="order?.dispatch" class="card tl">
          <template v-if="!order.dispatch.claimed && !order.dispatch.lost">
            <Countdown :until="order.dispatch.window_end" prefix="抢单窗口剩" />
            <span class="tl-note">{{ order.dispatch.rivals }} 位定制师同时在抢，最快的一位约 {{ order.dispatch.rival_eta_min }} 分钟后会接走</span>
          </template>
          <template v-else-if="order.dispatch.first_call">
            <Countdown :until="order.dispatch.first_call.due_at" prefix="首呼时限剩" />
            <Countdown :until="order.dispatch.plan.due_at" prefix="方案时限剩" />
          </template>
          <span v-if="order.dispatch.lost" class="tl-lost">{{ order.dispatch.lost_reason }}</span>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>方案信息</span></div>
          <div v-if="!plans.length" class="plan-empty">
            <span class="chip">方案未创建</span>
            <span class="plan-hint">暂未创建方案，尽快创建并发送给客户，成团机会更大。</span>
            <button class="tc-btn" @click="createPlan">创建方案</button>
          </div>
          <div v-else class="plan-list">
            <div v-for="p in plans" :key="p.plan_id" class="plan-row">
              <span class="p-ver">V{{ p.version }}</span>
              <div class="p-mid">
                <span class="p-title">{{ p.title || ('方案 V' + p.version) }}</span>
                <span class="p-meta">
                  {{ p.status }}
                  <template v-if="p.sent_at">· 发送 {{ p.sent_at.slice(5, 16) }}</template>
                  <template v-if="p.read_at">· 客户已读 {{ p.read_at.slice(5, 16) }}</template>
                </span>
                <span v-if="p.feedback" class="p-fb">客户反馈：{{ p.feedback }}</span>
              </div>
              <span class="p-tag" :class="planClass(p)">{{ p.status }}</span>
              <button v-if="p.status === '草稿'" class="tc-btn ghost p-btn"
                @click="router.push(`/practice/orders/${orderId}/plan/new?plan=${p.plan_id}`)">继续编辑</button>
              <button v-else class="tc-btn ghost p-btn"
                @click="router.push(`/practice/orders/${orderId}/plan/new?plan=${p.plan_id}`)">查看</button>
            </div>
            <div class="plan-foot">
              <button class="tc-btn" @click="createPlan">创建新版本</button>
              <span v-if="unreadPlans" class="plan-warn">
                还有 {{ unreadPlans }} 个方案客户未阅读，可到聊天界面提醒客户
              </span>
            </div>
          </div>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule">
            <span>产出与投递</span>
            <span class="dw-stat"><b>{{ deliveredCount }}</b> / {{ deliverables.length }} 份已投递</span>
          </div>
          <div class="dw-docs">
            <button v-for="d in deliverables" :key="d.code" class="dw-doc" :class="{ done: d.submitted }"
              @click="openWorkbench(d.code)">
              <span class="dd-ic"><SIcon :name="d.submitted ? 'check' : 'filetext'" :size="13" /></span>
              <span class="dd-mid">
                <span class="dd-name">{{ d.title }}</span>
                <span class="dd-meta">{{ d.step }} · {{ d.audience.join('、') }}</span>
              </span>
              <span class="dd-tag">{{ d.submitted ? 'V' + d.version + ' 已投递' : '未填写' }}</span>
            </button>
          </div>
          <div class="dw-foot">
            <span class="dw-tip">填完提交即投递：发给客户 / 地接 / 司导的会进对应群聊，内部台账只留档。</span>
            <button class="tc-btn" @click="openWorkbench()">
              <SIcon name="right" :size="14" /> 进入产出与投递
            </button>
          </div>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>订单跟进信息</span></div>
          <div class="alert">
            合规要求：按照员工所属企业合规要求，目的地不支持国际、中国香港、中国台湾、中国澳门。
          </div>
          <div class="guide">
            客人还未阅读过任何方案，还有机会争取到用户，可需尽快发送方案吸引用户。
          </div>
          <div class="note-row">
            <button class="tc-btn ghost">添加跟进备注</button>
            <span class="note-tip">请严格遵循流程规则进行报备，<span class="lnk">查看备注规则</span></span>
          </div>
          <div v-if="order?.dispatch?.plan" class="pause">
            方案最晚发送时间：
            <Countdown :until="order.dispatch.plan.due_at" prefix="剩" />
          </div>

          <div class="sub-title">客户联系记录</div>
          <table class="tbl">
            <thead><tr><th style="width:220px">联系时间</th><th style="width:140px">状态</th><th>记录</th><th style="width:70px">录音</th></tr></thead>
            <tbody>
              <tr v-for="r in contacts" :key="r.time">
                <td class="mono">{{ r.time }}</td>
                <td><span class="tag" :class="r.status.includes('已接通') || r.status.includes('已添加') ? 'ok' : 'bad'">{{ r.status }}</span></td>
                <td>{{ r.detail || '—' }}</td>
                <td><span v-if="r.has_record" class="lnk">录音</span><span v-else class="muted">—</span></td>
              </tr>
              <tr v-if="!contacts.length"><td colspan="4" class="muted">暂无联系记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 右侧栏 -->
      <aside class="side-col">
        <div class="card sec">
          <div class="sec-title title-rule"><span>订单状态</span></div>
          <div class="timeline">
            <div v-for="(s, i) in steps" :key="s.label" class="step" :class="s.state">
              <div class="dot-col">
                <span class="dot" />
                <span v-if="i < steps.length - 1" class="line" />
              </div>
              <div class="step-body">
                <div class="step-label">{{ s.label }}
                  <span v-if="s.urgent" class="urgent">需处理</span>
                </div>
                <div v-if="s.deadline_at" class="step-note">
                  <Countdown :until="s.deadline_at" prefix="剩" />
                </div>
                <div v-else-if="s.note" class="step-note red">{{ s.note }}</div>
              </div>
            </div>
          </div>
          <button class="tc-btn ghost full">取消订单</button>
        </div>

        <div class="card sec">
          <div class="sec-title title-rule"><span>信息</span></div>
          <div class="info-row"><span class="k">是否真需求单</span><span class="v muted">未判断</span></div>
          <div class="info-note">请及时添加跟进备注完成是否真需求单的判断</div>
          <div class="info-row"><span class="k">是否添加企微</span><span class="v muted">否</span></div>
          <div class="info-row"><span class="k">是否建立售前微信群</span><span class="v muted">否</span></div>
          <div class="lnk">点击查看建群流程和相关话术</div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import Countdown from '@/components/Countdown.vue'
import client from '@/api/client'

const HINTS = [
  '尽快首呼，挖清人数/日期/预算口径（1 小时内）',
  '创建并发送方案（4 小时内）',
  '跟进客户确认方案',
  '准备并发送合同',
  '跟进客户确认合同',
  '行前准备：锁定资源、发出团通知',
  '核对地接结算单，提交结算',
  '回访客户，记录利润与复盘',
]
import { useUserStore } from '@/stores/user'
import { usePracticeStore } from '@/stores/practice'

const route = useRoute()
const router = useRouter()
const orderId = computed(() => String(route.params.id || ''))
const user = useUserStore()
const practice = usePracticeStore()
practice.setActiveOrder(String(route.params.id || ''))
const order = ref<any>(null)
const rawSteps = ref<any[]>([])
const steps = computed(() => rawSteps.value)

const contacts = computed<any[]>(() => order.value?.contacts || [])
const gate = ref<any>(null)
const plans = ref<any[]>([])
const deliverables = ref<any[]>([])
const deliveredCount = computed(() => deliverables.value.filter((d) => d.submitted).length)
const unreadPlans = computed(() => plans.value.filter((p) => p.status === '已发送' && !p.read).length)

function planClass(p: any) {
  if (p.status === '客户已确认') return 'ok'
  if (p.status === '已读') return 'read'
  if (p.status === '已发送') return 'sent'
  return 'draft'
}

async function loadPlans() {
  try { plans.value = (await client.get(`/practice/orders/${orderId.value}/plans`)).data.plans || [] }
  catch { plans.value = [] }
}

async function loadDeliverables() {
  try {
    deliverables.value = (await client.get(`/practice/orders/${orderId.value}/deliverables`)).data.deliverables || []
  } catch { deliverables.value = [] }
}

/** 统一入口：不传 code 就自动落到第一份没填的交付物，省一步选择 */
function openWorkbench(code = '') {
  const target = code || (deliverables.value.find((d) => !d.submitted) || {}).code || ''
  router.push(`/practice/orders/${orderId.value}/deliverables${target ? '?code=' + target : ''}`)
}

async function loadGate() {
  try { gate.value = (await client.get(`/practice/orders/${orderId.value}/gates`)).data } catch {}
  await loadPlans()
}

const DOC_MAP: Record<string, string> = {
  'deliverable:需求确认单': 'requirement_sheet',
  'deliverable:行程方案': 'itinerary',
  'deliverable:分项报价': 'quotation',
  'guard_pass:分项报价': 'quotation',
  'deliverable:合同与保险': 'contract',
  'deliverable:出团通知书': 'departure_notice',
  'deliverable:地接结算核对单': 'settlement',
  'deliverable:回访与复盘记录': 'review',
}
function docCode(action: string) { return DOC_MAP[action] || '' }
function openDoc(action: string) {
  router.push(`/practice/orders/${orderId.value}/deliverables?code=${docCode(action)}`)
}

async function doAction(action: string) {
  try {
    await client.post(`/practice/orders/${orderId.value}/actions`, { action })
    await Promise.all([load(), loadGate()])
  } catch (e: any) {
    alert(e?.response?.data?.detail || '操作失败')
  }
}

async function load() {
  const id = orderId.value
  try {
    const o = await client.get(`/practice/orders/${id}`)
    order.value = o.data
    rawSteps.value = (o.data.steps || []).map((s: any) => ({
      label: s.label, state: s.state, note: s.note || undefined, urgent: !!s.urgent,
    }))
    loadGate()
    loadDeliverables()
  } catch { order.value = null }
}

function startCall() { router.push(`/practice/orders/${orderId.value}/call`) }

function createPlan() { router.push(`/practice/orders/${orderId.value}/plan/new`) }

onMounted(load)
// 同一个组件实例在不同订单之间复用时，必须重新拉数据（hash 路由不会重建组件）
watch(orderId, () => {
  practice.setActiveOrder(orderId.value)
  order.value = null
  gate.value = null
  rawSteps.value = []
  deliverables.value = []
  load()
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.vb { width: 100%; max-width: 1240px; margin: 0 auto; }
.vb-crumb { font-size: 15.5px; color: $color-text-muted; margin-bottom: 12px; }
.vb-body { display: flex; gap: 14px; align-items: flex-start; }
.main-col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.side-col { width: 290px; flex-shrink: 0; display: flex; flex-direction: column; gap: 12px; }

.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.head { display: flex; justify-content: space-between; align-items: flex-start; padding: 16px 18px; }
.head-right { display: flex; gap: 10px; }
.sec { padding: 16px 18px; }
.sec-title { font-size: 19px; font-weight: 800; margin-bottom: 12px; }

.row { display: flex; align-items: baseline; gap: 10px; margin-bottom: 7px; font-size: 15px; }
.row.mt { margin-top: 4px; }
.k { color: $color-text-muted; width: 88px; flex-shrink: 0; }
.v { color: $color-text; }
.muted { color: $color-text-secondary; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 15.5px; }
.red { color: #e04b4b; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 20px; }
.src-tag { margin-left: 8px; font-size: 14.5px; background: #efe9fe; color: #7a5af8; border-radius: 4px; padding: 1px 7px; }

.gate { display: flex; flex-direction: column; gap: 4px; }
.g-top { display: flex; align-items: baseline; gap: 10px; }
.g-stage { font-size: 15.5px; font-weight: 800; }
.g-count { font-size: 15.5px; color: $color-primary; background: $color-primary-soft; border-radius: 999px; padding: 2px 10px; }
.g-hint { font-size: 15.5px; color: $color-text-secondary; margin-bottom: 4px; }
.g-row { display: flex; align-items: center; gap: 9px; font-size: 15px; padding: 6px 0; border-bottom: 1px dashed #f1f3f5; }
.g-row:last-of-type { border-bottom: none; }
.gk { width: 8px; height: 8px; border-radius: 50%; background: #d5dce5; flex-shrink: 0; }
.g-row.ok .gk { background: #12a76a; }
.gl { font-weight: 600; color: $color-text-secondary; flex-shrink: 0; }
.g-row.ok .gl { color: $color-text; }
.gr { flex: 1; font-size: 15.5px; color: $color-text-muted; }
.g-btn { padding: 3px 12px; font-size: 15.5px; flex-shrink: 0; }
.g-next { margin-top: 6px; font-size: 15.5px; color: $color-primary; }
.g-link { margin-top: 5px; font-size: 15.5px; color: $color-primary; cursor: pointer; }
.g-link:hover { text-decoration: underline; }
.tl { display: flex; align-items: center; gap: 10px; padding: 11px 18px; flex-wrap: wrap; }
.tl-note { font-size: 15.5px; color: $color-text-muted; }
.tl-lost { font-size: 15.5px; color: #c0392b; }

.plan-empty { display: flex; align-items: center; gap: 14px; background: $color-primary-softer; border: 1px dashed $color-border-strong; border-radius: $radius-md; padding: 18px; }
.chip { background: $color-primary-soft; color: $color-primary; font-size: 15.5px; padding: 3px 10px; border-radius: 4px; }
.plan-hint { flex: 1; font-size: 15px; color: $color-text-secondary; }
.plan-list { display: flex; flex-direction: column; gap: 10px; }
.plan-row { display: flex; align-items: flex-start; gap: 12px; border: 1px solid $color-border; border-radius: $radius-md; padding: 12px 14px; }
.p-ver { font-size: 15.5px; font-weight: 800; color: $color-primary; background: $color-primary-soft; border-radius: 5px; padding: 3px 8px; }
.p-mid { flex: 1; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.p-title { font-size: 15.5px; font-weight: 700; }
.p-meta { font-size: 15px; color: $color-text-muted; }
.p-fb { font-size: 15.5px; color: $color-text-secondary; }
.p-tag { font-size: 15px; border-radius: 4px; padding: 2px 8px; }
.p-tag.draft { background: #f1f4f8; color: $color-text-secondary; }
.p-tag.sent { background: #fdf3e6; color: $color-warning; }
.p-tag.read { background: $color-primary-soft; color: $color-primary; }
.p-tag.ok { background: #e8f7ee; color: $color-success; }
.p-btn { flex-shrink: 0; }
.plan-foot { display: flex; align-items: center; gap: 12px; }
.plan-warn { font-size: 15.5px; color: $color-warning; }

.alert { background: #fdeceb; color: #c0392b; font-size: 15.5px; padding: 9px 12px; border-radius: 6px; margin-bottom: 10px; }
.guide { background: $color-primary-softer; color: $color-text-secondary; font-size: 15.5px; padding: 9px 12px; border-radius: 6px; margin-bottom: 12px; }
.note-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.note-tip { font-size: 15.5px; color: $color-text-muted; }
.pause { font-size: 15.5px; color: $color-text-secondary; margin-bottom: 14px; }
.sub-title { font-size: 17px; font-weight: 700; margin-bottom: 8px; }

.tbl { width: 100%; border-collapse: collapse; font-size: 15.5px; }
.tbl th { background: #fafbfc; text-align: left; padding: 9px 12px; color: $color-text-secondary; font-weight: 600; border-bottom: 1px solid $color-border; }
.tbl td { padding: 10px 12px; border-bottom: 1px solid #f1f3f5; }
.tag { display: inline-block; padding: 2px 9px; border-radius: 4px; font-size: 15.5px; }
.tag.ok { background: #e8f7ee; color: #12a76a; }
.tag.bad { background: #fdeceb; color: #e04b4b; }
.lnk { color: $color-primary; cursor: pointer; font-size: 15.5px; }
.lnk:hover { text-decoration: underline; }

.timeline { margin-bottom: 14px; }
.step { display: flex; gap: 10px; }
.dot-col { display: flex; flex-direction: column; align-items: center; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: #cfd6de; margin-top: 3px; }
.line { width: 1px; flex: 1; background: #e3e7ec; min-height: 22px; }
.step.done .dot { background: #12a76a; }
.step.current .dot { background: #e04b4b; box-shadow: 0 0 0 3px rgba(224,75,75,0.16); }
.step-body { padding-bottom: 12px; }
.step-label { font-size: 15px; color: $color-text-secondary; display: flex; align-items: center; gap: 8px; }
.step.done .step-label { color: $color-text; }
.step.current .step-label { color: $color-text; font-weight: 700; }
.step-note { font-size: 15.5px; margin-top: 3px; }
.urgent { font-size: 14.5px; background: #e04b4b; color: #fff; border-radius: 8px; padding: 1px 7px; }
.full { width: 100%; justify-content: center; }

.sec-title { display: flex; align-items: center; gap: 8px; }
.head-cta { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
.dw-stat { margin-left: auto; font-size: 14px; font-weight: 500; color: $color-text-secondary; }
.dw-stat b { font-size: 16px; font-weight: 800; color: $color-primary; }
.dw-docs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.dw-doc { display: flex; align-items: center; gap: 11px; text-align: left; padding: 12px 14px; cursor: pointer;
  border: 1px solid $color-border; border-radius: $radius-md; background: #fff;
  transition: border-color .16s ease, box-shadow .16s ease, transform .16s cubic-bezier(.34,1.4,.6,1); }
.dw-doc:hover { border-color: $color-primary; transform: translateY(-1px); box-shadow: 0 6px 18px rgba(37,119,227,0.12); }
.dw-doc.done { background: #f6fbf8; border-color: #e2f1e8; }
.dw-doc.done:hover { border-color: #12a76a; box-shadow: 0 6px 18px rgba(18,167,106,0.12); }
.dd-ic { width: 26px; height: 26px; flex-shrink: 0; border-radius: 8px; display: flex; align-items: center;
  justify-content: center; background: $color-primary-soft; color: $color-primary; }
.dw-doc.done .dd-ic { background: #e5f7ee; color: #12a76a; }
.dd-mid { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.dd-name { font-size: 15.5px; font-weight: 600; }
.dd-meta { font-size: 13.5px; color: $color-text-muted; }
.dd-tag { font-size: 13px; color: $color-text-muted; white-space: nowrap; }
.dw-doc.done .dd-tag { color: #12a76a; font-weight: 700; }
.dw-foot { margin-top: 14px; display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.dw-tip { font-size: 14px; line-height: 1.6; color: $color-text-muted; }
.dw-foot .tc-btn { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.call-row { display: flex; align-items: center; gap: 14px; }
.call-info { flex: 1; }
.ci-name { font-size: 19px; font-weight: 800; }
.ci-hint { margin-top: 3px; font-size: 15.5px; color: $color-text-muted; }
.call-btn { padding: 8px 18px; }

.info-row { display: flex; justify-content: space-between; font-size: 15.5px; margin-bottom: 8px; }
.info-note { font-size: 15.5px; color: $color-text-muted; background: $color-primary-softer; padding: 8px 10px; border-radius: 6px; margin-bottom: 10px; }
</style>