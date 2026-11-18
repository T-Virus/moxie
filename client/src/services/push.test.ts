import { describe, expect, it } from 'vitest'
import { pushSupported, safeNotificationPath, urlBase64ToUint8Array } from './push'

describe('Web Push 辅助', () => {
  it('node 环境（无 window/navigator）判定为不支持', () => {
    expect(pushSupported()).toBe(false)
  })

  it('base64url 公钥正确解码为字节数组', () => {
    // 'AQID' = [1, 2, 3]；'-_' 需要按 base64url 还原为 '+/' 
    expect(Array.from(urlBase64ToUint8Array('AQID'))).toEqual([1, 2, 3])
    expect(Array.from(urlBase64ToUint8Array('____'))).toEqual([255, 255, 255])
  })

  it('通知跳转只保留同源路径', () => {
    expect(safeNotificationPath('/runs?tab=all#top')).toBe('/runs?tab=all#top')
    expect(safeNotificationPath('https://evil.example/phish')).toBe('/')
    expect(safeNotificationPath('javascript:alert(1)')).toBe('/')
    expect(safeNotificationPath(null)).toBe('/')
    expect(safeNotificationPath('')).toBe('/')
  })
})
