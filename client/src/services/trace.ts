/**
 * 端到端链路 ID：同一浏览器会话共用一个 32 位 trace-id，每次请求生成新 span-id。
 * 服务端 request_context 会解析 traceparent、回写 X-Trace-Id，日志与前端错误上报即可串联。
 */

const TRACE_KEY = 'mx_trace_id'
const HEX = '0123456789abcdef'
let fallbackTraceId = ''

function randomHex(bytes: number): string {
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const values = new Uint8Array(bytes)
    crypto.getRandomValues(values)
    return Array.from(values, (value) => HEX[value >> 4] + HEX[value & 15]).join('')
  }
  let out = ''
  for (let i = 0; i < bytes * 2; i += 1) out += HEX[Math.floor(Math.random() * 16)]
  return out
}

export function currentTraceId(): string {
  try {
    const stored = sessionStorage.getItem(TRACE_KEY) || ''
    if (/^[0-9a-f]{32}$/i.test(stored)) return stored.toLowerCase()
    const trace = randomHex(16)
    sessionStorage.setItem(TRACE_KEY, trace)
    return trace
  } catch {
    // 无 sessionStorage 的测试/隐私模式：进程内保持稳定即可
    if (!fallbackTraceId) fallbackTraceId = randomHex(16)
    return fallbackTraceId
  }
}

export function resetTraceId(): void {
  fallbackTraceId = ''
  try {
    sessionStorage.removeItem(TRACE_KEY)
  } catch {
    /* 忽略无存储环境 */
  }
}

export function traceHeaders(): Record<string, string> {
  const trace = currentTraceId()
  return {
    'X-Trace-Id': trace,
    Traceparent: `00-${trace}-${randomHex(8)}-01`,
  }
}
