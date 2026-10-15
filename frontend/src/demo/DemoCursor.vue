<template>
  <div class="cursor-layer">
    <div class="cur" :class="{ on: cursor.visible, tap: cursor.clicking, typing: cursor.typing }"
      :style="{ transform: `translate3d(${Math.round(cursor.x)}px, ${Math.round(cursor.y)}px, 0)` }">
      <svg width="34" height="46" viewBox="0 0 22 30">
        <path d="M2 1.6 L2 24.5 L8.1 18.6 L12 28.2 L15.6 26.6 L11.7 17.2 L19.6 16.6 Z"
          fill="#ffffff" stroke="#083161" stroke-width="1.5" stroke-linejoin="round" />
      </svg>
    </div>

    <template v-if="cursor.clicking">
      <span class="ring r1" :style="{ left: Math.round(cursor.x) + 'px', top: Math.round(cursor.y) + 'px' }" />
      <span class="ring r2" :style="{ left: Math.round(cursor.x) + 'px', top: Math.round(cursor.y) + 'px' }" />
      <span class="core" :style="{ left: Math.round(cursor.x) + 'px', top: Math.round(cursor.y) + 'px' }" />
    </template>

    <span v-if="cursor.typing" class="caret-hint" :style="{ left: Math.round(cursor.x) + 'px', top: Math.round(cursor.y) + 'px' }">
      <i /><i /><i />
    </span>
  </div>
</template>

<script setup lang="ts">
import { cursor } from './driver'
</script>

<style scoped>
.cursor-layer { position: fixed; inset: 0; z-index: 2147483000; pointer-events: none; }
.cur { position: absolute; left: 0; top: 0; opacity: 0; transition: opacity .2s ease; will-change: transform; }
.cur.on { opacity: 1; }
.cur svg { display: block; filter: drop-shadow(0 4px 10px rgba(8, 49, 97, 0.42)); transform-origin: 2px 2px; }
.cur.tap svg { transform: scale(.88); transition: transform .11s ease; }
.tip { position: absolute; left: 32px; top: 34px; white-space: nowrap; font-size: 14px; font-weight: 600; color: #fff;
  background: #083161; border-radius: 999px; padding: 4px 13px; box-shadow: 0 8px 20px rgba(8, 49, 97, .34); }
.ring { position: absolute; width: 18px; height: 18px; margin: -9px 0 0 -9px; border-radius: 50%;
  border: 3px solid #083161; }
.r1 { animation: ringOut .85s cubic-bezier(.22,.61,.36,1) forwards; }
.r2 { animation: ringOut .85s cubic-bezier(.22,.61,.36,1) .12s forwards; opacity: .55; }
.core { position: absolute; width: 22px; height: 22px; margin: -11px 0 0 -11px; border-radius: 50%;
  background: rgba(8, 49, 97, .22); animation: coreIn .5s ease-out forwards; }
@keyframes ringOut { from { transform: scale(.35); opacity: .95; } to { transform: scale(5.2); opacity: 0; } }
@keyframes coreIn { from { transform: scale(.5); opacity: .9; } to { transform: scale(1.6); opacity: 0; } }
.caret-hint { position: absolute; margin: -30px 0 0 6px; display: flex; gap: 4px; align-items: center; }
.caret-hint i { width: 5px; height: 5px; border-radius: 50%; background: #083161; animation: blink .9s infinite; }
.caret-hint i:nth-child(2) { animation-delay: .15s; }
.caret-hint i:nth-child(3) { animation-delay: .3s; }
@keyframes blink { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
</style>
