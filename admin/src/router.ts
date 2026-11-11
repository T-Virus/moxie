import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { ensureSession, notifyLoginNotice } from './auth'
import { can } from './roles'
import { getRole, loadSession } from './session'
import { setDenial } from './guard'
import type { Permission } from './roles'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('./views/Login.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: () => import('./components/AppShell.vue'),
    children: [
      { path: '', redirect: '/overview' },
      {
        path: 'overview',
        component: () => import('./views/Overview.vue'),
        meta: { title: '概览', permission: 'users:read' },
      },
      {
        path: 'users',
        component: () => import('./views/Users.vue'),
        meta: { title: '用户管理', permission: 'users:read' },
      },
      {
        path: 'subscriptions',
        component: () => import('./views/Subscriptions.vue'),
        meta: { title: '订阅与权益', permission: 'subscriptions:read' },
      },
      {
        path: 'orders',
        component: () => import('./views/Orders.vue'),
        meta: { title: '订单与退款', permission: 'orders:read' },
      },
      {
        path: 'invoices',
        component: () => import('./views/Invoices.vue'),
        meta: { title: '发票', permission: 'invoices:read' },
      },
      {
        path: 'reconcile',
        component: () => import('./views/Reconcile.vue'),
        meta: { title: '对账', permission: 'reconcile:read' },
      },
      {
        path: 'tasks',
        component: () => import('./views/TaskBoard.vue'),
        meta: { title: '任务看板', permission: 'tasks:read' },
      },
      {
        path: 'alerts',
        component: () => import('./views/Alerts.vue'),
        meta: { title: '告警与通知', permission: 'alerts:read' },
      },
      {
        path: 'audit',
        component: () => import('./views/AuditLogs.vue'),
        meta: { title: '审计日志', permission: 'audit:read' },
      },
      {
        path: 'forbidden',
        component: () => import('./views/Forbidden.vue'),
        meta: { title: '权限不足', public: true },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/overview' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) {
    if (to.path === '/login' && loadSession()) return '/overview'
    return true
  }
  const ready = await ensureSession()
  if (!ready) {
    notifyLoginNotice('请先登录管理后台')
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  const permission = to.meta.permission as Permission | undefined
  if (permission && !can(getRole(), permission)) {
    setDenial(to.path, permission)
    return '/forbidden'
  }
  return true
})

export default router
