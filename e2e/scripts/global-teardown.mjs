/**
 * Playwright globalTeardown：删除本次运行的临时根目录，并清理历史遗留（>10 分钟）。
 * Windows 下文件句柄可能延迟释放，所以带重试。
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

function removeTree(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true })
  } catch { /* retry below */ }
  if (!fs.existsSync(dir)) return true
  try {
    for (const child of fs.readdirSync(dir)) {
      fs.rmSync(path.join(dir, child), { recursive: true, force: true })
    }
    fs.rmdirSync(dir)
  } catch { /* retry below */ }
  return !fs.existsSync(dir)
}

async function removeWithRetry(dir) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (removeTree(dir)) return true
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  return false
}

export default async function globalTeardown() {
  const root = process.env.E2E_ROOT
  if (root) {
    if (!(await removeWithRetry(root))) {
      console.warn(`[e2e] 临时目录未能删除，可手动清理：${root}`)
    }
  }

  // 清理异常退出留下的空目录（只处理 10 分钟前的目录，避免影响并行运行）
  const cutoff = Date.now() - 10 * 60 * 1000
  const tmp = os.tmpdir()
  for (const name of fs.readdirSync(tmp)) {
    if (!name.startsWith('moxie-e2e-')) continue
    const dir = path.join(tmp, name)
    try {
      if (fs.statSync(dir).mtimeMs > cutoff) continue
      await removeWithRetry(dir)
    } catch { /* ignore */ }
  }
}
