/**
 * 应用层载荷加密：ECDH(P-256) + HKDF-SHA256 + AES-256-GCM。
 * 与服务端约定的 AAD：
 *   请求：`METHOD\nPATH?QUERY\nKEY_ID`
 *   响应：请求 AAD + `\nresponse`
 */
const HKDF_INFO = 'moxie-api-payload-v1'
const NONCE_LEN = 12
const encoder = new TextEncoder()

export interface PayloadSession {
  key: CryptoKey
  keyId: string
  clientKey: string
}

let publicKeyUrl = '/v1/crypto/public-key'
let sessionPromise: Promise<PayloadSession> | null = null

export function configurePayloadCrypto(url: string): void {
  publicKeyUrl = url
  sessionPromise = null
}

export function resetPayloadCrypto(): void {
  sessionPromise = null
}

function b64urlEncode(bytes: Uint8Array): string {
  let binary = ''
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function b64urlDecode(text: string): Uint8Array<ArrayBuffer> {
  const normalized = text.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

function aadFor(
  session: PayloadSession,
  method: string,
  pathWithQuery: string,
): Uint8Array<ArrayBuffer> {
  return encoder.encode(`${method.toUpperCase()}\n${pathWithQuery}\n${session.keyId}`)
}

async function createSession(): Promise<PayloadSession> {
  if (typeof crypto === 'undefined' || !crypto.subtle) {
    throw new Error('当前环境不支持 WebCrypto，无法建立加密会话')
  }
  const response = await fetch(publicKeyUrl, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    credentials: 'omit',
  })
  if (!response.ok) throw new Error('无法获取服务端加密公钥')
  const data = (await response.json()) as { key_id?: string; public_key?: string }
  if (!data.key_id || !data.public_key) throw new Error('服务端加密公钥格式不正确')

  const serverKey = await crypto.subtle.importKey(
    'spki',
    b64urlDecode(data.public_key),
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    [],
  )
  const pair = (await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' },
    false,
    ['deriveBits'],
  )) as CryptoKeyPair
  const clientSpki = new Uint8Array(await crypto.subtle.exportKey('spki', pair.publicKey))
  const shared = await crypto.subtle.deriveBits(
    { name: 'ECDH', public: serverKey },
    pair.privateKey,
    256,
  )
  const hkdfKey = await crypto.subtle.importKey('raw', shared, 'HKDF', false, ['deriveKey'])
  const key = await crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt: encoder.encode(data.key_id),
      info: encoder.encode(HKDF_INFO),
    },
    hkdfKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
  return { key, keyId: data.key_id, clientKey: b64urlEncode(clientSpki) }
}

export function getPayloadSession(): Promise<PayloadSession> {
  if (!sessionPromise) {
    sessionPromise = createSession().catch((error) => {
      sessionPromise = null
      throw error
    })
  }
  return sessionPromise
}

export function payloadHeaders(
  session: PayloadSession,
  nonce?: string,
): Record<string, string> {
  const headers: Record<string, string> = {
    'X-Payload-Key': session.keyId,
    'X-Payload-Client': session.clientKey,
  }
  if (nonce) {
    headers['X-Payload-Nonce'] = nonce
    headers['X-Payload-Encrypted'] = '1'
  }
  return headers
}

export async function encryptJson(
  session: PayloadSession,
  method: string,
  pathWithQuery: string,
  body: string,
): Promise<{ body: Uint8Array<ArrayBuffer>; nonce: string }> {
  const nonce = crypto.getRandomValues(new Uint8Array(NONCE_LEN))
  const ciphertext = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce, additionalData: aadFor(session, method, pathWithQuery) },
    session.key,
    encoder.encode(body),
  )
  return { body: new Uint8Array(ciphertext), nonce: b64urlEncode(nonce) }
}

export async function decryptJson(
  session: PayloadSession,
  method: string,
  pathWithQuery: string,
  nonceText: string,
  data: ArrayBuffer,
): Promise<string> {
  const nonce = b64urlDecode(nonceText)
  const aad = encoder.encode(
    `${method.toUpperCase()}\n${pathWithQuery}\n${session.keyId}\nresponse`,
  )
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: nonce, additionalData: aad },
    session.key,
    data,
  )
  return new TextDecoder('utf-8').decode(plain)
}
