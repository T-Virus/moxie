import { computed, onMounted, onUnmounted, ref } from 'vue'
import { listJobs } from '../api'
import type { JobSummary } from '../types'

/**
 * 多任务队列的全局共享状态。
 *
 * 侧边栏「任务中心」角标、右下角悬浮任务条、任务中心页都需要同一份 /api/jobs 结果，
 * 这里做单例轮询：谁挂载谁登记，最后一个卸载后自动停止定时器，
 * 避免三个地方各自发一轮同样的请求。
 */
const jobs = ref<JobSummary[]>([])
const running = ref(0)
const maxRunning = ref(8)   // 后端 MAX_RUNNING_TASKS：所有通道共用这一个额度
const ready = ref(false)
const lastError = ref('')

const INTERVAL = 1500
let timer: any = null
let users = 0

export async function refreshJobs() {
  try {
    const r = await listJobs()
    jobs.value = r.jobs
    running.value = r.running
    maxRunning.value = r.max_running
    lastError.value = ''
    ready.value = true
  } catch (e: any) {
    // 服务未就绪 / 旧版本后端：静默，保留上一份数据
    lastError.value = e?.message || '任务接口不可用'
  }
}

function acquire() {
  users++
  if (timer) return
  refreshJobs()
  timer = setInterval(refreshJobs, INTERVAL)
}

function release() {
  users = Math.max(0, users - 1)
  if (users === 0 && timer) {
    clearInterval(timer)
    timer = null
  }
}

export function useJobQueue() {
  onMounted(acquire)
  onUnmounted(release)
  return {
    jobs,
    running,
    maxRunning,
    ready,
    lastError,
    refresh: refreshJobs,
    runningJobs: computed(() => jobs.value.filter(j => j.running)),
  }
}
