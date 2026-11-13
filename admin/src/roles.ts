import type { Role } from './types'

export type Permission =
  | 'users:read' | 'users:write'
  | 'subscriptions:read' | 'subscriptions:write' | 'quota:write'
  | 'orders:read' | 'refunds:read' | 'refunds:write'
  | 'invoices:read' | 'invoices:write'
  | 'reconcile:read' | 'reconcile:write'
  | 'tasks:read' | 'tasks:write'
  | 'alerts:read' | 'notifications:write'
  | 'audit:read'
  | 'model_config:read' | 'model_config:write'
  | 'offline_package:read' | 'offline_package:write'

const ADMIN_PERMISSIONS: Permission[] = [
  'users:read', 'users:write',
  'subscriptions:read', 'subscriptions:write', 'quota:write',
  'orders:read', 'refunds:read', 'refunds:write',
  'invoices:read', 'invoices:write',
  'reconcile:read', 'reconcile:write',
  'tasks:read', 'tasks:write',
  'alerts:read', 'notifications:write',
  'audit:read',
  'model_config:read', 'model_config:write',
  'offline_package:read', 'offline_package:write',
]

const SUPPORT_PERMISSIONS: Permission[] = [
  'users:read',
  'subscriptions:read',
  'orders:read', 'refunds:read',
  'invoices:read',
  'reconcile:read',
  'tasks:read',
  'alerts:read',
  'audit:read',
]

const ROLE_MAP: Record<Role, Permission[]> = {
  admin: ADMIN_PERMISSIONS,
  support: SUPPORT_PERMISSIONS,
}

export function can(role: Role | null | undefined, permission: Permission): boolean {
  if (!role) return false
  return ROLE_MAP[role]?.includes(permission) ?? false
}

export interface NavItem {
  path: string
  label: string
  permission: Permission
  group: string
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/overview', label: '概览', permission: 'users:read', group: '工作台' },
  { path: '/users', label: '用户管理', permission: 'users:read', group: '业务管理' },
  { path: '/subscriptions', label: '订阅与权益', permission: 'subscriptions:read', group: '业务管理' },
  { path: '/orders', label: '订单与退款', permission: 'orders:read', group: '业务管理' },
  { path: '/invoices', label: '发票', permission: 'invoices:read', group: '业务管理' },
  { path: '/reconcile', label: '对账', permission: 'reconcile:read', group: '业务管理' },
  { path: '/tasks', label: '任务看板', permission: 'tasks:read', group: '运维监控' },
  { path: '/alerts', label: '告警与通知', permission: 'alerts:read', group: '运维监控' },
  { path: '/model-configs', label: '模型配置', permission: 'model_config:read', group: '运维监控' },
  { path: '/offline-packages', label: '离线安装包', permission: 'offline_package:read', group: '运维监控' },
  { path: '/audit', label: '审计日志', permission: 'audit:read', group: '运维监控' },
]

export function visibleNav(role: Role | null): NavItem[] {
  return NAV_ITEMS.filter(item => can(role, item.permission))
}

export function hiddenNavLabels(role: Role | null): string[] {
  return NAV_ITEMS.filter(item => !can(role, item.permission)).map(item => item.label)
}

export const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  support: '客服 / 支持',
  user: '普通用户',
}
