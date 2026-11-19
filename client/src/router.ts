import { createRouter, createWebHistory } from 'vue-router'
import { hasSession } from '@/services/http'
// 首屏落地页静态导入，保证首页最快；其余视图按需加载，避免全部打进一个 chunk。
import Home from '@/views/Home.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Home },
    { path: '/login', name: 'login', component: () => import('@/views/Auth.vue') },
    { path: '/verify-email', name: 'verify-email', component: () => import('@/views/VerifyEmail.vue') },
    // 重置密码全链路公开访问：邮件链接携带 token，无需登录
    {
      path: '/forgot-password',
      name: 'forgot-password',
      component: () => import('@/views/ForgotPassword.vue'),
    },
    {
      path: '/reset-password',
      name: 'reset-password',
      component: () => import('@/views/ResetPassword.vue'),
    },
    // /plans 自身有未登录访客态（登录/注册引导），保持公开，不用守卫拦截。
    { path: '/plans', name: 'plans', component: () => import('@/views/Plans.vue') },
    { path: '/runs', name: 'runs', component: () => import('@/views/Runs.vue'), meta: { requiresAuth: true } },
    {
      path: '/runs/:id',
      name: 'workspace',
      component: () => import('@/views/Workspace.vue'),
      props: true,
      meta: { requiresAuth: true },
    },
    { path: '/tools', name: 'tools', component: () => import('@/views/Tools.vue'), meta: { requiresAuth: true } },
    { path: '/skills', name: 'skills', component: () => import('@/views/Skills.vue'), meta: { requiresAuth: true } },
    {
      path: '/account',
      name: 'account-settings',
      component: () => import('@/views/AccountSettings.vue'),
      meta: { requiresAuth: true },
    },
    { path: '/legal', name: 'legal', component: () => import('@/views/Legal.vue') },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('@/views/NotFound.vue') },
  ],
})

// 受保护路由统一拦截：未登录跳登录页并带 next 回跳，避免各视图自理导致深链先闪现错误态。
// 真正的权限与资源归属仍由后端 API 兜底，这里只改善体验与一致性。
router.beforeEach((to) => {
  if (to.meta.requiresAuth && !hasSession()) {
    return { name: 'login', query: { next: to.fullPath } }
  }
  return true
})

export default router
