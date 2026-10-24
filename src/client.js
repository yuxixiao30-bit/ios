import { EventEmitter } from 'node:events'
import WebSocket from 'ws'
import {
  buildLogin,
  decodePacket,
  encodePacket,
  normalizeIncoming,
  parseChatMessage,
  parseLoginResponse,
  parseSystemEvent,
  splitInitPacket,
} from './protocol.js'

const LOGIN_CODES = {
  1: '账号或密码不对（也可能是游客模式被拒）',
  2: '密码错误（检查 passwordMd5 是否为密码的 32 位小写 MD5）',
  3: '用户不存在（检查 username，不要带 [**] 标记）',
  4: '房间不存在（检查 roomId）',
  5: '房间密码错误（需要 roomPassword）',
}

/**
 * 一条 IIROSE WebSocket 连接。
 *
 * 它只负责：连上去、登录、压包/解包、心跳、断线重连、把下行拆成事件。
 * 业务逻辑交给 bot.js。
 */
export class IiroseClient extends EventEmitter {
  constructor(config) {
    super()
    this.config = config
    this.ws = null
    this.ready = false
    this.retries = 0
    this.heartbeatTimer = null
    this.reconnectTimer = null
    this.closedByUser = false
    this.self = { uid: config.uid, name: config.username, roomId: config.roomId }
    this.loginResult = null
  }

  get endpoints() {
    return Array.isArray(this.config.endpoints) && this.config.endpoints.length
      ? this.config.endpoints
      : ['wss://m1.iirose.com']
  }

  log(...args) {
    if (this.config.debug) console.log('[iirose]', ...args)
  }

  /** 连接 + 登录，返回初始化包信息 */
  async connect() {
    this.closedByUser = false
    let lastError = null
    for (const url of this.endpoints) {
      try {
        const init = await this.connectOne(url)
        this.retries = 0
        return init
      } catch (err) {
        lastError = err
        this.log(`连接 ${url} 失败：${err.message}`)
      }
    }
    throw lastError || new Error('没有任何端点可用')
  }

  async connectOne(url) {
    const loginPacket = encodePacket(await buildLogin({
      username: this.config.username,
      passwordMd5: this.config.passwordMd5,
      roomId: this.config.roomId,
      status: this.config.status,
      signature: this.config.signature,
      lastRoomId: this.config.lastRoomId,
      roomPassword: this.config.roomPassword,
    }))

    return new Promise((resolve, reject) => {
      this.log('连接', url)
      const ws = new WebSocket(url, {
        handshakeTimeout: this.config.timeoutMs ?? 8000,
        perMessageDeflate: false,
      })
      this.ws = ws

      let settled = false
      let loginDone = false

      const timer = setTimeout(() => {
        if (settled || loginDone) return
        settled = true
        try {
          ws.terminate()
        } catch {}
        reject(new Error('登录超时（没有收到 % 开头的响应）'))
      }, this.config.loginTimeoutMs ?? 20000)

      const onOpen = () => {
        this.log('已连接，发送登录报文')
        ws.send(loginPacket)
      }

      const onMessage = (data) => {
        const text = decodePacket(data)

        // 登录阶段：等那个几百 KB 的 % 包
        if (!loginDone) {
          const login = parseLoginResponse(text)
          if (!login) {
            // 不是登录响应，按普通包处理
            this.emit('packet', text)
            this.dispatch(text)
            return
          }
          if (!login.ok) {
            const hint = LOGIN_CODES[Number(login.code)] || '未收录的错误'
            settled = true
            clearTimeout(timer)
            try {
              ws.terminate()
            } catch {}
            reject(new Error(`登录被拒绝（code=${login.code}）：${hint}`))
            return
          }
          loginDone = true
          settled = true
          clearTimeout(timer)
          this.ready = true
          this.loginResult = login
          this.startHeartbeat()
          const info = splitInitPacket(login.init)
          this.initInfo = info
          this.log(`登录成功，初始化包分段 ${info.partCount}，用户表 ${info.users.length} 字节`)
          resolve(info)
          return
        }

        // 登录之后：所有下行照常分发，监听器不能再摘掉
        this.emit('packet', text)
        this.dispatch(text)
      }

      const onError = (err) => {
        if (settled) {
          this.log('连接出错', err.message)
          return
        }
        settled = true
        clearTimeout(timer)
        reject(new Error(`连接错误：${err.message}`))
      }

      const onClose = (code, reason) => {
        this.ready = false
        this.stopHeartbeat()
        const why = `连接关闭（code=${code}${reason?.length ? '，' + reason.toString() : ''}）`
        if (!settled) {
          settled = true
          clearTimeout(timer)
          reject(new Error(why))
          return
        }
        this.emit('close', why)
      }

      ws.on('open', onOpen)
      ws.on('message', onMessage)
      ws.on('error', onError)
      ws.on('close', onClose)
    })
  }

  /** 下行分流：系统事件 / 聊天 / 其他 */
  dispatch(raw) {
    const text = normalizeIncoming(raw)
    if (!text) return
    if (text.startsWith('%')) {
      this.emit('login-packet', text)
      return
    }
    if (text.includes('>')) {
      const event = parseSystemEvent(text)
      if (event) {
        this.emit(event.kind, event)
        return
      }
      const chat = parseChatMessage(text)
      if (chat) {
        this.emit('message', chat)
        return
      }
    }
    this.emit('unknown', text)
  }

  /** 发送原始上行文本（自动压包） */
  send(text) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('未连接，无法发送')
    }
    const packet = encodePacket(text)
    this.ws.send(packet)
    this.log('发送', text.slice(0, 120))
    return packet.length
  }

  startHeartbeat() {
    this.stopHeartbeat()
    const ms = this.config.heartbeatMs ?? 30000
    if (ms <= 0) return
    this.heartbeatTimer = setInterval(() => {
      try {
        if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(encodePacket(''))
      } catch (err) {
        this.log('心跳失败', err.message)
      }
    }, ms)
  }

  stopHeartbeat() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer)
    this.heartbeatTimer = null
  }

  /** 断线后按指数退避重试 */
  scheduleReconnect(onReconnect) {
    if (this.closedByUser) return
    const max = this.config.maxRetries ?? 20
    if (this.retries >= max) {
      this.emit('giveup')
      return
    }
    this.retries += 1
    const base = this.config.reconnectDelayMs ?? 3000
    const delay = Math.min(base * 2 ** (this.retries - 1), 60000)
    this.log(`${delay}ms 后重连（第 ${this.retries}/${max} 次）`)
    clearTimeout(this.reconnectTimer)
    this.reconnectTimer = setTimeout(() => {
      this.connect().then((info) => onReconnect?.(info)).catch((err) => {
        this.log('重连失败', err.message)
        this.scheduleReconnect(onReconnect)
      })
    }, delay)
  }

  close() {
    this.closedByUser = true
    this.stopHeartbeat()
    clearTimeout(this.reconnectTimer)
    try {
      this.ws?.close()
    } catch {}
    this.ws = null
    this.ready = false
  }
}
