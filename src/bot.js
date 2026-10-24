import { EventEmitter } from 'node:events'
import {
  buildChat,
  buildDislike,
  buildFollow,
  buildLike,
  buildMoveRoom,
  buildPrivate,
  buildProfile,
  buildRecall,
  buildUserList,
  cleanContent,
  nextMessageId,
} from './protocol.js'

/**
 * 业务层：把协议动作包装成“人话”方法，并把收到的消息整理成可用的结构。
 */
export class IroseBot extends EventEmitter {
  constructor(client, options = {}) {
    super()
    this.client = client
    this.options = options
    this.roomId = client.self.roomId
    this.members = new Map()
    this.history = []
    this.maxHistory = options.maxHistory ?? 200

    client.on('ready', () => {
      this.emit('online', { uid: client.self.uid, name: client.self.name, roomId: this.roomId })
    })
    client.on('message', (msg) => this.onChat(msg))
    client.on('member-added', (ev) => {
      this.members.set(ev.name, ev.uid)
      this.emit('member-added', ev)
    })
    client.on('member-removed', (ev) => {
      this.members.delete(ev.name)
      this.emit('member-removed', ev)
    })
    client.on('close', (why) => this.emit('offline', why))
  }

  onChat(msg) {
    const cleaned = { ...msg, content: cleanContent(msg.content) }
    this.history.push(cleaned)
    if (this.history.length > this.maxHistory) this.history.shift()
    if (msg.senderId) this.members.set(msg.name, msg.senderId)
    this.emit('message', cleaned)
  }

  get uid() {
    return this.client.self.uid
  }

  get name() {
    return this.client.self.name
  }

  /** 当前房间发一句 */
  say(text) {
    return this.client.send(buildChat(text, this.uid, nextMessageId()))
  }

  /** 回给某个人（公开 @） */
  reply(toName, text) {
    return this.say(`[*${toName}*] ${text}`)
  }

  /** 私聊 */
  whisper(groupId, text) {
    return this.client.send(buildPrivate(groupId, text, this.uid, nextMessageId()))
  }

  /** 换房间（断线重连带新房间号，见 client.switchRoom） */
  moveRoom(roomId) {
    this.roomId = roomId
    if (typeof this.client.switchRoom === 'function') return this.client.switchRoom(roomId)
    return this.client.send(buildMoveRoom(roomId))
  }

  /** 取当前房间成员列表 */
  requestUserList() {
    return this.client.send(buildUserList())
  }

  /** 查某人资料 */
  profile(name) {
    return this.client.send(buildProfile(name))
  }

  like(uid, note = '') {
    return this.client.send(buildLike(uid, note))
  }

  dislike(uid, note = '') {
    return this.client.send(buildDislike(uid, note))
  }

  follow(uid, on = true) {
    return this.client.send(buildFollow(uid, on))
  }

  recall(messageId) {
    return this.client.send(buildRecall(messageId))
  }

  /** 最近 n 条消息 */
  recent(n = 10) {
    return this.history.slice(-n)
  }
}
