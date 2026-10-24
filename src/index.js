import { PersonaAI, mentionsMe } from './ai.js'
import { IroseBot } from './bot.js'
import { IiroseClient } from './client.js'
import { CommandRegistry } from './commands.js'
import { loadConfig } from './config.js'
import { registerBasicCommands } from './plugins/basic.js'

const config = await loadConfig()
const client = new IiroseClient(config)
const bot = new IroseBot(client, { maxHistory: config.maxHistory })
const registry = new CommandRegistry({ prefix: config.commandPrefix })
registerBasicCommands(registry, config)

let ai = null
if (config.aiEnabled && config.apiKey) {
  ai = new PersonaAI({
    apiKey: config.apiKey,
    apiBase: config.apiBase,
    model: config.model,
    temperature: config.temperature,
    maxTokens: config.maxTokens,
    family: config.family || [],
  })
  console.log(`[iirose] 对话模型已接：${config.model}`)
}

let lastReplyAt = 0
let repliesThisHour = 0
let hourStart = Date.now()

client.on('ready', () => {
  console.log(`[iirose] 已上线：${bot.name} (${bot.uid}) 房间 ${bot.roomId}`)
  if (config.greeting) {
    setTimeout(() => {
      try {
        bot.say(config.greeting)
        console.log(`[iirose] 打了个招呼：${config.greeting}`)
      } catch (err) {
        console.error('[iirose] 招呼没说出去：', err.message)
      }
    }, 2000)
  }
})

client.on('close', (why) => {
  console.warn(`[iirose] ${why}`)
  client.scheduleReconnect()
})

client.on('giveup', () => {
  console.error('[iirose] 重连次数用尽，退出')
  process.exit(1)
})

bot.on('member-added', (ev) => {
  if (config.debug) console.log(`[iirose] ${ev.name} 进入房间`)
})

bot.on('member-removed', (ev) => {
  if (config.debug) console.log(`[iirose] ${ev.name} 离开房间`)
})

const recentLines = []
let lastAmbientAt = 0

/** 纯链接、纯表情包、太短的就别接话了 */
function worthTalking(content) {
  const text = String(content || '').trim()
  if (!text) return false
  if (text.length < (config.ambientMinChars ?? 3)) return false
  if (/^https?:\/\//.test(text)) return false
  if (/#e$/.test(text)) return false
  return /[\u4e00-\u9fa5A-Za-z]/.test(text)
}

bot.on('message', async (message) => {
  if (config.ignoreSelf && message.senderId === bot.uid) return
  if (config.debug) console.log(`[iirose] ${message.name}: ${message.content}`)

  recentLines.push(`${message.name}：${message.content}`.slice(0, 120))
  if (recentLines.length > 12) recentLines.shift()

  try {
    const handled = await registry.handle(bot, message)
    if (handled) return
    if (!ai) return

    const now = Date.now()
    const mentioned = mentionsMe(message.content, bot.name)
    const ambient = !mentioned
      && config.ambientEnabled
      && now - lastAmbientAt > (config.ambientCooldownMs ?? 25000)
      && worthTalking(message.content)
      && Math.random() < (config.ambientChance ?? 0.18)

    if (!mentioned && !ambient) return
    if (now - lastReplyAt < (config.replyCooldownMs ?? 4000)) return
    if (now - hourStart > 3600 * 1000) {
      hourStart = now
      repliesThisHour = 0
    }
    if (repliesThisHour >= (config.maxRepliesPerHour ?? 60)) {
      console.warn('[iirose] 本小时回复次数到顶，先歇着')
      return
    }
    lastReplyAt = now
    repliesThisHour += 1
    if (ambient) lastAmbientAt = now

    const text = await ai.reply(message, recentLines.slice(-8))
    bot.say(text)
    console.log(`[iirose] ${ambient ? '插话' : '回'} ${message.name}：${text}`)
  } catch (err) {
    console.error('[iirose] 处理消息失败：', err.message)
  }
})

process.on('SIGINT', () => {
  console.log('\n[iirose] 收到 Ctrl+C，断开连接')
  client.close()
  process.exit(0)
})

/**
 * 本地控制口（默认关闭）：让外部脚本能指挥机器人说话，不用另开一条连接。
 *   POST /say   {"text":"..."}
 *   POST /room  {"roomId":"..."}
 *   GET  /status
 */
if (config.controlPort > 0) {
  const { createServer } = await import('node:http')
  const server = createServer((req, res) => {
    const send = (code, obj) => {
      res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify(obj))
    }
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      let body = {}
      if (chunks.length) {
        try {
          body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        } catch {
          return send(400, { ok: false, error: 'body 不是合法 JSON' })
        }
      }
      try {
        if (req.method === 'GET' && req.url === '/status') {
          return send(200, { ok: true, online: client.ready, name: bot.name, uid: bot.uid, roomId: bot.roomId })
        }
        if (req.method === 'POST' && req.url === '/say') {
          if (!body.text) return send(400, { ok: false, error: '缺 text' })
          bot.say(String(body.text))
          return send(200, { ok: true })
        }
        if (req.method === 'POST' && req.url === '/room') {
          if (!body.roomId) return send(400, { ok: false, error: '缺 roomId' })
          bot.moveRoom(String(body.roomId))
          return send(200, { ok: true })
        }
        return send(404, { ok: false, error: '没有这个接口' })
      } catch (err) {
        return send(500, { ok: false, error: err.message })
      }
    })
  })
  server.listen(config.controlPort, '127.0.0.1', () => {
    console.log(`[iirose] 控制口开了：http://127.0.0.1:${config.controlPort}`)
  })
}

console.log('[iirose] 连接中…')
try {
  await client.connect()
} catch (err) {
  console.error(`[iirose] 首次连接失败：${err.message}`)
  process.exit(1)
}
