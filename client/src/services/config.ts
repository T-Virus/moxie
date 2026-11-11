/** 环境配置集中在这里：全部数据走在线服务端接口。 */
/** 开发期默认走 Vite 代理（/v1）；生产可配置完整地址，如 https://api.example.com/v1 */
export const API_BASE = (import.meta.env.VITE_API_BASE || '/v1').replace(/\/$/, '')

export const MAX_UPLOAD_MB = Number(import.meta.env.VITE_MAX_UPLOAD_MB || 20)

export const ACCEPTED_EXTENSIONS = ['.txt', '.md', '.markdown']
