import { beforeEach, describe, expect, it } from 'vitest'
import {
  byokHeaders,
  clearByokKey,
  getByokConfig,
  getByokKey,
  hasByokKey,
  setByokConfig,
  setByokKey,
} from './byok'

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

  it('自选模型与网关地址随请求头下发，并去掉地址尾部斜杠', () => {
    setByokConfig({ key: 'sk-x', model: 'gpt-4o', baseUrl: 'https://api.openai.com/v1///' })
    expect(byokHeaders()).toEqual({
      'X-BYOK-Key': 'sk-x',
      'X-BYOK-Model': 'gpt-4o',
      'X-BYOK-Base-URL': 'https://api.openai.com/v1',
    })
    expect(getByokConfig()).toEqual({ key: 'sk-x', model: 'gpt-4o', baseUrl: 'https://api.openai.com/v1' })
  })

  it('模型/地址留空时不发对应请求头（兼容仅填 Key）', () => {
    setByokConfig({ key: 'sk-x', model: '', baseUrl: '' })
    expect(byokHeaders()).toEqual({ 'X-BYOK-Key': 'sk-x' })
  })

  it('兼容旧版裸 Key 存储', () => {
    sessionStorage.setItem('mx_byok_key', 'sk-legacy')
    expect(getByokKey()).toBe('sk-legacy')
    expect(byokHeaders()).toEqual({ 'X-BYOK-Key': 'sk-legacy' })
  })
})
