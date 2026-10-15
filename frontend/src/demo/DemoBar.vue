<template>
  <div class="demo-bar" data-demo-stop>
    <span class="ph">{{ beat.phase }}</span>
    <span class="tt">{{ store.index + 1 }} / {{ store.total }} · {{ beat.title }}</span>
    <span class="ac">{{ beat.action }}</span>
    <span class="sp" />
    <button class="ctl" :disabled="store.running || store.index === 0" @click="store.prev()">上一步</button>
    <button class="ctl replay" :disabled="store.running" @click="store.replay()">重播本步</button>
    <button class="ctl play" :class="{ on: store.playing }" @click="store.togglePlay()">
      {{ store.playing ? '暂停' : '自动播放' }}
    </button>
    <button class="ctl" :disabled="store.running || store.index >= store.total - 1" @click="store.next()">下一步</button>
    <button class="ctl exit" @click="store.stop()">退出演示</button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useDemoStore } from './store'

const store = useDemoStore()
const beat = computed(() => store.beat)
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;

.demo-bar { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 2147483001;
  display: flex; align-items: center; gap: 10px; max-width: calc(100vw - 48px);
  background: rgba(255, 255, 255, 0.97); border: 1px solid $color-border; border-radius: 999px;
  padding: 8px 12px 8px 16px; box-shadow: 0 16px 44px rgba(16, 32, 56, 0.22); }
.ph { font-size: 13px; color: $color-primary; background: $color-primary-soft; border-radius: 999px; padding: 3px 10px; white-space: nowrap; }
.tt { font-size: 14.5px; font-weight: 700; color: $color-text; white-space: nowrap; }
.ac { font-size: 13.5px; color: $color-text-secondary; max-width: 42ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sp { width: 1px; height: 20px; background: $color-border; }
.ctl { font-size: 13.5px; border: 1px solid $color-border; background: #fff; color: $color-text-secondary;
  border-radius: 999px; padding: 6px 14px; cursor: pointer; white-space: nowrap; }
.ctl:hover:not(:disabled) { border-color: $color-primary; color: $color-primary; }
.ctl:disabled { opacity: .45; cursor: default; }
.ctl.play { background: $color-primary; border-color: $color-primary; color: #fff; font-weight: 600; }
.ctl.play.on { background: $color-primary-dark; }
.ctl.exit { color: $color-danger; }
.ctl.exit:hover { border-color: $color-danger; color: $color-danger; }
@media (max-width: 1280px) { .ac { display: none; } }
</style>
