/**
 * E2E 本地服务启动器。
 *
 * 流程：
 *   1. 在系统临时目录下建立一次性 MOBIT_ROOT（web/config/data/input/output 全部隔离）；
 *   2. 复制 web/dist 与 config/*，写入一本最小测试书；
 *   3. 用 python src/webapp.py 启动桌面端本地模式服务（不依赖真实云端、不读真实 data/）。
 *
 * 退出（SIGTERM/SIGINT/子进程退出）时删除临时根目录。
 */
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const REPO = path.resolve(import.meta.dirname, '..', '..')
const PORT = Number(process.env.E2E_PORT || process.env.MOBIT_PORT || 8797)
const ROOT = process.env.E2E_ROOT || fs.mkdtempSync(path.join(os.tmpdir(), 'moxie-e2e-'))
const BOOK = 'e2e-smoke-book'
const PYTHON = process.env.E2E_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')

let child = null
let cleaned = false

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true })
}

function prepareFixture() {
  if (!fs.existsSync(path.join(REPO, 'web', 'dist', 'index.html'))) {
    console.error('[e2e] 缺少 web/dist，请先在 web/ 执行 npm run build')
    process.exit(1)
  }

  ensureDir(path.join(ROOT, 'web'))
  fs.cpSync(path.join(REPO, 'web', 'dist'), path.join(ROOT, 'web', 'dist'), { recursive: true })

  const cfgDir = path.join(ROOT, 'config')
  ensureDir(cfgDir)
  for (const name of ['workflow.json', 'studio.json', 'sensitive_words.txt']) {
    const src = path.join(REPO, 'config', name)
    if (fs.existsSync(src)) fs.copyFileSync(src, path.join(cfgDir, name))
  }

  for (const name of ['input', 'output', 'data']) ensureDir(path.join(ROOT, name))

  const bookDir = path.join(ROOT, 'data', BOOK)
  ensureDir(bookDir)
  const storyBible = [
    '作品简介：E2E 冒烟测试用最小作品，只用于验证页面可加载、数据可渲染。',
    '题材与基调：都市异能 / 测试样例。',
    '',
    '人物卡片：',
    '- 姓名：林舟；性别：男；剧情功能：主角；人设倾向：守序善良；势力名称：青云宗；身份背景：外门弟子；性格：沉稳；动机目标：查明身世',
    '',
    '势力卡片：',
    '- 名称：青云宗；势力大类：宗门势力；类型：正道宗门；阵营：正派；立场：正面；简介：测试用势力',
  ].join('\n')

  const chapters = {
    story_bible: storyBible,
    status: '连载中',
    author: 'E2E',
    items: [],
    chapters: [
      {
        no: 1,
        chapter_id: '第1章',
        title: '山门试炼',
        roles: ['林舟'],
        factions: ['青云宗'],
        scene: '青云宗山门',
        summary: '林舟参加山门试炼，意外激活体内灵脉。',
        points: ['林舟抵达山门', '试炼中灵脉觉醒'],
      },
    ],
  }
  fs.writeFileSync(
    path.join(bookDir, 'chapters.json'),
    JSON.stringify(chapters, null, 2),
    'utf8',
  )
  // 作品详情页会预读首章正文；补一份原文避免 /api/output 404 干扰控制台断言
  ensureDir(path.join(bookDir, 'manuscript'))
  fs.writeFileSync(
    path.join(bookDir, 'manuscript', '001.txt'),
    '第一章 山门试炼\n\n林舟踏上青云宗山门的青石阶，晨雾里传来钟声。\n',
    'utf8',
  )
}

function removeTree(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true })
  } catch { /* 句柄可能延迟释放 */ }
  if (!fs.existsSync(dir)) return
  try {
    for (const child of fs.readdirSync(dir)) {
      fs.rmSync(path.join(dir, child), { recursive: true, force: true })
    }
    fs.rmdirSync(dir)
  } catch { /* 交给 globalTeardown 兜底 */ }
}

function cleanup() {
  if (cleaned) return
  cleaned = true
  removeTree(ROOT)
  if (fs.existsSync(ROOT)) {
    console.warn(`[e2e] 临时目录清理未完成（globalTeardown 会重试）：${ROOT}`)
  }
}

function stop(code = 0) {
  if (child && !child.killed) {
    try { child.kill() } catch { /* ignore */ }
  }
  cleanup()
  process.exit(code)
}

prepareFixture()

const env = {
  ...process.env,
  MOBIT_ROOT: ROOT,
  MOBIT_HOST: '127.0.0.1',
  MOBIT_PORT: String(PORT),
  MOBIT_NO_AUDIT: '1',
  PYTHONUNBUFFERED: '1',
}
// 强制走本地模式：不继承外部云端地址，避免测试打到真实服务
delete env.MOBIT_CLOUD_API

child = spawn(PYTHON, [path.join(REPO, 'src', 'webapp.py')], {
  cwd: REPO,
  env,
  stdio: 'inherit',
})

child.on('exit', (code) => {
  console.error(`[e2e] 本地服务退出（code=${code}）`)
  stop(code ?? 1)
})
child.on('error', (error) => {
  console.error('[e2e] 无法启动 python 本地服务：', error.message)
  stop(1)
})

process.on('SIGINT', () => stop(0))
process.on('SIGTERM', () => stop(0))
process.on('exit', cleanup)
