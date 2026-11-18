import { describe, expect, it } from 'vitest'
import {
  buildRightsDeclaration,
  canConfirmRights,
  readRememberedBasis,
  rememberBasis,
  RIGHTS_BASES,
} from './rightsDeclaration'

describe('canConfirmRights', () => {
  it('两个勾选都为真才放行', () => {
    expect(canConfirmRights(false, false)).toBe(false)
    expect(canConfirmRights(true, false)).toBe(false)
    expect(canConfirmRights(false, true)).toBe(false)
    expect(canConfirmRights(true, true)).toBe(true)
  })
})

describe('buildRightsDeclaration', () => {
  it('未勾选时不生成声明', () => {
    expect(
      buildRightsDeclaration({ basis: 'own', rightsConfirmed: false, aiNoticeAck: true, note: 'x' }),
    ).toBeNull()
  })

  it('生成可信结构：两个 must-be-true 字段固定为 true', () => {
    const result = buildRightsDeclaration({
      basis: 'authorized',
      rightsConfirmed: true,
      aiNoticeAck: true,
      note: '合同编号 ABC-123',
    })
    expect(result).toEqual({
      basis: 'authorized',
      rights_confirmed: true,
      ai_notice_ack: true,
      note: '合同编号 ABC-123',
    })
  })

  it('note 去空白，空串转 null（与服务端 Optional[str] 对齐）', () => {
    const blank = buildRightsDeclaration({
      basis: 'own', rightsConfirmed: true, aiNoticeAck: true, note: '   ',
    })
    expect(blank?.note).toBeNull()
  })

  it('basis 只接受白名单值，非法值回退 own', () => {
    const result = buildRightsDeclaration({
      basis: 'unknown' as never,
      rightsConfirmed: true,
      aiNoticeAck: true,
      note: '',
    })
    expect(result?.basis).toBe('own')
  })

  it('三个 basis 枚举与服务端对齐', () => {
    expect(RIGHTS_BASES.map((b) => b.key)).toEqual(['own', 'authorized', 'public_domain'])
  })
})

describe('basis 本地记忆', () => {
  // node 环境无 localStorage：用最小 Storage 实现验证读写与降级
  function memoryStore(): Storage {
    const map = new Map<string, string>()
    return {
      get length() { return map.size },
      clear: () => map.clear(),
      getItem: (k: string) => map.get(k) ?? null,
      key: (i: number) => Array.from(map.keys())[i] ?? null,
      removeItem: (k: string) => { map.delete(k) },
      setItem: (k: string, v: string) => { map.set(k, v) },
    }
  }

  it('无记录时回退 own', () => {
    expect(readRememberedBasis(memoryStore())).toBe('own')
  })

  it('记住后可读回，并支持覆盖更新', () => {
    const store = memoryStore()
    rememberBasis('authorized', store)
    expect(readRememberedBasis(store)).toBe('authorized')
    rememberBasis('public_domain', store)
    expect(readRememberedBasis(store)).toBe('public_domain')
  })

  it('被篡改成非法值时回退 own，不再污染后续调用', () => {
    const store = memoryStore()
    store.setItem('moxie:rights-basis', 'everything_is_mine')
    expect(readRememberedBasis(store)).toBe('own')
  })

  it('只持久化 basis 本身，不写勾选或备注', () => {
    const store = memoryStore()
    rememberBasis('authorized', store)
    expect(store.length).toBe(1)
    expect(store.getItem('moxie:rights-basis')).toBe('authorized')
  })

  it('非法 basis 不写入存储', () => {
    const store = memoryStore()
    rememberBasis('evil' as never, store)
    expect(store.length).toBe(0)
  })

  it('存储不可用/抛异常时静默降级，不影响主流程', () => {
    const broken = {
      getItem: () => { throw new Error('blocked') },
      setItem: () => { throw new Error('quota') },
    } as unknown as Storage
    expect(readRememberedBasis(broken)).toBe('own')
    expect(() => rememberBasis('authorized', broken)).not.toThrow()
    expect(readRememberedBasis(null)).toBe('own')
    expect(() => rememberBasis('authorized', null)).not.toThrow()
  })
})
