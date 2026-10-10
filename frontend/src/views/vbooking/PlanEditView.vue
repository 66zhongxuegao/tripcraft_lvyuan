<template>
  <div class="vb">
    <div class="vb-crumb">
      <span class="lnk" @click="router.push('/practice')">订单管理</span> &gt;
      <span class="lnk" @click="router.push(`/practice/orders/${orderId}`)">订单详情</span> &gt; 方案编辑
    </div>

    <div class="topbar">
      <div class="tb-left">
        <span class="tb-order mono">需求单号 {{ orderId }}</span>
        <span class="tb-tip">当前没有定制师超越您！</span>
      </div>
      <div class="tb-right">
        <button class="tc-btn ghost">操作指南</button>
        <button class="tc-btn ghost">导出方案PDF</button>
        <button class="tc-btn ghost">＋ 导入方案/行程</button>
        <button class="tc-btn">更换方案类型</button>
      </div>
    </div>

    <div class="tabs card">
      <button v-for="t in tabs" :key="t" class="tab" :class="{ active: tab === t }" @click="tab = t">{{ t }}</button>
    </div>

    <div class="snapshot card">
      <div class="snap-item"><span class="sk">方案名称</span><span class="sv">{{ form.name || '（未填写）' }}</span></div>
      <div class="snap-item"><span class="sk">方案总价</span><span class="sv">CNY 0</span></div>
      <div class="snap-item"><span class="sk">方案状态</span><span class="sv chip">方案待创建</span></div>
      <div class="snap-item"><span class="sk">最后更新时间</span><span class="sv muted">—</span></div>
      <select class="hist"><option>请选择历史方案</option></select>
    </div>

    <div v-if="tab === '方案概况'" class="card form">
      <div class="row"><label class="lbl">方案名称 <i>*</i></label><input v-model="form.name" class="inp" /></div>
      <div class="row"><label class="lbl">出发日期 <i>*</i></label><input v-model="form.date" type="date" class="inp" /></div>
      <div class="row"><label class="lbl">出行人数 <i>*</i></label>
        <div class="people">
          <input v-model.number="form.adult" class="num" /><span class="unit">成人</span>
          <input v-model.number="form.child" class="num" /><span class="unit">儿童</span>
          <input v-model.number="form.baby" class="num" /><span class="unit">婴儿</span>
        </div>
      </div>
      <div class="row"><label class="lbl">出发城市 <i>*</i></label><input v-model="form.fromCity" class="inp" /></div>
      <div class="row"><label class="lbl">目的城市 <i>*</i></label>
        <div class="tags">
          <span v-for="(c, i) in form.toCities" :key="c" class="tag">{{ c }} <b @click="form.toCities.splice(i, 1)">×</b></span>
          <input v-model="newCity" class="tag-input" placeholder="输入后回车添加" @keydown.enter="addCity" />
        </div>
      </div>
      <div class="row"><label class="lbl">方案亮点</label><input v-model="form.highlight" class="inp" /></div>
      <div class="row"><label class="lbl">方案特色</label>
        <div class="editor">
          <div class="toolbar"><span>B</span><span><i>I</i></span><span><u>U</u></span><span>≡</span><span>≣</span><span>“”</span><span>🔗</span></div>
          <textarea v-model="form.feature" class="rte" placeholder="填写方案特色（≤200 字）"></textarea>
          <div class="count">{{ (form.feature || '').length }} / 200</div>
        </div>
        <button class="tc-btn ghost mini">导入特色</button>
      </div>

      <div class="form-foot">
        <button class="tc-btn ghost">将方案另存为新模版</button>
        <button class="tc-btn">保存</button>
      </div>
    </div>

    <div v-else class="card placeholder">
      「{{ tab }}」内容将在后续版本实现（当前完整实现「方案概况」）。
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const orderId = computed(() => String(route.params.id || ''))

const tabs = ['方案概况', '行程描述', '报价方案']
const tab = ref('方案概况')
const newCity = ref('')
const form = reactive({
  name: '云南 6 日亲子定制', date: '2026-10-20', adult: 3, child: 1, baby: 0,
  fromCity: '上海(中国)', toCities: ['昆明(中国)', '大理(中国)'],
  highlight: '一览苍山洱海，慢节奏亲子度假',
  feature: '',
})

function addCity() {
  const v = newCity.value.trim()
  if (v && !form.toCities.includes(v)) form.toCities.push(v)
  newCity.value = ''
}
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.vb { max-width: 1160px; }
.vb-crumb { font-size: 15.5px; color: $color-text-muted; margin-bottom: 12px; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }

.topbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.tb-left { display: flex; align-items: baseline; gap: 12px; }
.tb-order { font-size: 15px; color: $color-text-secondary; }
.tb-tip { font-size: 15.5px; color: #12a76a; }
.tb-right { display: flex; gap: 8px; }

.card { background: #fff; border: 1px solid $color-border; border-radius: $radius-md; }
.tabs { display: flex; gap: 4px; padding: 0 8px; margin-bottom: 12px; }
.tab { border: none; background: transparent; padding: 12px 16px; font-size: 16px; color: $color-text-secondary; cursor: pointer; border-bottom: 2px solid transparent; }
.tab.active { color: $color-primary; font-weight: 700; border-bottom-color: $color-primary; }

.snapshot { display: flex; align-items: center; gap: 26px; padding: 14px 18px; margin-bottom: 12px; }
.snap-item { display: flex; flex-direction: column; gap: 3px; }
.sk { font-size: 15.5px; color: $color-text-muted; }
.sv { font-size: 15.5px; font-weight: 600; }
.sv.muted { color: $color-text-muted; font-weight: 400; }
.chip { background: $color-primary-soft; color: $color-primary; font-size: 15.5px; padding: 2px 9px; border-radius: 4px; font-weight: 400; }
.hist { margin-left: auto; height: 30px; border: 1px solid $color-border; border-radius: 6px; font-size: 15px; padding: 0 8px; }

.form { padding: 20px 22px; }
.row { display: flex; gap: 14px; margin-bottom: 16px; align-items: flex-start; }
.lbl { width: 92px; flex-shrink: 0; font-size: 15px; color: $color-text-secondary; padding-top: 7px; }
.lbl i { color: #e04b4b; font-style: normal; }
.inp { flex: 1; height: 34px; border: 1px solid $color-border; border-radius: 6px; padding: 0 10px; font-size: 15px; outline: none; }
.inp:focus { border-color: $color-primary; }
.people { display: flex; align-items: center; gap: 8px; }
.num { width: 64px; height: 34px; border: 1px solid $color-border; border-radius: 6px; padding: 0 8px; font-size: 15px; }
.unit { font-size: 15.5px; color: $color-text-muted; margin-right: 10px; }
.tags { flex: 1; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.tag { display: inline-flex; align-items: center; gap: 5px; background: $color-primary-soft; color: $color-primary; font-size: 15.5px; padding: 4px 10px; border-radius: 6px; }
.tag b { cursor: pointer; font-weight: 400; }
.tag-input { height: 32px; border: 1px dashed $color-border-strong; border-radius: 6px; padding: 0 10px; font-size: 15px; width: 170px; }
.editor { flex: 1; border: 1px solid $color-border; border-radius: 6px; overflow: hidden; }
.toolbar { display: flex; gap: 14px; padding: 7px 12px; background: #fafbfc; border-bottom: 1px solid $color-border; font-size: 15px; color: $color-text-secondary; }
.rte { width: 100%; min-height: 96px; border: none; outline: none; padding: 10px 12px; font-size: 15px; resize: vertical; font-family: inherit; }
.count { text-align: right; font-size: 15px; color: $color-text-muted; padding: 4px 12px; }
.mini { margin-left: 10px; }
.form-foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 6px; }
.placeholder { padding: 50px; text-align: center; color: $color-text-muted; font-size: 15.5px; }
.lnk { color: $color-primary; cursor: pointer; }
.lnk:hover { text-decoration: underline; }
</style>