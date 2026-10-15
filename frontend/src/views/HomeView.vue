<template>
  <div class="home">
    <section class="hero card rise">
      <img class="hero-yun" :src="yunUrl" alt="" />
      <div class="hero-inner">
        <div class="hero-body">
          <h2 class="hero-title">在压力下，连续交付真实工作物</h2>
          <p class="hero-desc">13 步状态机、61 个技能点原子评分，倒计时、预算、资源、突发事件四重压力，每一步都可追溯。</p>
          <div class="hero-actions">
            <button class="tc-btn hero-cta" :class="{ locked: loaded && !canAssess }"
              :disabled="loaded && !canAssess" @click="startQuiz">
              <SIcon name="sparkle" :size="15" />
              {{ !loaded ? '画像' : (canAssess ? '画像' : '画像已建档') }}
            </button>
            <router-link to="/profile" class="tc-btn ghost"><SIcon name="chart" :size="15" /> 查看学情画像</router-link>
          </div>
          <p v-if="loaded && !canAssess" class="hero-hint">
            初始画像只对新用户开放。已有画像数据请到学情画像页用「更新画像」刷新。
          </p>
        </div>

        <div class="hero-facts">
          <div v-for="(s, i) in stats" :key="s.label" class="fact">
            <div class="fact-num">{{ animated[i] ?? s.value }}<i v-if="s.unit">{{ s.unit }}</i></div>
            <div class="fact-label">{{ s.label }}</div>
            <div class="fact-note">{{ s.note }}</div>
          </div>
        </div>
      </div>
    </section>

    <section class="block">
      <div class="block-head title-rule"><span>核心亮点</span></div>
      <div class="cards">
        <div v-for="h in highlights" :key="h.title" class="hl card rise">
          <div class="hl-icon"><SIcon :name="h.icon" :size="19" /></div>
          <div class="hl-title">{{ h.title }}</div>
          <div class="hl-desc">{{ h.desc }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import SIcon from '@/components/SIcon.vue'
import yunUrl from '@/assets/deco/yun-white.png'
import client from '@/api/client'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
const canAssess = ref(false)
const loaded = ref(false)

const stats = [
  { value: '13', unit: '', label: '流程步骤', note: '状态机驱动' },
  { value: '61', unit: '', label: '技能点', note: '8 维原子评分' },
  { value: '10', unit: '类', label: 'AI 角色', note: '客户 · 资源方 · 导演…' },
  { value: '6', unit: '类', label: '交付工作物', note: '需求单 · 方案 · 报价…' },
]

const animated = ref<Record<number, string>>({})
function animateStats() {
  stats.forEach((s, i) => {
    const num = parseInt(s.value)
    if (Number.isNaN(num)) { animated.value[i] = s.value; return }
    const target = num
    let cur = 0
    const tick = () => {
      cur = Math.min(target, cur + Math.max(1, Math.ceil(target / 55)))
      animated.value[i] = String(cur)
      if (cur < target) requestAnimationFrame(tick)
    }
    tick()
  })
}

const highlights = [
  { icon: 'shield', title: '覆盖校验', desc: '按 Rubric 埋点，未考核到的技能点不更新画像。' },
  { icon: 'link', title: '证据链', desc: '每一分都引用学员原话或交付物片段，可反查。' },
  { icon: 'route', title: '画像-难度闭环', desc: '掌握度分 M1–M5 五档，M1 以补救为主，M2–M5 逐档加压。' },
  { icon: 'globe', title: '真实外部数据', desc: '接入真实地图与天气，折返耗时自动核验。' },
]

function startQuiz() {
  if (canAssess.value) router.push('/profile/quiz')
}

onMounted(async () => {
  requestAnimationFrame(animateStats)
  try {
    const r = await client.get(`/profiles/${userStore.userId}/intake`)
    canAssess.value = !!r.data.can_assess
  } catch { canAssess.value = true }
  loaded.value = true
})
</script>

<style scoped lang="scss">
@use '@/styles/tokens.scss' as *;
/* 总览页铺满内容区：与顶栏共用同一条左右基准线（28px） */
.home { display: flex; flex-direction: column; gap: 24px; width: 100%; }

/* 收紧首屏高度：留出固定约 130px 的"下一段预览"，让核心亮点那排卡片露出来 */
.hero { position: relative; display: flex; min-height: max(520px, calc(100vh - 272px));
  padding: 46px 60px 42px; overflow: hidden; color: #fff; border: none; border-radius: $radius-lg;
  background: linear-gradient(135deg, #1a6ae0 0%, #2f7ff0 50%, #4a8ff0 100%); }
.hero-inner { position: relative; z-index: 2; display: flex; flex-direction: column; justify-content: space-between;
  gap: 44px; width: 100%; }
.hero::after { content: ''; position: absolute; top: -60%; left: -40%; width: 40%; height: 220%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.12), transparent);
  transform: translate3d(0, 0, 0) rotate(18deg); will-change: transform;
  animation: heroShine 13s ease-in-out infinite; pointer-events: none; }
@keyframes heroShine { 0%, 52% { transform: translate3d(0, 0, 0) rotate(18deg); } 88%, 100% { transform: translate3d(400%, 0, 0) rotate(18deg); } }
.hero-body { max-width: 1000px; }
/* 半透明云纹铺满 hero：这张素材自带一层均匀薄纱，云形很淡，是想要的观感，别去扣它 */
.hero-yun { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover;
  object-position: center; opacity: 0.24; pointer-events: none;
  animation: cloudFloat 24s ease-in-out infinite; }
@keyframes cloudFloat { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-8px); } }
.hero-title { margin: 0 0 18px; font-size: clamp(42px, 3.6vw, 58px); font-weight: 900; line-height: 1.24;
  letter-spacing: .5px; text-shadow: 0 2px 18px rgba(0, 20, 60, 0.25); }
.hero-desc { font-size: 17px; line-height: 1.85; color: rgba(255,255,255,0.88); max-width: 860px; }
.hero-actions { margin-top: 28px; display: flex; gap: 12px; align-items: center; }
.hero-actions .tc-btn { background: #fff; color: $color-primary; }
.hero-actions .tc-btn:hover { background: $color-primary-soft; }
.hero-actions .tc-btn.ghost { background: rgba(255,255,255,0.12); color: #fff; border-color: rgba(255,255,255,0.5); }
.hero-cta { position: relative; }
.hero-cta.locked, .hero-cta.locked:hover { background: rgba(255,255,255,0.14); color: rgba(255,255,255,0.66);
  cursor: not-allowed; border: 1px solid rgba(255,255,255,0.28); box-shadow: none; }
.hero-hint { margin-top: 14px; font-size: 14.5px; line-height: 1.7; color: rgba(255,255,255,0.74); }

/* 首屏事实带：真实产品指标，不是装饰数字 */
.hero-facts { display: grid; grid-template-columns: repeat(4, 1fr); gap: 28px;
  padding-top: 26px; border-top: 1px solid rgba(255, 255, 255, 0.22); }
.fact-num { font-size: 46px; font-weight: 800; line-height: 1.05; animation: numIn .8s cubic-bezier(.25,.8,.4,1) both; }
.fact-num i { font-style: normal; font-size: 18px; font-weight: 600; margin-left: 4px; opacity: .82; }
@keyframes numIn { from { opacity: 0; transform: scale(.6); } to { opacity: 1; transform: scale(1); } }
.fact-label { margin-top: 8px; font-size: 17px; font-weight: 700; }
.fact-note { margin-top: 5px; font-size: 15px; line-height: 1.5; color: rgba(255, 255, 255, 0.68); }

.block { display: flex; flex-direction: column; gap: 12px; }
.block-head { font-size: 22px; font-weight: 800; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.hl { padding: 22px 22px 24px; display: flex; flex-direction: column; gap: 10px; transition: all .16s ease; }
.hl:hover { box-shadow: $shadow-hover; transform: translateY(-2px); }
.hl-icon { width: 38px; height: 38px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
  background: $color-primary-soft; color: $color-primary; transition: transform .28s cubic-bezier(.34,1.56,.64,1); }
.hl:hover .hl-icon { transform: scale(1.14) rotate(-5deg); }
.hl-title { font-size: 19px; font-weight: 700; }
.hl-desc { font-size: 16px; line-height: 1.75; color: $color-text-secondary; }
</style>
