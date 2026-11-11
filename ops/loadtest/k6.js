// 墨写服务端基准压测（k6 版本）。与 locustfile.py 场景保持一致。
// 运行：
//   k6 run -e BASE_URL=http://127.0.0.1:8798 -e ACCOUNTS=10 ops/loadtest/k6.js
//
// 前置：服务端已用 SQLite + 本地存储启动（见 ops/loadtest/run_local.py）。
// 压测数据只落在服务端临时目录，不写项目 data/。

import http from 'k6/http'
import { check, sleep } from 'k6'

const BASE = (__ENV.BASE_URL || 'http://127.0.0.1:8798').replace(/\/$/, '')
const API = `${BASE}/v1`
const ACCOUNTS = Number(__ENV.ACCOUNTS || 10)
const PASSWORD = __ENV.PASSWORD || 'loadtest-password-123'

export const options = {
  scenarios: {
    baseline: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '10s', target: Number(__ENV.VUS || 10) },
        { duration: __ENV.HOLD || '20s', target: Number(__ENV.VUS || 10) },
        { duration: '5s', target: 0 },
      ],
    },
  },
  thresholds: {
    // 本地 SQLite 小规模基准的建议阈值（可按机器性能调整）
    http_req_failed: ['rate<0.01'],
    'http_req_duration{name:GET /v1/auth/me}': ['p(95)<150'],
    'http_req_duration{name:GET /v1/entitlements}': ['p(95)<200'],
    'http_req_duration{name:GET /v1/tasks/{id}}': ['p(95)<150'],
    'http_req_duration{name:POST /v1/tasks}': ['p(95)<400'],
  },
}

function jsonHeaders(token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

function setupAccount(index) {
  const email = `loadtest-${index}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
  const register = http.post(`${API}/auth/register`, JSON.stringify({ email, password: PASSWORD }), {
    headers: jsonHeaders(),
    tags: { name: 'POST /v1/auth/register' },
  })
  if (register.status !== 201) throw new Error(`register failed: ${register.status} ${register.body}`)
  const token = register.json('access_token')

  const subKey = `k6-sub-${index}-${Date.now()}`
  const sub = http.post(
    `${API}/subscriptions`,
    JSON.stringify({ plan_code: 'studio_byok', cycle: 'month', provider: 'mock' }),
    { headers: { ...jsonHeaders(token), 'Idempotency-Key': subKey }, tags: { name: 'POST /v1/subscriptions' } },
  )
  if (sub.status !== 201) throw new Error(`subscribe failed: ${sub.status} ${sub.body}`)
  const params = sub.json('payment.params')
  const webhook = http.post(`${BASE}${params.webhook_path}`, JSON.stringify(params.body), {
    headers: { 'Content-Type': 'application/json', 'x-mock-signature': params.signature },
    tags: { name: 'POST /v1/webhooks/mock' },
  })
  if (webhook.status !== 200) throw new Error(`webhook failed: ${webhook.status} ${webhook.body}`)

  const created = http.post(`${API}/tasks`, JSON.stringify({ type: 'decompose', params: {} }), {
    headers: { ...jsonHeaders(token), 'Idempotency-Key': `k6-seed-${index}-${Date.now()}` },
    tags: { name: 'POST /v1/tasks' },
  })
  if (created.status !== 201 && created.status !== 200) {
    throw new Error(`seed task failed: ${created.status} ${created.body}`)
  }
  const taskId = created.json('task.id')
  http.post(`${API}/tasks/${taskId}/cancel`, JSON.stringify({ reason: 'loadtest seed' }), {
    headers: jsonHeaders(token),
    tags: { name: 'POST /v1/tasks/{id}/cancel' },
  })
  return { token, taskId }
}

export function setup() {
  const accounts = []
  for (let i = 0; i < ACCOUNTS; i += 1) accounts.push(setupAccount(i))
  return { accounts }
}

export default function (data) {
  const account = data.accounts[__VU % data.accounts.length]
  const headers = jsonHeaders(account.token)

  const me = http.get(`${API}/auth/me`, { headers, tags: { name: 'GET /v1/auth/me' } })
  check(me, { 'auth/me 200': (r) => r.status === 200 })

  const quota = http.get(`${API}/entitlements`, { headers, tags: { name: 'GET /v1/entitlements' } })
  check(quota, { 'entitlements 200': (r) => r.status === 200 })

  const detail = http.get(`${API}/tasks/${account.taskId}`, {
    headers,
    tags: { name: 'GET /v1/tasks/{id}' },
  })
  check(detail, { 'task detail 200': (r) => r.status === 200 })

  const create = http.post(`${API}/tasks`, JSON.stringify({ type: 'decompose', params: {} }), {
    headers: { ...headers, 'Idempotency-Key': `k6-${__VU}-${Date.now()}-${Math.floor(Math.random() * 1e6)}` },
    tags: { name: 'POST /v1/tasks' },
  })
  check(create, { 'create task 2xx': (r) => r.status === 201 || r.status === 200 })
  if (create.status === 201 || create.status === 200) {
    http.post(`${API}/tasks/${create.json('task.id')}/cancel`, JSON.stringify({ reason: 'loadtest' }), {
      headers,
      tags: { name: 'POST /v1/tasks/{id}/cancel' },
    })
  }

  sleep(0.2)
}
