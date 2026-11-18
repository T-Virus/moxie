import { describe, expect, it } from 'vitest'
import { trimPayload } from './api'

describe('admin trimPayload', () => {
  it('去掉用户标识、备注等短文本首尾空白', () => {
    expect(trimPayload({ identity: '  admin@example.com ', note: '  已处理  ' })).toEqual({
      identity: 'admin@example.com',
      note: '已处理',
    })
  })

  it('保留密钥与通知正文的原始空白', () => {
    const payload = {
      secret: '  keep-me  ',
      content: '\n多行正文\n',
      body: '  通知正文  ',
      prompt: '  提示词  ',
    }
    expect(trimPayload(payload)).toEqual(payload)
  })
})
