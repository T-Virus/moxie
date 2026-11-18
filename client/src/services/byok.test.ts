import { beforeEach, describe, expect, it } from 'vitest'
import { byokHeaders, clearByokKey, getByokKey, hasByokKey, setByokKey } from './byok'

class MemoryStorage {
  private data = new Map<string, string>()

  get length(): number {
    return this.data.size
  }

  clear(): void {
    this.data.clear()
  }

  getItem(key: string): string | null {
    return this.data.get(key) ?? null
  }

  key(index: number): string | null {
    return Array.from(this.data.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.data.delete(key)
  }

  setItem(key: string, value: string): void {
    this.data.set(key, value)
  }
}

describe('BYOK 会话存储', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'sessionStorage', {
      value: new MemoryStorage(),
      configurable: true,
      writable: true,
    })
  })

  it('只接受非空 Key，并 trim 首尾空白', () => {
    setByokKey('   ')
    expect(hasByokKey()).toBe(false)
    setByokKey('  sk-test-123  ')
    expect(getByokKey()).toBe('sk-test-123')
  })

  it('清除后不再产生请求头', () => {
    setByokKey('sk-test-123')
    expect(byokHeaders()).toEqual({ 'X-BYOK-Key': 'sk-test-123' })
    clearByokKey()
    expect(byokHeaders()).toEqual({})
    expect(hasByokKey()).toBe(false)
  })
})
