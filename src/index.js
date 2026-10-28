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

// 跟着谁换房间
let followTarget = null

registry.add('跟随', async ({ bot, message }) => {
  followTarget = { name: message.name, uid: message.senderId }
  bot.reply(message.name, '行，你走哪我跟哪。')
}, { aliases: ['followme'], description: '跟着你换房间' })

registry.add('别跟', async ({ bot, message }) => {
  const had = followTarget
  followTarget = null
  bot.reply(message.name, had ? '行，不跟了。' : '本来也没跟着谁。')
}, { aliases: ['stopfollow'], description: '不再跟着你' })

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
// 自己说完话后要盯的后续消息条数，以及这轮已经接了几次
let followWindow = 0
let chain = 0

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

if (config.debug) {
  client.on('unknown', (text) => console.log('[raw]', text.slice(0, 220)))
}

bot.on('member-added', (ev) => {
  if (config.debug) console.log(`[iirose] ${ev.name} 进入房间`)
})

bot.on('member-removed', (ev) => {
  if (config.debug) {
    console.log(`[iirose] ${ev.name} 离开房间${ev.targetRoom ? ' → ' + ev.targetRoom : ''}`)
    console.log('[leave raw]', (ev.raw || '').slice(0, 260))
  }

  if (!followTarget || ev.name !== followTarget.name) return

  const target = ev.targetRoom || extractRoomId(ev.raw)
  if (!target || target === bot.roomId) return

  setTimeout(() => {
    try {
      bot.moveRoom(target)
      console.log(`[iirose] 跟随 ${followTarget.name} → ${target}`)
    } catch (err) {
      console.error('[iirose] 跟随失败：', err.message)
    }
  }, 1200)
})

const recentLines = []
let lastAmbientAt = 0

const IMG_RE = /https?:\/\/[^\s"'<>]+\.(?:jpe?g|png|gif|webp)(?:[^\s"'<>]*)?/i

/** 发言里带的图 */
function extractImage(content) {
  const m = String(content || '').match(IMG_RE)
  return m ? m[0] : null
}

/**
 * 从初始化包里找某个人当前在哪个房间。
 * 用户记录的格式是 ...>用户名>名字颜色>房间ID>状态>...，取名字后面第一个 13 位 ID。
 */
function findRoomOf(raw, name) {
  if (!raw || !name) return null
  const idx = raw.indexOf('>' + name + '>')
  if (idx < 0) return null
  const seg = raw.slice(idx + name.length + 2, idx + name.length + 160)
  const m = seg.match(/([0-9a-f]{13})/i)
  return m ? m[1] : null
}

/** 离开包里可能带目标房间：'3<房间ID> 或 3<房间ID>；uid 也是 13 位，不能乱认 */
function extractRoomId(raw) {
  if (!raw) return null
  const m = raw.match(/'3([0-9a-f]{13})/i) || raw.match(/(?:^|>)3([0-9a-f]{13})(?:<|$)/i)
  return m ? m[1] : null
}

/** 纯链接、纯表情包、太短的就别接话了；带图的仍然算有话可说 */
function worthTalking(content) {
  if (extractImage(content)) return true
  const text = String(content || '').trim()
  if (!text) return false
  if (text.length < (config.ambientMinChars ?? 3)) return false
  if (/^https?:\/\//.test(text)) return false
  if (/#e$/.test(text)) return false
  return /[\u4e00-\u9fa5A-Za-z]/.test(text)
}

bot.on('message', async (message) => {
  if (config.ignoreSelf && message.senderId === bot.uid) return
  const img = extractImage(message.content)
  if (config.debug) console.log(`[iirose] ${message.name}${img ? '（图）' : ''}: ${message.content}`)

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

    // 自己刚说完话：后面这几条里找有没有能接下去的钩子
    let continuation = 0
    if (!mentioned && !ambient && followWindow > 0 && chain < (config.followupMaxChain ?? 12)) {
      followWindow -= 1
      continuation = chain
    }

    if (!mentioned && !ambient && !continuation) return
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

    const text = await ai.reply(
      { ...message, content: img ? message.content.replace(img, '[图片]') : message.content },
      recentLines.slice(-8),
      img,
      { continuation },
    )

    if (!text) {
      // 模型判断没钩子，这轮就断了
      console.log(`[iirose] ${message.name} 这条没钩子，不接`)
      if (followWindow <= 0) chain = 0
      return
    }

    bot.say(text)
    console.log(`[iirose] ${ambient ? '插话' : continuation ? '接话' : '回'} ${message.name}${img ? '（带图）' : ''}：${text}`)
    followWindow = config.followupWindow ?? 5
    chain = continuation ? chain + 1 : 1
  } catch (err) {
    console.error('[iirose] 处理消息失败：', err.message)
  }
})

process.on('SIGINT', () => {
  console.log('\n[iirose] 收到 Ctrl+C，断开连接')
  client.close()
  process.exit(0)
})

// 别因为一个没接住的 Promise 就把整个进程带走
process.on('unhandledRejection', (err) => {
  console.error('[iirose] 未处理的异步错误：', err?.message || err)
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
    req.on('end', async () => {
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
        if (req.method === 'GET' && req.url.startsWith('/where')) {
          const name = new URL(req.url, 'http://127.0.0.1').searchParams.get('name')
          const roomId = findRoomOf(client.initInfo?.raw || '', name)
          return send(200, { ok: true, name, roomId })
        }
        if (req.method === 'POST' && req.url === '/raw') {
          if (!body.text) return send(400, { ok: false, error: '缺 text' })
          client.send(String(body.text))
          return send(200, { ok: true })
        }
        if (req.method === 'POST' && req.url === '/say') {
          if (!body.text) return send(400, { ok: false, error: '缺 text' })
          bot.say(String(body.text))
          return send(200, { ok: true })
        }
        if (req.method === 'POST' && req.url === '/room') {
          if (!body.roomId) return send(400, { ok: false, error: '缺 roomId' })
          await bot.moveRoom(String(body.roomId))
          return send(200, { ok: true, roomId: bot.roomId })
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
for (;;) {
  try {
    await client.connect()
    break
  } catch (err) {
    const wait = config.startupRetryMs ?? 30000
    console.error(`[iirose] 首次连接失败：${err.message}，${wait / 1000} 秒后重试`)
    await new Promise((resolve) => setTimeout(resolve, wait))
  }
}
