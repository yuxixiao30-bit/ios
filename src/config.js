import { readFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { md5 } from './protocol.js'

const here = path.dirname(fileURLToPath(import.meta.url))
export const projectRoot = path.resolve(here, '..')

/**
 * 当前网页客户端走 Cloudflare 的 443（wss）。
 * 早年的 ws://m*.iirose.com:8777 直连端口已经关了，留着只作兼容尝试。
 */
export const DEFAULT_ENDPOINTS = [
  'wss://m1.iirose.com',
  'wss://m8.iirose.com',
  'wss://m9.iirose.com',
  'wss://m1.iirose.com:443',
  'ws://m.iirose.com:8777',
]

const defaults = {
  endpoints: DEFAULT_ENDPOINTS,
  username: '',
  uid: '',
  passwordMd5: '',
  roomId: '',
  roomPassword: '',
  lastRoomId: '',
  status: 'n',
  signature: '',
  greeting: '',
  controlPort: 0,
  apiKey: '',
  apiBase: 'https://api.deepseek.com',
  aiEnabled: false,
  model: 'deepseek-chat',
  temperature: 1.1,
  maxTokens: 120,
  replyCooldownMs: 4000,
  maxRepliesPerHour: 60,
  ambientEnabled: false,
  ambientChance: 0.18,
  ambientCooldownMs: 25000,
  ambientMinChars: 3,
  followupWindow: 5,
  followupMaxChain: 12,
  followName: '',
  followDelayMs: 1500,
  commandPrefix: '/',
  replyToOwner: true,
  ignoreSelf: true,
  heartbeatMs: 30000,
  timeoutMs: 8000,
  loginTimeoutMs: 20000,
  reconnectDelayMs: 3000,
  maxRetries: 20,
  debug: false,
  maxHistory: 200,
}

/** 32 位十六进制：当作已经是 MD5 */
const MD5_RE = /^[a-f0-9]{32}$/i

export async function loadConfig(file = path.join(projectRoot, 'config.json')) {
  if (!existsSync(file)) {
    throw new Error(`找不到配置文件 ${file}，先复制 config.example.json 为 config.json 再填`)
  }
  const raw = JSON.parse(await readFile(file, 'utf8'))
  const config = { ...defaults, ...raw }

  // 环境变量覆盖，便于不把口令写进文件
  config.username = process.env.IIROSE_USERNAME || config.username
  config.uid = process.env.IIROSE_UID || config.uid
  config.roomId = process.env.IIROSE_ROOM_ID || config.roomId
  const envPwd = process.env.IIROSE_PASSWORD
  if (envPwd) config.passwordMd5 = envPwd

  if (!config.username) throw new Error('配置缺少 username（不带 [**] 标记）')
  if (!config.uid) throw new Error('配置缺少 uid（13 位唯一标识）')
  if (!config.passwordMd5) throw new Error('配置缺少 passwordMd5；也可以直接填 password，程序会自己算 MD5')
  if (!config.roomId) throw new Error('配置缺少 roomId')

  // 允许直接写明文 password，这里统一转成 MD5
  if (raw.password && !config.passwordMd5) config.passwordMd5 = raw.password
  if (!MD5_RE.test(config.passwordMd5)) config.passwordMd5 = await md5(config.passwordMd5)

  if (!Array.isArray(config.endpoints) || config.endpoints.length === 0) {
    config.endpoints = DEFAULT_ENDPOINTS
  }
  return config
}
