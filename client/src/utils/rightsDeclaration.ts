/** 合规声明纯逻辑：与 UI 解耦，便于在 node 环境单测。 */
import type { RightsDeclaration } from '@/types'

export type RightsBasis = RightsDeclaration['basis']

export interface RightsChoice {
  basis: RightsBasis
  rightsConfirmed: boolean
  aiNoticeAck: boolean
  note: string
}

export const RIGHTS_BASES: Array<{ key: RightsBasis; label: string; desc: string }> = [
  { key: 'own', label: '自有作品', desc: '本人创作，或已取得完整著作权' },
  { key: 'authorized', label: '已获授权', desc: '有书面授权或合同，允许改编' },
  { key: 'public_domain', label: '公有领域', desc: '作者逝世满 50 年等可自由改编' },
]

/** 只记住权利来源枚举本身，绝不持久化勾选状态或授权凭证备注。 */
const REMEMBER_KEY = 'moxie:rights-basis'

function isBasis(value: unknown): value is RightsBasis {
  return RIGHTS_BASES.some((b) => b.key === value)
}

/** 隐私模式 / SSR / 存储被禁用时返回 null，调用方按「未记住」处理。 */
function defaultStore(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

/** 读取上次确认过的权利来源；无记录或被篡改时回退 own。 */
export function readRememberedBasis(store: Storage | null = defaultStore()): RightsBasis {
  if (!store) return 'own'
  try {
    const raw = store.getItem(REMEMBER_KEY)
    return isBasis(raw) ? raw : 'own'
  } catch {
    return 'own'
  }
}

/** 写入权利来源；仅在用户确认后调用，取消不改记忆。失败静默。 */
export function rememberBasis(basis: RightsBasis, store: Storage | null = defaultStore()): void {
  if (!isBasis(basis) || !store) return
  try {
    store.setItem(REMEMBER_KEY, basis)
  } catch {
    // 配额满 / 隐私模式：不影响主流程
  }
}

/** 两个勾选项必须都为 true 才能继续。 */
export function canConfirmRights(rightsConfirmed: boolean, aiNoticeAck: boolean): boolean {
  return rightsConfirmed && aiNoticeAck
}

/**
 * 构造随加密 body 提交的结构化声明；未确认时返回 null。
 * note 去空白，空串转 null（与服务端 Optional[str] 对齐，避免留空字符串）。
 */
export function buildRightsDeclaration(choice: RightsChoice): RightsDeclaration | null {
  if (!canConfirmRights(choice.rightsConfirmed, choice.aiNoticeAck)) return null
  const basis = RIGHTS_BASES.some((b) => b.key === choice.basis) ? choice.basis : 'own'
  const note = choice.note.trim()
  return {
    basis,
    rights_confirmed: true,
    ai_notice_ack: true,
    note: note || null,
  }
}
