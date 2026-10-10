<template>
  <div class="dw">
    <div class="dw-head">
      <button class="back" @click="router.push(`/practice/orders/${orderId}`)">
        <SIcon name="back" :size="13" /> 返回订单
      </button>
      <span class="dw-title">产出与投递</span>
      <span class="dw-oid">{{ orderId }}</span>
      <span v-if="order" class="dw-cust">{{ order.customer }} · {{ order.source_market }} · {{ order.destination }}</span>
      <span class="dw-stage">{{ order?.stage_name }}</span>
    </div>

    <div class="dw-body">
      <!-- 交付物切换：横向标签带，把横向空间留给表单与预览 -->
      <nav class="card dw-tabs">
        <div v-for="grp in grouped" :key="grp.key" class="tab-grp">
          <span class="tg-label" :title="grp.hint">{{ grp.label }}</span>
          <button v-for="d in grp.items" :key="d.code" class="tab"
            :class="{ on: d.code === activeCode, done: d.submitted }" @click="open(d.code)"
            :title="`${d.step} · 发给${d.audience.join('、')} · ${d.purpose || ''}`">
            <SIcon :name="d.submitted ? 'check' : 'filetext'" :size="13" />
            <span class="tb-name">{{ d.title }}</span>
            <i v-if="d.submitted" class="tb-v">V{{ d.version }}</i>
          </button>
        </div>
      </nav>

      <!-- 右：填表 + 预览 -->
      <section class="dw-main">
        <div v-if="!spec" class="card empty">左侧选一个交付物开始填写</div>
        <template v-else>
          <div class="card f-head">
            <div class="fh-l">
              <span class="fh-title">{{ spec.title }}</span>
              <span class="fh-step">{{ spec.step }}</span>
              <span class="fh-surface">{{ SURFACE_LABEL[spec.surface] || '文档' }}</span>
              <span v-for="a in spec.audience" :key="a" class="fh-aud" :class="audClass(a)">{{ a }}</span>
            </div>
            <div class="fh-r">
              <span v-if="savedVersion" class="fh-ver"><SIcon name="check" :size="13" /> 已投递 V{{ savedVersion }}</span>
              <div class="exp-group">
                <button class="exp" :disabled="pdfBusy" @click="exportPdf">
                  <SIcon name="download" :size="15" />
                  <span class="ex-t">导出 <i class="ex-fmt">PDF</i></span>
                </button>
                <button class="exp" @click="exportFile">
                  <SIcon name="download" :size="15" />
                  <span class="ex-t">导出 <i class="ex-fmt">Markdown</i></span>
                </button>
              </div>
              <button class="tc-btn submit-btn" :disabled="busy" @click="submit">
                <SIcon name="check" :size="16" /> {{ busy ? '投递中…' : '提交并投递' }}
              </button>
            </div>
          </div>
          <div class="fh-purpose">{{ spec.purpose }}</div>

          <div class="dw-cols">
            <div class="card form">
              <div v-for="f in spec.fields" :key="f.key" class="fld">
                <label class="lb">{{ f.label }}<i v-if="f.required" class="req">*</i>
                  <span v-if="f.help" class="help">{{ f.help }}</span></label>

                <input v-if="f.type === 'text'" v-model="values[f.key]" class="inp" :placeholder="f.placeholder" />
                <input v-else-if="f.type === 'number'" v-model="values[f.key]" type="number" class="inp"
                  :placeholder="f.placeholder" />
                <input v-else-if="f.type === 'date'" v-model="values[f.key]" type="date" class="inp" />
                <select v-else-if="f.type === 'select'" v-model="values[f.key]" class="inp">
                  <option value="">请选择</option>
                  <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
                </select>
                <textarea v-else-if="f.type === 'textarea'" v-model="values[f.key]" class="ta" rows="3"
                  :placeholder="f.placeholder" />

                <div v-else-if="f.type === 'rows'" class="rows">
                  <table class="rt">
                    <thead><tr><th v-for="c in f.columns" :key="c.key">{{ c.label }}</th><th class="rop"></th></tr></thead>
                    <tbody>
                      <tr v-for="(r, i) in rowsOf(f.key)" :key="i">
                        <td v-for="c in f.columns" :key="c.key">
                          <input v-model="r[c.key]" class="rin" />
                        </td>
                        <td class="rop"><button class="rm" @click="removeRow(f.key, i)">×</button></td>
                      </tr>
                    </tbody>
                  </table>
                  <button class="btn ghost add" @click="addRow(f)">+ 添加一行</button>
                </div>

                <div v-else-if="f.type === 'file'" class="file">
                  <input type="file" @change="onFile($event, f.key)" />
                  <span v-if="files[f.key]" class="fname">{{ files[f.key].filename }}</span>
                </div>
              </div>
            </div>

            <div class="card preview">
              <div class="pv-head">
                <SIcon name="filetext" :size="15" />
                <span class="pv-title">文档预览</span>
                <span class="pv-name">{{ spec.filename }}</span>
                <span v-if="missing.length" class="pv-miss">缺 {{ missing.length }} 项必填</span>
              </div>
              <div class="pv-paper"><MarkdownView :text="preview" /></div>
            </div>
          </div>

          <div class="card send-row">
            <span class="sr-ic"><SIcon name="users" :size="15" /></span>
            <span class="sr-k">发送对象</span>
            <span class="sr-v">{{ sendSummary }}</span>
            <button v-if="needPicker" class="tc-btn ghost sr-edit" @click="sendModal = true">
              <SIcon name="users" :size="14" /> 选择接收人
            </button>
          </div>

          <div v-if="result" class="card result" :class="result.blocked ? 'bad' : 'ok'">
            <div class="r-head">
              <span class="r-tag">{{ result.blocked ? '被拦截' : '已投递' }}</span>
              <span v-if="!result.blocked" class="r-sent">
                发送对象：{{ (result.routing?.targets || []).map((t: any) => t.name).join('、')
                  || (result.routing?.sent_to || []).join('、') || '内部留存' }}
              </span>
              <span v-if="result.version" class="r-ver">版本 V{{ result.version }}</span>
            </div>
            <template v-if="result.blocked">
              <div class="r-why">交付物未通过校验，未投递给客户：</div>
              <div v-for="(x, i) in result.guard?.reasons || []" :key="i" class="r-line">× {{ x }}</div>
            </template>
            <template v-else>
              <div v-for="(x, i) in guardChecks" :key="i" class="r-line">
                <i class="dot" :class="x.ok ? 'ok' : 'warn'" />{{ x.name }}{{ x.detail ? '：' + x.detail : '' }}
              </div>
              <div v-for="(x, i) in result.guard?.semantic?.issues || []" :key="'s' + i" class="r-line">
                <i class="dot warn" />语义合规［{{ x.severity }}］{{ x.why }}
              </div>
              <div v-if="result.routing?.customer_reply" class="r-reply">
                <span class="r-who">客户反馈</span>{{ result.routing.customer_reply }}
                <div v-for="(a, i) in result.routing.asks || []" :key="i" class="r-ask">客户追问：{{ a }}</div>
              </div>
              <div v-if="result.routing?.platform_note" class="r-line">平台：{{ result.routing.platform_note }}</div>
              <div v-if="result.routing?.im_session" class="r-line">已同步到聊天界面「地接资源信息群」</div>
              <div v-if="result.gates" class="r-gate">
                当前门槛 {{ result.gates.done }}/{{ result.gates.total }} · {{ result.gates.stage_name }}
                <span v-if="result.gates.next" class="r-next">下一步：{{ result.gates.next.hint }}</span>
              </div>
            </template>
          </div>
        </template>
      </section>
    </div>

    <!-- 选择接收人：向聊天界面的会话列表靠齐 -->
    <transition name="pop">
      <div v-if="sendModal" class="modal-mask" @click.self="sendModal = false">
        <div class="modal">
          <div class="md-head">
            <span class="md-title">选择接收人</span>
            <span class="md-sub">{{ spec?.title }} · 勾选后提交即投递</span>
            <button class="md-x" @click="sendModal = false"><SIcon name="x" :size="16" /></button>
          </div>
          <div class="md-body">
            <button v-for="t in targetOptions" :key="t.session_id" class="pick"
              :class="{ on: pickedTargets.includes(t.session_id) }" @click="toggleTarget(t.session_id)">
              <span class="pk-av" :class="{ on: pickedTargets.includes(t.session_id) }">{{ (t.name || '?').slice(0, 1) }}</span>
              <span class="pk-mid">
                <span class="pk-name">{{ t.name }}</span>
                <span class="pk-hint">{{ t.hint }}</span>
              </span>
              <span class="pk-kind">{{ t.kind }}</span>
              <span class="pk-check"><SIcon name="check" :size="13" /></span>
            </button>
            <div v-if="!targetOptions.length" class="md-empty">
              暂无可投递的会话，请先到聊天界面添加客户或地接的联系方式
            </div>
          </div>
          <div class="md-foot">
            <span class="md-count">已选 {{ pickedTargets.length }} 个会话</span>
            <button class="tc-btn ghost" @click="sendModal = false">取消</button>
            <button class="tc-btn" @click="sendModal = false">确认</button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import client from '@/api/client'

const route = useRoute()
const router = useRouter()
const orderId = computed(() => String(route.params.id || ''))
const list = ref<any[]>([])
const spec = ref<any>(null)
const activeCode = ref('')
const values = ref<Record<string, any>>({})
const fileIds = ref<Record<string, string>>({})
const files = ref<Record<string, any>>({})
const preview = ref('')
const missing = ref<string[]>([])
const result = ref<any>(null)
const busy = ref(false)
const order = ref<any>(null)
const savedVersion = ref(0)
const sendModal = ref(false)
const pdfBusy = ref(false)

const SURFACE_LABEL: Record<string, string> = {
  platform: '平台提交', document: '发给对方', ledger: '内部记录',
}
const SURFACE_GROUPS = [
  { key: 'platform', label: '平台提交', hint: '平台表单，平台要什么填什么' },
  { key: 'document', label: '发给对方', hint: '要发给客户 / 地接 / 司导的文档' },
  { key: 'ledger', label: '内部记录', hint: '只有自己看的台账，不进群' },
]
const grouped = computed(() => SURFACE_GROUPS.map((g) => ({
  ...g, items: list.value.filter((d) => (d.surface || 'document') === g.key),
})).filter((g) => g.items.length))

const NEEDS_PICK = ['地接社']          // 只有"要给客户以外的人"的产出才让学员选
const needPicker = computed(() => (spec.value?.audience || []).some((a: string) => NEEDS_PICK.includes(a)))
const fixedTargetsText = computed(() => {
  const map: Record<string, string> = { 客户: '客户（客户单聊，客户可直接阅读并回复）',
                                        平台: '平台报备', 内部: '内部留档（不发送）' }
  return (spec.value?.audience || []).map((a: string) => map[a] || a).join(' + ') || '内部留档'
})

const targetOptions = ref<any[]>([])
const pickedTargets = ref<string[]>([])

function audClass(a: string) {
  return a === '客户' ? 'c' : a === '平台' ? 'p' : a === '地接社' ? 's' : 'i'
}
const guardChecks = computed<any[]>(() => result.value?.guard?.deterministic?.checks || [])

function rowsOf(key: string) {
  if (!Array.isArray(values.value[key])) values.value[key] = []
  return values.value[key]
}
function addRow(f: any) {
  rowsOf(f.key).push({})
  loadPreview()
}
function removeRow(key: string, i: number) {
  rowsOf(key).splice(i, 1)
  loadPreview()
}

async function onFile(ev: Event, key: string) {
  const input = ev.target as HTMLInputElement
  const f = input.files?.[0]
  if (!f) return
  const buf = await f.arrayBuffer()
  let bin = ''
  const bytes = new Uint8Array(buf)
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + 0x8000)) as number[])
  }
  const r = (await client.post('/deliverables/files', {
    filename: f.name, mime: f.type || 'application/octet-stream',
    data_b64: btoa(bin), order_id: orderId.value, deliverable_id: spec.value?.id || '',
  })).data
  fileIds.value[key] = r.file_id
  files.value[key] = r
}

async function loadList() {
  const r = (await client.get(`/practice/orders/${orderId.value}/deliverables`)).data
  list.value = r.deliverables
  if (!activeCode.value && list.value.length) {
    const want = String(route.query.code || '')
    const next = (want && list.value.find((d: any) => d.code === want))
      || list.value.find((d: any) => !d.submitted) || list.value[0]
    await open(next.code)
  }
}

async function open(code: string) {
  activeCode.value = code
  result.value = null
  const d = (await client.get(`/practice/orders/${orderId.value}/deliverables/${code}`)).data
  spec.value = d.spec
  targetOptions.value = d.target_options || []
  pickedTargets.value = (d.target_options || []).filter((t: any) => t.default)
    .map((t: any) => t.session_id)
  values.value = d.values || {}
  savedVersion.value = d.version || 0
  fileIds.value = {}
  files.value = {}
  ;(d.spec.fields || []).forEach((f: any) => {
    if (f.type === 'rows' && !Array.isArray(values.value[f.key])) values.value[f.key] = [{}]
  })
  preview.value = d.rendered || ''
  await loadPreview()
}

async function loadPreview() {
  if (!spec.value) return
  try {
    const r = (await client.post(
      `/practice/orders/${orderId.value}/deliverables/${spec.value.code}/preview`, { values: values.value })).data
    preview.value = r.rendered
    missing.value = r.missing || []
  } catch { /* 预览失败不打断填写 */ }
}

function toggleTarget(id: string) {
  const i = pickedTargets.value.indexOf(id)
  if (i >= 0) pickedTargets.value.splice(i, 1)
  else pickedTargets.value.push(id)
}

const sendSummary = computed(() => {
  if (!needPicker.value) return '固定发给：' + fixedTargetsText.value
  const names = targetOptions.value.filter((t) => pickedTargets.value.includes(t.session_id)).map((t) => t.name)
  return names.length ? '将发给：' + names.join('、') : '尚未选择接收人'
})

/** 导出 PDF：版式由后端按同一份渲染结果生成，前端不重拼。 */
async function exportPdf() {
  if (!spec.value || pdfBusy.value) return
  pdfBusy.value = true
  try {
    const r = await client.post(
      `/practice/orders/${orderId.value}/deliverables/${spec.value.code}/export.pdf`,
      { values: values.value }, { responseType: 'blob' })
    const url = URL.createObjectURL(new Blob([r.data], { type: 'application/pdf' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${spec.value.title || spec.value.code}-${orderId.value}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    alert('导出 PDF 失败，请稍后重试')
  } finally {
    pdfBusy.value = false
  }
}

function exportFile() {
  if (!spec.value) return
  const blob = new Blob([preview.value || ''], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = (spec.value.filename || spec.value.code) + '.md'
  a.click()
  URL.revokeObjectURL(url)
}

async function submit() {
  if (!spec.value) return
  busy.value = true
  result.value = null
  try {
    result.value = (await client.post(`/practice/orders/${orderId.value}/deliverables/${spec.value.code}`, {
      values: values.value, file_ids: Object.values(fileIds.value),
      targets: needPicker.value ? pickedTargets.value : [],
    })).data
    await loadList()
    const o = (await client.get(`/practice/orders/${orderId.value}`)).data
    order.value = o
  } catch (e: any) {
    result.value = { blocked: true, guard: { reasons: [e?.response?.data?.detail || '提交失败'] } }
  } finally {
    busy.value = false
  }
}

// 输入即刷新预览（防抖 500ms），不必手动点
let pvTimer = 0
watch(values, () => {
  if (!spec.value) return
  if (pvTimer) clearTimeout(pvTimer)
  pvTimer = window.setTimeout(loadPreview, 500)
}, { deep: true })

onMounted(async () => {
  try { order.value = (await client.get(`/practice/orders/${orderId.value}`)).data } catch {}
  await loadList()
})
watch(orderId, async () => {
  activeCode.value = ''
  spec.value = null
  result.value = null
  await loadList()
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.dw { display: flex; flex-direction: column; gap: 12px; }
.dw-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.back { display: inline-flex; align-items: center; gap: 4px; border: 1px solid $color-border; background: #fff; border-radius: 999px; padding: 6px 14px; font-size: 15.5px; color: $color-primary; cursor: pointer; }
.dw-title { font-size: 24px; font-weight: 800; }
.dw-oid { font-family: ui-monospace, monospace; font-size: 15.5px; color: #e04b4b; }
.dw-cust { font-size: 15px; }
.dw-stage { margin-left: auto; font-size: 15.5px; color: $color-primary; background: $color-primary-soft; border-radius: 999px; padding: 3px 12px; }

.dw-body { display: grid; grid-template-columns: 268px 1fr; gap: 12px; align-items: start; }
.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.dw-side { padding: 8px; }
.side-title { font-size: 15.5px; color: $color-text-muted; padding: 8px 10px 6px; }
.grp-title { font-size: 15px; color: $color-text-muted; margin: 8px 4px 4px; display: flex; gap: 6px; align-items: baseline; }
.grp-sub { font-size: 15px; color: $color-text-secondary; }
.fh-surface { font-size: 15px; color: #fff; background: $color-primary; border-radius: 4px; padding: 1px 7px; }
.send-to { margin-top: 12px; padding: 14px 16px; }
.st-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.st-title { font-size: 15.5px; font-weight: 700; }
.st-hint { font-size: 15px; color: $color-text-muted; }
.st-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(228px, 1fr)); gap: 8px; }
.st-item { display: flex; align-items: center; gap: 7px; border: 1px solid $color-border; border-radius: 8px; padding: 8px 10px; font-size: 15.5px; cursor: pointer; }
.st-item.on { border-color: $color-primary; background: $color-primary-softer; }
.st-name { font-weight: 600; }
.st-kind { font-size: 14.5px; color: $color-text-secondary; background: #f1f4f8; border-radius: 4px; padding: 1px 6px; }
.st-note { font-size: 14.5px; color: $color-text-muted; }
.st-empty { font-size: 15.5px; color: $color-text-muted; }
.st-note-row { margin-top: 9px; font-size: 15px; color: $color-text-muted; }
.doc { width: 100%; display: flex; gap: 10px; align-items: center; text-align: left; border: none; background: none; padding: 9px 10px; border-radius: 8px; cursor: pointer; }
.doc:hover { background: $color-primary-softer; }
.doc.on { background: $color-primary-soft; }
.d-av { width: 26px; height: 26px; border-radius: 8px; background: #eef2f7; color: $color-text-muted; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.d-av.done { background: #e8f7ee; color: #0d8a55; }
.d-mid { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.d-name { font-size: 15.5px; font-weight: 700; }
.d-v { font-style: normal; font-size: 14.5px; color: #0d8a55; margin-left: 6px; }
.d-meta { font-size: 15px; color: $color-text-muted; }

.dw-main { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.empty { padding: 40px; text-align: center; color: $color-text-muted; }
.f-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 13px 16px; flex-wrap: wrap; }
.fh-l { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.fh-title { font-size: 19px; font-weight: 800; }
.fh-step { font-size: 15px; background: #eef2f7; border-radius: 4px; padding: 1px 7px; color: $color-text-secondary; }
.fh-aud { font-size: 15px; border-radius: 999px; padding: 2px 10px; }
.fh-aud.c { background: #e8f0fe; color: #2577e3; }
.fh-aud.p { background: #efe9fe; color: #7a5af8; }
.fh-aud.s { background: #fdf2e4; color: #c77700; }
.fh-aud.i { background: #eef2f7; color: #64748b; }
.fh-r { display: flex; align-items: center; gap: 10px; }
.fh-ver { font-size: 15.5px; color: #0d8a55; background: #e8f7ee; border-radius: 999px; padding: 2px 10px; }
.fh-purpose { font-size: 16px; color: $color-text-secondary; padding: 0 4px; }

.dw-cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; align-items: start; }
.form { padding: 8px 16px 16px; max-height: 720px; overflow-y: auto; }
.fld { margin-top: 12px; }
.lb { display: block; font-size: 15.5px; font-weight: 700; margin-bottom: 5px; }
.req { color: #e04b4b; font-style: normal; margin-left: 3px; }
.help { display: block; font-weight: 400; font-size: 15px; color: $color-text-muted; margin-top: 2px; }
.inp, .ta, .rin { width: 100%; border: 1px solid $color-border; border-radius: 7px; padding: 7px 10px; font-size: 15px; font-family: inherit; outline: none; }
.inp:focus, .ta:focus, .rin:focus { border-color: $color-primary; }
.ta { resize: vertical; line-height: 1.7; }
.rows { border: 1px solid $color-border; border-radius: 8px; padding: 8px; }
.rt { width: 100%; border-collapse: collapse; table-layout: fixed; }
.rt th { font-size: 15px; color: $color-text-muted; text-align: left; padding: 3px 4px; font-weight: 600; white-space: nowrap; }
.rt td { padding: 3px 4px; }
.rin { padding: 5px 7px; font-size: 15.5px; }
.rop { width: 26px; }
.rm { border: none; background: none; color: #e04b4b; cursor: pointer; font-size: 16.5px; }
.add { margin-top: 7px; }
.file { display: flex; align-items: center; gap: 10px; }
.fname { font-size: 15.5px; color: #0d8a55; }

.preview { padding: 0; max-height: 720px; overflow-y: auto; }
.pv-head { display: flex; align-items: center; gap: 10px; padding: 11px 14px; border-bottom: 1px solid $color-border; font-size: 15.5px; font-weight: 700; position: sticky; top: 0; background: #fff; }
.pv-name { font-family: ui-monospace, monospace; font-size: 15px; color: $color-text-muted; font-weight: 400; }
.pv-miss { margin-left: auto; font-size: 15px; color: #c77700; font-weight: 400; }

.result { padding: 13px 16px; }
.result.ok { border-left: 4px solid #12a76a; }
.result.bad { border-left: 4px solid #e04b4b; }
.r-head { display: flex; align-items: center; gap: 10px; margin-bottom: 7px; }
.r-tag { font-size: 15.5px; font-weight: 700; }
.result.ok .r-tag { color: #0d8a55; }
.result.bad .r-tag { color: #c0392b; }
.r-sent, .r-ver { font-size: 15.5px; color: $color-text-muted; }
.r-ver { margin-left: auto; }
.r-why { font-size: 15.5px; color: #c0392b; margin-bottom: 5px; }
.r-line { display: flex; align-items: center; gap: 7px; font-size: 15.5px; line-height: 1.9; color: $color-text-secondary; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: #d5dce5; flex-shrink: 0; }
.dot.ok { background: #12a76a; }
.dot.warn { background: #d98324; }
.r-reply { margin-top: 7px; font-size: 15.5px; line-height: 1.8; background: $color-primary-softer; border-radius: 8px; padding: 9px 12px; }
.r-who { font-weight: 700; color: $color-primary; margin-right: 7px; }
.r-ask { font-size: 15.5px; color: $color-text-muted; }
.r-gate { margin-top: 7px; font-size: 15.5px; color: $color-text-secondary; }
.r-next { margin-left: 8px; color: $color-primary; }

/* ══ 版式优化（2026-10-09）：填满宽度、字段两列、动作粘顶、动作驱动动效 ══ */
.dw { gap: 18px; }
.dw-title { font-size: 24px; font-weight: 800; }
.dw-body { grid-template-columns: 320px minmax(0, 1fr); gap: 20px;
  width: 100%; max-width: 1600px; margin: 0 auto; }
.dw-side { position: sticky; top: 8px; max-height: calc(100vh - 40px); overflow-y: auto; }
.dw-main { min-width: 0; }

.grp-title { display: flex; align-items: baseline; gap: 6px; }
.grp-sub { white-space: normal; line-height: 1.4; }
.doc { transition: background .16s ease, transform .16s ease, box-shadow .16s ease; }
.doc:hover { transform: translateX(2px); }
.d-name { white-space: normal; line-height: 1.35; }
.d-meta { white-space: normal; line-height: 1.45; }

.f-head { position: sticky; top: 0; z-index: 8; gap: 10px; }
.fh-l { min-width: 0; flex-wrap: wrap; }
.fh-title { white-space: normal; }
.fh-purpose { line-height: 1.6; }

.dw-cols { grid-template-columns: minmax(0, 1fr) minmax(360px, 40%); gap: 20px; }
/* 表单：两列自适应，textarea / 行表格 / 文件占满整行 */
.form { max-height: none; overflow: visible;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px 18px; align-content: start; padding: 20px 22px; }
.form .fld { margin-top: 0; min-width: 0; }
.form .fld:has(textarea), .form .fld:has(.rows), .form .fld:has(.file) { grid-column: 1 / -1; }
.lb { line-height: 1.5; }
.help { display: block; margin-top: 3px; line-height: 1.5; }
.rows { overflow-x: auto; }

.preview { position: sticky; top: 78px; max-height: calc(100vh - 150px); }

.inp { border-color: $color-border-strong; border-radius: 6px; transition: border-color .2s ease-out, box-shadow .2s ease-out; }
.inp:focus, .ta:focus { border-color: $color-primary; box-shadow: 0 0 0 2px rgba(37,119,227,.10); }
.send-to .st-item { align-items: flex-start; transition: border-color .16s ease, background .16s ease; }
.st-note { white-space: normal; line-height: 1.45; }
.st-empty { line-height: 1.6; }

.result { animation: reveal .26s cubic-bezier(.22,.9,.3,1) both; }
@keyframes reveal { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
.rows .rt tbody tr { transition: background .14s ease; }
.rows .rt tbody tr:hover { background: $color-primary-softer; }

@media (max-width: 1400px) {
  .dw-cols { grid-template-columns: minmax(0, 1fr); }
  .preview { position: static; max-height: none; }
}
@media (max-width: 1180px) {
  .dw-body { grid-template-columns: minmax(0, 1fr); }
  .dw-side { position: static; max-height: none; }
}
@media (max-width: 820px) { .form { grid-template-columns: minmax(0, 1fr); } }

/* ══ 版式 v2（2026-10-09）：顶部标签带 + 表单/预览等宽 + 弹窗选人 ══ */
.dw { gap: 16px; width: 100%; max-width: 1600px; margin: 0 auto; }

.dw-tabs { display: flex; flex-direction: column; gap: 9px; padding: 13px 16px; }
.tab-grp { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tg-label { flex-shrink: 0; width: 62px; font-size: 13.5px; font-weight: 700; color: $color-text-muted; }
.tab { display: inline-flex; align-items: center; gap: 7px; padding: 7px 14px; cursor: pointer; font-family: inherit;
  border: 1px solid $color-border; border-radius: 999px; background: #fff; color: $color-text-secondary;
  font-size: 15px; transition: all .16s ease; }
.tab:hover { border-color: $color-primary; color: $color-primary; background: $color-primary-softer; }
.tab.on { background: $color-primary; border-color: $color-primary; color: #fff; font-weight: 600; }
.tab.done { color: #0d8a55; border-color: #d6ecdf; background: #f6fbf8; }
.tab.done:hover { border-color: #0d8a55; }
.tb-name { white-space: nowrap; }
.tb-v { font-style: normal; font-size: 12.5px; opacity: .85; }

/* 单列主体：表单与预览各占一半，解决预览被挤窄的问题 */
.dw-body { grid-template-columns: minmax(0, 1fr); }
.dw-cols { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; }
/* v1 只写了 grid-template-columns 没写 display:grid，字段两列一直没生效 */
.form { display: grid; padding: 18px 20px 20px; }

.f-head { padding: 14px 18px; }
.fh-r { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.fh-ver { display: inline-flex; align-items: center; gap: 5px; }
/* 三个动作按钮：导出做成同款次级按钮，提交做成唯一的主按钮 */
.exp-group { display: inline-flex; align-items: center; gap: 10px; }
.exp { display: inline-flex; align-items: center; gap: 7px; height: 42px; padding: 0 16px;
  border: 1px solid #d9e3f1; border-radius: 10px; background: linear-gradient(#ffffff, #f6faff);
  color: $color-text-secondary; font-size: 15px; font-family: inherit; cursor: pointer;
  box-shadow: 0 1px 2px rgba(16, 42, 80, 0.05); transition: all .16s ease; }
.exp:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; background: $color-primary-softer;
  box-shadow: 0 6px 14px rgba(37, 119, 227, 0.14); transform: translateY(-1px); }
.exp:active:not(:disabled) { transform: translateY(0); box-shadow: 0 1px 2px rgba(16, 42, 80, 0.05); }
.exp:disabled { opacity: .6; cursor: default; }
.ex-t { display: inline-flex; align-items: baseline; gap: 4px; white-space: nowrap; }
.ex-fmt { font-style: normal; font-weight: 700; letter-spacing: .2px; color: $color-text; }
.exp:hover:not(:disabled) .ex-fmt { color: $color-primary; }
.submit-btn { display: inline-flex; align-items: center; gap: 8px; height: 42px; padding: 0 24px;
  border-radius: 10px; font-weight: 700; letter-spacing: .2px;
  background: linear-gradient(135deg, #3389f7, #1a63d8);
  box-shadow: 0 6px 16px rgba(26, 99, 216, 0.26); }
.submit-btn:hover:not(:disabled) { background: linear-gradient(135deg, #4598ff, #1a5cc6);
  box-shadow: 0 10px 22px rgba(26, 99, 216, 0.32); transform: translateY(-1px); }
.submit-btn:active:not(:disabled) { transform: translateY(0);
  box-shadow: 0 4px 10px rgba(26, 99, 216, 0.24); }

.preview { display: flex; flex-direction: column; top: 86px; }
.pv-head { gap: 9px; color: $color-primary; }
.pv-title { font-size: 15.5px; font-weight: 700; color: $color-text; }
.pv-paper { padding: 22px 26px 28px; }

.send-row { display: flex; align-items: center; gap: 11px; padding: 12px 16px; }
.sr-ic { width: 28px; height: 28px; border-radius: 8px; display: flex; align-items: center; justify-content: center;
  background: $color-primary-soft; color: $color-primary; flex-shrink: 0; }
.sr-k { font-size: 15px; font-weight: 700; white-space: nowrap; }
.sr-v { flex: 1; min-width: 0; font-size: 15px; color: $color-text-secondary; }
.sr-edit { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }

.modal-mask { position: fixed; inset: 0; z-index: 60; display: flex; align-items: center; justify-content: center;
  background: rgba(16, 32, 56, 0.42); backdrop-filter: blur(2px); }
@keyframes popIn { from { opacity: 0; transform: translateY(-8px) scale(.98); } to { opacity: 1; transform: none; } }
.modal { width: 560px; max-width: 92vw; max-height: 82vh; display: flex; flex-direction: column; background: #fff;
  border-radius: $radius-xl; box-shadow: $shadow-deep; overflow: hidden; animation: popIn .22s cubic-bezier(.22,.9,.3,1) both; }
.md-head { display: flex; align-items: baseline; gap: 10px; padding: 18px 20px 14px; border-bottom: 1px solid $color-border; }
.md-title { font-size: 19px; font-weight: 800; }
.md-sub { flex: 1; min-width: 0; font-size: 14.5px; color: $color-text-muted; }
.md-x { border: none; background: none; cursor: pointer; color: $color-text-muted; padding: 2px; line-height: 0; }
.md-x:hover { color: $color-danger; }
.md-body { flex: 1; overflow-y: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 8px; }
.pick { display: flex; align-items: center; gap: 12px; text-align: left; padding: 12px 14px; cursor: pointer;
  font-family: inherit; border: 1px solid $color-border; border-radius: $radius-md; background: #fff; transition: all .16s ease; }
.pick:hover { border-color: $color-primary; background: $color-primary-softer; }
.pick.on { border-color: $color-primary; background: $color-primary-softer; box-shadow: 0 0 0 2px rgba(37,119,227,.10); }
.pk-av { width: 36px; height: 36px; flex-shrink: 0; border-radius: 10px; display: flex; align-items: center;
  justify-content: center; background: $color-primary-soft; color: $color-primary; font-size: 16px; font-weight: 700; }
.pk-av.on { background: $color-primary; color: #fff; }
.pk-mid { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.pk-name { font-size: 15.5px; font-weight: 700; }
.pk-hint { font-size: 14px; color: $color-text-muted; }
.pk-kind { font-size: 13.5px; color: $color-text-secondary; background: #f1f4f8; border-radius: 6px; padding: 2px 9px; white-space: nowrap; }
.pk-check { width: 20px; height: 20px; flex-shrink: 0; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; color: #fff; border: 1px solid $color-border-strong; transition: all .16s ease; }
.pick.on .pk-check { background: $color-primary; border-color: $color-primary; }
.md-empty { padding: 26px 12px; text-align: center; font-size: 15px; color: $color-text-muted; }
.md-foot { display: flex; align-items: center; gap: 10px; padding: 14px 20px; border-top: 1px solid $color-border; }
.md-count { flex: 1; font-size: 14.5px; color: $color-text-secondary; }
.pop-enter-active, .pop-leave-active { transition: opacity .2s ease; }
.pop-enter-from, .pop-leave-to { opacity: 0; }

@media (max-width: 1240px) {
  .dw-cols { grid-template-columns: minmax(0, 1fr); }
  .preview { position: static; max-height: none; top: auto; }
}
@media (prefers-reduced-motion: reduce) { .modal { animation: none; } }
</style>