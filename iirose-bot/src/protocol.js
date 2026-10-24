import { gzipSync, gunzipSync } from 'node:zlib'

/** 压缩阈值：超过该字节数的上行报文会用 0x01 前缀 + gzip 打包 */
export const COMPRESS_THRESHOLD = 256

/** 下行：0x01 开头说明是 gzip 压缩体，其余按 UTF-8 原文 */
export function decodePacket(buffer) {
  const buf = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer)
  if (buf.length === 0) return ''
  if (buf[0] === 0x01) {
    try {
      return gunzipSync(buf.subarray(1)).toString('utf8')
    } catch {
      return ''
    }
  }
  return buf.toString('utf8')
}

/** 上行：长报文压缩，短报文原样发送 */
export function encodePacket(text) {
  const raw = Buffer.from(text, 'utf8')
  if (raw.length <= COMPRESS_THRESHOLD) return raw
  return Buffer.concat([Buffer.from([0x01]), gzipSync(raw)])
}

const md5HexCache = new Map()

/** 密码 -> 32 位小写 MD5（登录用） */
export async function md5(text) {
  if (md5HexCache.has(text)) return md5HexCache.get(text)
  const { createHash } = await import('node:crypto')
  const hex = createHash('md5').update(text, 'utf8').digest('hex')
  md5HexCache.set(text, hex)
  return hex
}

/**
 * 登录报文：'*' + JSON
 *
 * 真实的字段是短键（跟网页客户端一致），不是 username/password/roomId：
 *   r  房间 ID
 *   n  用户名
 *   p  密码的 MD5
 *   st 状态码（n 在线 / 8 离开 / 1 忙碌）
 *   mo 签名
 *   mb 空串
 *   mu '01'
 *   lr 上一次所在房间（用于正确退出旧房间，可省略）
 *   rp 房间密码（可省略）
 *   fp '@' + md5(用户名)，客户端指纹
 */
export async function buildLogin({ username, passwordMd5, roomId, status, signature, lastRoomId, roomPassword }) {
  const payload = {
    r: roomId,
    n: username,
    p: passwordMd5,
    st: status ?? 'n',
    mo: signature ?? '',
    mb: '',
    mu: '01',
    fp: '@' + (await md5(username)),
  }
  if (lastRoomId) payload.lr = lastRoomId
  if (roomPassword) payload.rp = roomPassword
  return '*' + JSON.stringify(payload)
}

/**
 * 登录响应判定。
 *
 * 实测：登录成功返回 `%*"` 紧跟一包几百 KB 的初始化数据（房间表/用户表/历史）。
 * 失败则是很短的 `%*"2` 之类。所以用长度区分，不能只看前缀。
 */
export function parseLoginResponse(text) {
  if (!text.startsWith('%')) return null
  if (!text.startsWith('%*')) return { ok: false, code: text.slice(1, 3) || 'unknown', raw: text.slice(0, 32) }
  if (text.length > 1024) return { ok: true, init: text.slice(3) }
  return { ok: false, code: text.slice(3, 4) || 'short', raw: text.slice(0, 32) }
}

/**
 * 下行包常以一个双引号开头（分帧残留），先削掉再分流。
 */
export function normalizeIncoming(text) {
  let s = String(text || '')
  while (s.startsWith('"')) s = s.slice(1)
  return s
}

/** 初始化包拆分：'%' 起始，'"' 分段 —— [0]=用户表 [1]=房间表 [2]=资源/历史 */
export function splitInitPacket(init) {
  const parts = init.split('"')
  return {
    users: parts[0] || '',
    rooms: parts[1] || '',
    extras: parts.slice(2).join('"') || '',
    partCount: parts.length,
    raw: init,
  }
}

/** 公共频道消息（下行）：时间戳>头像>用户名>内容>发送者>接收者>类型>>房间>... */
export function parseChatMessage(text) {
  const parts = text.split('>')
  if (parts.length < 7) return null
  return {
    timestamp: Number(parts[0]) || 0,
    avatar: parts[1] || '',
    name: parts[2] || '',
    content: parts[3] || '',
    senderId: parts[4] || '',
    receiverId: parts[5] || '',
    type: parts[6] || '',
    roomId: parts[8] || '',
    raw: text,
  }
}

/** 系统事件：>'1 进房 / >'2 离房（实测标记位于第 4 段，uid 在第 9 段） */
export function parseSystemEvent(text) {
  const parts = text.split('>')
  const marker = parts[3] || ''
  if (marker.startsWith("'1")) {
    return { kind: 'member-added', roomOrAvatar: parts[1] || '', name: parts[2] || '', uid: parts[8] || '' }
  }
  if (marker.startsWith("'2")) {
    return {
      kind: 'member-removed',
      roomOrAvatar: parts[1] || '',
      name: parts[2] || '',
      uid: parts[8] || '',
      targetRoom: parts[10] || '',
    }
  }
  return null
}

/** 上行：公共消息 */
export function buildChat(text, uid, id = String(Date.now())) {
  return JSON.stringify({ m: text, mc: uid, i: id })
}

/** 上行：私聊 */
export function buildPrivate(groupId, text, uid, id = String(Date.now())) {
  return JSON.stringify({ g: groupId, m: text, mc: uid, i: id })
}

/** 上行：切房间 */
export function buildMoveRoom(roomId) {
  return 'm' + roomId
}

/** 上行：当前房间成员列表 */
export function buildUserList() {
  return 'r2'
}

/** 上行：查用户资料 */
export function buildProfile(name) {
  return '+-' + name
}

/** 上行：点赞 / 点踩 / 关注 */
export function buildLike(uid, note = '') {
  return '+*' + uid + (note ? ' ' + note : '')
}

export function buildDislike(uid, note = '') {
  return '+!' + uid + (note ? ' ' + note : '')
}

export function buildFollow(uid, on = true) {
  return '+#' + (on ? '0' : '1') + ' ' + uid
}

/** 上行：撤回（频道消息） */
export function buildRecall(msgId) {
  return 'v0#' + msgId
}

/** 上行：广播（需要手机绑定） */
export function buildBroadcast(text, uid) {
  return '~' + JSON.stringify({ t: text, c: uid, v: 0 })
}

/**
 * 把下行正文里的控制标记清干净：
 * [*用户名*] 提及、[_房间_*] 频道引用、(_hr)…(hr_) 引用块
 */
export function cleanContent(text) {
  return String(text || '')
    .replace(/\(\s*_hr\s*\)([\s\S]*?)\(\s*hr_\s*\)/g, '')
    .replace(/\[\*([^*]*)\*\]/g, '@$1')
    .replace(/\[_([^_]*)_\]/g, '#$1')
    .replace(/\s+/g, ' ')
    .trim()
}

/** 消息 id：与网页客户端/适配器一致，12 位随机数字 */
export function nextMessageId() {
  return String(Math.random()).slice(2, 14).padEnd(12, '0')
}
