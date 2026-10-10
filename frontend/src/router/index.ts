import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'home', component: () => import('@/views/HomeView.vue'), meta: { title: '总览', fullscreen: true } },

  // ── 学习做题 ──
  { path: '/learn', name: 'learn-map', component: () => import('@/views/learn/LearnMapView.vue'), meta: { title: '学习地图' } },
  { path: '/learn/bridge/:code?', name: 'learn-bridge', component: () => import('@/views/learn/CultureBridgeView.vue'), meta: { title: '文化桥' } },
  { path: '/learn/thread/:sp', name: 'learn-thread', component: () => import('@/views/learn/ThreadView.vue'), meta: { title: '技能点对话工作台' } },

  // ── 对话实战（13 步业务流 + vbooking 工作台操作面，二者并列）──
  { path: '/practice', name: 'practice', component: () => import('@/views/practice/PracticeView.vue'), meta: { title: '实战工作台' } },
  { path: '/practice/im', name: 'p-im', component: () => import('@/views/practice/ImView.vue'), meta: { title: '聊天界面' } },
  { path: '/practice/messages', name: 'p-messages', component: () => import('@/views/vbooking/MessagesView.vue'), meta: { title: '消息中心' } },
  // 旧的 vbooking 订单管理表已废弃：订单列表并入「订单管理」（/practice）
  { path: '/practice/orders', redirect: '/practice' },
  { path: '/practice/orders/:id', name: 'p-order-detail', component: () => import('@/views/vbooking/OrderDetailView.vue'), meta: { title: '订单详情' } },
  { path: '/practice/orders/:id/call', name: 'p-order-call', component: () => import('@/views/practice/CallView.vue'), meta: { title: '通话' } },
  { path: '/practice/orders/:id/score', name: 'p-order-score', component: () => import('@/views/practice/OrderScoreView.vue'), meta: { title: '订单评分复盘' } },
  { path: '/practice/orders/:id/deliverables', name: 'p-deliverables', component: () => import('@/views/practice/DeliverableWorkbenchView.vue'), meta: { title: '产出与投递' } },
  { path: '/practice/orders/:id/finance', name: 'p-finance', component: () => import('@/views/practice/FinanceView.vue'), meta: { title: '成本与结算' } },
  { path: '/practice/orders/:id/plan/new', name: 'p-plan-new', component: () => import('@/views/vbooking/PlanNewView.vue'), meta: { title: '创建方案' } },
  // 方案编辑已并入产出与投递：行程方案 = 逐日六要素编辑器（避免两处各维护一套行程表单）
  { path: '/practice/orders/:id/plan/edit', redirect: (to: any) => `/practice/orders/${to.params.id}/deliverables?code=itinerary` },

  // ── 训练反馈 ──
  { path: '/profile', name: 'profile', component: () => import('@/views/ProfileView.vue'), meta: { title: '学情画像' } },
  { path: '/profile/quiz', name: 'profile-quiz', component: () => import('@/views/ProfileQuizView.vue'), meta: { title: '初始画像测评' } },
  { path: '/score', name: 'score', component: () => import('@/views/ScoreView.vue'), meta: { title: '评分复盘' } },
  { path: '/toolbox', name: 'toolbox', component: () => import('@/views/ToolboxView.vue'), meta: { title: '工具台' } },
  { path: '/system', name: 'system', component: () => import('@/views/SystemStatusView.vue'), meta: { title: '系统状态' } },
]

export default createRouter({ history: createWebHashHistory(), routes })