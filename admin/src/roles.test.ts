import { describe, expect, it } from 'vitest'
import { can, hiddenNavLabels, visibleNav } from './roles'

describe('权限矩阵 can()', () => {
  it('admin 拥有读写全部权限', () => {
    expect(can('admin', 'users:write')).toBe(true)
    expect(can('admin', 'refunds:write')).toBe(true)
    expect(can('admin', 'model_config:write')).toBe(true)
    expect(can('admin', 'audit:read')).toBe(true)
    expect(can('admin', 'skills:read')).toBe(true)
    expect(can('admin', 'backup:write')).toBe(true)
    expect(can('admin', 'usage:read')).toBe(true)
  })

  it('support 只有读权限，没有写权限', () => {
    expect(can('support', 'users:read')).toBe(true)
    expect(can('support', 'audit:read')).toBe(true)
    expect(can('support', 'users:write')).toBe(false)
    expect(can('support', 'refunds:write')).toBe(false)
    expect(can('support', 'quota:write')).toBe(false)
    expect(can('support', 'model_config:write')).toBe(false)
    // 技能目录对两种后台角色都只读开放
    expect(can('support', 'skills:read')).toBe(true)
    expect(can('support', 'backup:read')).toBe(true)
    expect(can('support', 'backup:write')).toBe(false)
    expect(can('support', 'usage:read')).toBe(true)
  })

  it('无角色或未识别角色一律拒绝', () => {
    expect(can(null, 'users:read')).toBe(false)
    expect(can(undefined, 'users:read')).toBe(false)
    // 'user' 不在 ROLE_MAP 中，应安全拒绝（用断言模拟运行时传入的非法角色）
    expect(can('user' as never, 'users:read')).toBe(false)
  })
})

describe('菜单可见性', () => {
  it('admin 可见全部菜单，support 隐藏写权限菜单', () => {
    expect(visibleNav('admin').length).toBeGreaterThan(visibleNav('support').length)
    const supportPaths = visibleNav('support').map((item) => item.path)
    expect(supportPaths).toContain('/users')
    expect(supportPaths).toContain('/skills')
    expect(supportPaths).not.toContain('/model-configs')
    expect(hiddenNavLabels('admin')).toHaveLength(0)
    expect(hiddenNavLabels('support').length).toBeGreaterThan(0)
  })
})
