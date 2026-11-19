import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '../..')
const serverDir = path.join(root, 'server')
const tmp = mkdtempSync(path.join(tmpdir(), 'moxie-online-e2e-'))
const dbPath = path.join(tmp, 'e2e.db').replace(/\\/g, '/')
const artifactDir = path.join(tmp, 'artifacts')
const port = process.env.MOXIE_E2E_SERVER_PORT || '18000'

const env = {
  ...process.env,
  ENV: 'dev',
  LICENSE_ALLOW_EPHEMERAL_KEY: 'true',
  REDIS_ENABLED: 'false',
  SCHEDULER_ENABLED: 'false',
  AUTO_CREATE_TABLES: 'true',
  DATABASE_URL: `sqlite:///${dbPath}`,
  STORAGE_BACKEND: 'local',
  STORAGE_LOCAL_DIR: artifactDir,
  PAYLOAD_ENCRYPTION_ENABLED: 'true',
  PAYLOAD_ENCRYPTION_REQUIRED: 'true',
  LEGAL_GATE_ENABLED: 'false',
  EMAIL_VERIFICATION_REQUIRED: 'false',
  PAYMENTS_MOCK_ENABLED: 'true',
  MOCK_PAYMENT_SECRET: 'online-e2e-mock-secret',
  MODEL_STUB: 'true',
  // E2E 只验证主链交互，不触发真实出图/外部图片服务
  AGENT_COVER_AUTO_GENERATE: 'false',
  TRUST_PROXY: 'false',
  BOOTSTRAP_ADMIN_EMAILS: '',
}

// 供 spec 侧执行 bootstrap CLI 时复用同一套环境变量。
writeFileSync(path.join(root, 'client', '.e2e-online-env.json'), JSON.stringify(env, null, 2))

const venvPython = path.join(serverDir, '.venv', 'Scripts', 'python.exe')
const command = process.platform === 'win32' && existsSync(venvPython) ? venvPython : 'python'

const child = spawn(command, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port], {
  cwd: serverDir,
  env,
  stdio: ['ignore', 'pipe', 'pipe'],
})

child.stdout?.on('data', (chunk) => process.stdout.write(`[server] ${chunk}`))
child.stderr?.on('data', (chunk) => process.stderr.write(`[server] ${chunk}`))

let stopped = false
function stop(code = 0) {
  if (stopped) return
  stopped = true
  child.kill('SIGTERM')
  setTimeout(() => child.kill('SIGKILL'), 2000).unref()
  process.exit(code)
}
process.on('SIGTERM', () => stop(0))
process.on('SIGINT', () => stop(0))
child.on('exit', (code) => stop(code ?? 1))

const deadline = Date.now() + 90_000
while (Date.now() < deadline) {
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/healthz`)
    if (resp.ok) {
      console.log('[e2e] online server ready')
      break
    }
  } catch {
    // wait
  }
  await new Promise((resolve) => setTimeout(resolve, 300))
}

if (Date.now() >= deadline) {
  console.error('[e2e] online server did not become ready')
  stop(1)
}
