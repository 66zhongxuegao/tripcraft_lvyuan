<template>
  <div class="app-shell">
    <aside v-if="!isFullscreen" class="sidebar">
      <div class="side-top">
        <AppLogo />
      </div>
      <nav class="side-nav">
        <template v-for="g in groups" :key="g.title">
          <div v-if="g.title" class="nav-group">{{ g.title }}</div>
          <router-link v-for="item in g.items" :key="item.path" :to="item.path"
            class="nav-item" :class="{ active: isActive(item.path) }">
            <SIcon :name="item.icon" :size="16" />
            <span>{{ item.title }}</span>
          </router-link>
        </template>
      </nav>
      <div class="side-foot">
        <router-link to="/" class="foot-card" :class="{ on: route.path === '/' }">
          <span class="foot-title"><SIcon name="home" :size="15" /> 返回首页</span>
          <span class="foot-sub">8 维 · 61 技能点<br />每分带证据</span>
        </router-link>
      </div>
    </aside>

    <main class="main">
      <header class="topbar" :class="{ plain: isFullscreen }">
        <div v-if="!isFullscreen" class="topbar-left">
          <h1 class="page-title">{{ pageHeading }}</h1>
        </div>
        <div class="topbar-right">
          <span class="status" :class="online ? 'on' : 'off'"><i class="dot" />{{ online ? '已连接' : '未连接' }}</span>
          <div class="account" @click="userMenuOpen = !userMenuOpen">
            <span class="acc-avatar">{{ currentUserName.slice(0, 1) }}</span>
            <span class="acc-name">{{ currentUserName }}</span>
            <span class="acc-chev" />
            <transition name="menu">
              <div v-if="userMenuOpen" class="acc-menu" @click.stop>
                <div class="acc-menu-hd">切换用户</div>
                <div v-for="u in user.users" :key="u.id" class="acc-item"
                  :class="{ on: u.id === user.userId }" @click="onSwitchTo(u.id)">
                  <span class="ai-avatar">{{ u.name.slice(0, 1) }}</span>{{ u.name }}<i v-if="u.id === user.userId" class="ai-on">当前</i>
                </div>
                <div class="acc-divider" />
                <div class="acc-item new" @click="onNewUser">＋ 新建用户</div>
              </div>
            </transition>
          </div>
        </div>
      </header>

      <section class="content" :class="{ plain: isFullscreen }">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </section>
      <ProgressDock v-if="route.path.startsWith('/practice')" :order-id="String(route.params.id || '')" />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppLogo from '@/components/AppLogo.vue'
import SIcon from '@/components/SIcon.vue'
import ProgressDock from '@/components/ProgressDock.vue'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const user = useUserStore()
const online = ref(false)

const groups = [
  { title: '学习中心', items: [
    { path: '/learn', title: '学习地图', icon: 'book' },
  ]},
  { title: '对话实战', items: [
    { path: '/practice/messages', title: '消息中心', icon: 'chat' },
    { path: '/practice', title: '订单管理', icon: 'layers' },
    { path: '/practice/im', title: '聊天界面', icon: 'chat' },
  ]},
  { title: '训练反馈', items: [
    { path: '/profile', title: '学情画像', icon: 'chart' },
    { path: '/score', title: '评分复盘', icon: 'link' },
    { path: '/toolbox', title: '工具台', icon: 'map' },
    { path: '/system', title: '系统状态', icon: 'target' },
  ]},
]

const userMenuOpen = ref(false)
const currentUserName = computed(() => user.users.find((u) => u.id === user.userId)?.name || user.userId)
function onSwitchTo(id: string) { if (id && id !== user.userId) { user.switchUser(id); window.location.reload() } }
function onNewUser() { user.addUser(); window.location.reload() }

function isActive(p: string) {
  if (p === '/') return route.path === '/'
  if (p === '/practice') return route.path === '/practice'
  return route.path.startsWith(p)
}

/* 主标题直接承载页面用途，不再挂灰色副标题；补充说明放到正文层。 */
const HEADINGS: Record<string, string> = {
  '/': '总览 · 定制师全流程实战',
  '/learn': '学习地图 · 8 维 61 技能点',
  '/learn/tutor': '技能点对话 · 生成学习资源',
  '/learn/practice': '技能点练题 · 写回掌握度',
  '/practice': '订单管理 · 逐单推进 13 步',
  '/practice/messages': '消息中心 · 抢派单',
  '/practice/orders': '订单详情',
  '/practice/im': '聊天界面 · 客户 / 地接 / 供应商',
  '/profile': '学情画像 · 掌握度与薄弱点',
  '/score': '评分复盘 · 按订单下钻',
  '/toolbox': '工具台 · 方案要用的外部数据',
  '/system': '系统状态 · 导演规则与评分公信力',
}
const pageHeading = computed(() => HEADINGS[route.path] || String(route.meta.title || '总览'))
/* 总览页走全画面：不挂侧边栏 */
const isFullscreen = computed(() => !!route.meta.fullscreen)

onMounted(async () => {
  try { online.value = (await client.get('/')).data?.status === 'ok' } catch { online.value = false }
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
/* 底纹位移走 GPU 合成：曾直接动画 background-position，导致整屏逐帧重绘。 */
.app-shell { position: relative; display: flex; height: 100vh; overflow: hidden; background: $color-bg; }
.app-shell::before {
  content: ''; position: absolute; inset: -25%; z-index: 0; pointer-events: none;
  background:
    radial-gradient(720px 520px at 22% 22%, rgba(37, 119, 227, 0.05), transparent 62%),
    radial-gradient(620px 480px at 74% 74%, rgba(74, 143, 240, 0.04), transparent 60%);
  will-change: transform;
  animation: shellDrift 32s ease-in-out infinite alternate;
}
@keyframes shellDrift { from { transform: translate3d(0, 0, 0); } to { transform: translate3d(90px, 60px, 0); } }

.sidebar { position: relative; z-index: 1; width: $sidebar-width; flex-shrink: 0; display: flex; flex-direction: column; background: $color-surface; border-right: 1px solid $color-border; }
.side-top { flex-shrink: 0; padding: 20px 20px 16px; border-bottom: 1px solid $color-border; }
.side-nav { padding: 10px 10px; display: flex; flex-direction: column; gap: 2px; flex: 1; overflow-y: auto; }
.nav-group { font-size: 14px; color: $color-text-muted; letter-spacing: .5px; padding: 16px 12px 6px; font-weight: 700; }
.nav-item { position: relative; display: flex; align-items: center; gap: 11px; padding: 11px 12px; border-radius: $radius-md; color: $color-text-secondary; font-size: 15.5px; transition: all .15s ease; }
.nav-item::before { content: ''; position: absolute; left: 0; top: 50%; width: 3px; height: 0; border-radius: 0 3px 3px 0;
  background: $color-primary; transform: translateY(-50%); transition: height .18s cubic-bezier(.34,1.3,.6,1); }
.nav-item.active::before { height: 18px; }
.nav-item:hover { background: $color-primary-softer; color: $color-primary; }
.nav-item.active { background: $color-primary-soft; color: $color-primary; font-weight: 600; }
.side-foot { flex-shrink: 0; padding: 14px; }
.foot-card { display: block; padding: 13px 15px; border-radius: $radius-md; color: #fff;
  background: linear-gradient(135deg, $color-primary, $color-primary-dark);
  box-shadow: 0 6px 16px rgba(37,119,227,0.24);
  transition: transform .18s cubic-bezier(.34,1.4,.6,1), box-shadow .18s ease; }
.foot-card:hover { transform: translateY(-2px); box-shadow: 0 12px 24px rgba(37,119,227,0.32); }
.foot-card.on { box-shadow: 0 0 0 3px rgba(37,119,227,0.18), 0 6px 16px rgba(37,119,227,0.24); }
.foot-title { display: inline-flex; align-items: center; gap: 7px; font-size: 16px; font-weight: 700; }
.foot-sub { display: block; margin-top: 5px; font-size: 14.5px; font-weight: 500; line-height: 1.5; color: rgba(255,255,255,0.9); }

.main { position: relative; z-index: 1; flex: 1; min-width: 0; display: flex; flex-direction: column; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 18px 28px; background: $color-surface; border-bottom: 1px solid $color-border; }
/* 全画面路由（总览）：不写大标题，顶栏也退成一层薄边，让画面从顶部就开始 */
/* 全画面路由：标题隐藏后只剩右侧一组，必须显式靠右，否则 space-between 会把它甩到最左 */
.topbar.plain { padding: 12px 28px; background: transparent; border-bottom: none; justify-content: flex-end; }
.content.plain { padding: 12px 28px 28px; }
.page-title { font-size: $fs-page-title; font-weight: 800; letter-spacing: .3px; line-height: 1.25; }

.topbar-right { display: flex; align-items: center; gap: 12px; }
.account { position: relative; display: flex; align-items: center; gap: 8px; padding: 4px 12px 4px 5px; border: 1px solid $color-border; border-radius: 999px; background: #fff; cursor: pointer; transition: border-color .15s ease, box-shadow .15s ease; }
.account:hover { border-color: $color-primary; box-shadow: $shadow-card; }
.acc-avatar { width: 36px; height: 36px; border-radius: 50%; background: linear-gradient(135deg, #2577e3, #4a8ff0); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 15.5px; font-weight: 700; }
.acc-name { font-size: 15.5px; font-weight: 600; color: $color-text; }
.acc-chev { width: 7px; height: 7px; border-right: 1.5px solid $color-text-secondary; border-bottom: 1.5px solid $color-text-secondary; transform: rotate(45deg) translateY(-2px); }
.acc-menu { position: absolute; top: calc(100% + 8px); right: 0; width: 258px; background: #fff; border: 1px solid $color-border; border-radius: 12px; box-shadow: 0 16px 40px rgba(16,32,56,0.18); padding: 7px; z-index: 50; }
.acc-menu-hd { font-size: 14.5px; color: $color-text-muted; padding: 5px 9px; letter-spacing: 1px; }
.acc-item { display: flex; align-items: center; gap: 10px; padding: 10px; border-radius: 8px; font-size: 15.5px; color: $color-text; cursor: pointer; }
.acc-item:hover { background: $color-primary-softer; }
.acc-item.on { background: $color-primary-soft; color: $color-primary; font-weight: 600; }
.ai-avatar { width: 26px; height: 26px; border-radius: 50%; background: $color-primary-soft; color: $color-primary; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; flex-shrink: 0; }
.ai-on { margin-left: auto; font-style: normal; font-size: 13.5px; color: $color-primary; background: $color-primary-soft; border-radius: 999px; padding: 1px 7px; }
.acc-item.new { color: $color-primary; font-weight: 600; }
.acc-divider { height: 1px; background: $color-border; margin: 5px 4px; }
.menu-enter-active, .menu-leave-active { transition: opacity .16s ease, transform .16s ease; }
.menu-enter-from, .menu-leave-to { opacity: 0; transform: translateY(-6px); }
.status { display: inline-flex; align-items: center; gap: 7px; font-size: 14.5px; padding: 6px 14px; border-radius: 999px; background: $color-bg; border: 1px solid $color-border; }
.status .dot { width: 8px; height: 8px; border-radius: 50%; }
.status.on { color: $color-success; } .status.on .dot { background: $color-success; }
.status.off { color: $color-danger; } .status.off .dot { background: $color-danger; }

.content { flex: 1; overflow-y: auto; padding: 20px 28px 40px; }
.step-wrap { margin-bottom: 14px; }
.fade-enter-active, .fade-leave-active { transition: opacity .16s ease, transform .16s ease; }
.fade-enter-from { opacity: 0; transform: translateY(5px); }
.fade-leave-to { opacity: 0; }

</style>