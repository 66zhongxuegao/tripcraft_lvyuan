<template>
  <div class="stepbar">
    <div v-for="(s, i) in STEPS" :key="s.id" class="sb-item"
      :class="{ active: current === s.id, done: i < currentIndex }">
      <span class="sb-dot">{{ i + 1 }}</span>
      <span class="sb-name">{{ s.name }}</span>
      <span v-if="i < STEPS.length - 1" class="sb-line" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ current?: string }>(), { current: 'S2' })

/** 13 个主状态（PRD 第 3.2 节） */
const STEPS = [
  { id: 'S0', name: '交底' }, { id: 'S1', name: '抢单' }, { id: 'S2', name: '首呼' },
  { id: 'S3', name: '需求确认' }, { id: 'S4', name: '资源询价' }, { id: 'S5', name: '行程方案' },
  { id: 'S6', name: '分项报价' }, { id: 'S7', name: '反馈迭代' }, { id: 'S8', name: '成交录单' },
  { id: 'S9', name: '资源锁定' }, { id: 'S10', name: '行中执行' }, { id: 'S11', name: '行后结算' },
  { id: 'S12', name: '复盘' },
]
const currentIndex = computed(() => Math.max(0, STEPS.findIndex((s) => s.id === props.current)))
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
.stepbar { display: flex; align-items: center; gap: 0; background: #fff; border: 1px solid $color-border; border-radius: $radius-md; padding: 10px 14px; overflow-x: auto; }
.sb-item { display: flex; align-items: center; gap: 7px; flex-shrink: 0; }
.sb-dot { width: 22px; height: 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14.5px; background: #eef1f5; color: $color-text-muted; flex-shrink: 0; }
.sb-name { font-size: 15.5px; color: $color-text-muted; white-space: nowrap; }
.sb-line { width: 26px; height: 1px; background: $color-border; margin: 0 8px; }
.sb-item.done .sb-dot { background: #e8f7ee; color: #12a76a; }
.sb-item.done .sb-name { color: $color-text-secondary; }
.sb-item.active .sb-dot { background: $color-primary; color: #fff; }
.sb-item.active .sb-name { color: $color-primary; font-weight: 700; }
</style>