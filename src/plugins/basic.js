/**
 * 内置命令集。
 *
 * 每个 handler 收到 { bot, message, args }：
 *   bot     IroseBot 实例
 *   message 下行消息（name / content / senderId …）
 *   args    命令名之后按空白切开的参数
 */
/**
 * 唯一标识在房间里常以 [@5efc5d6adced4@] 这种带标记的形式出现，
 * 这里统一剥成纯 ID，纯 ID 也照常收。
 */
function normalizeUid(raw) {
  return String(raw || '')
    .trim()
    .replace(/^\[\s*@?/, '')
    .replace(/@?\s*\]$/, '')
    .trim()
}

export function registerBasicCommands(registry, config = {}) {
  const isOwner = (message) => {
    if (!config.ownerUid) return true
    return message.senderId === config.ownerUid
  }

  registry.add('ping', async ({ bot, message }) => {
    bot.reply(message.name, 'pong')
  }, { description: '测活' })

  registry.add('help', async ({ bot, message }) => {
    const names = registry.list().map((c) => c.name).join(' ')
    bot.reply(message.name, `可用命令：${names}`)
  }, { aliases: ['帮助'], description: '列出命令' })

  registry.add('status', async ({ bot, message }) => {
    const up = Math.floor(process.uptime() / 60)
    bot.reply(message.name, `在线 ${up} 分钟，房间 ${bot.roomId}，账号 ${bot.name}(${bot.uid})`)
  }, { aliases: ['状态'], description: '运行状态' })

  registry.add('say', async ({ bot, message, args }) => {
    if (!isOwner(message)) return bot.reply(message.name, '这个只有主人能用')
    const text = args.join(' ').trim()
    if (!text) return bot.reply(message.name, '说点什么')
    bot.say(text)
  }, { aliases: ['说'], description: '让机器人说话（主人）' })

  registry.add('like', async ({ bot, message, args }) => {
    const uid = normalizeUid(args[0])
    const note = args.slice(1).join(' ')
    if (!uid) return bot.reply(message.name, `用法：${registry.prefix}like <唯一标识> [备注]`)
    bot.like(uid, note)
  }, { aliases: ['赞'], description: '点赞' })

  registry.add('follow', async ({ bot, message, args }) => {
    const uid = normalizeUid(args[0])
    if (!uid) return bot.reply(message.name, `用法：${registry.prefix}follow <唯一标识>`)
    bot.follow(uid, true)
  }, { aliases: ['关注'], description: '关注某人' })

  registry.add('move', async ({ bot, message, args }) => {
    if (!isOwner(message)) return bot.reply(message.name, '这个只有主人能用')
    const roomId = args[0]
    if (!roomId) return bot.reply(message.name, `用法：${registry.prefix}move <roomId>`)
    bot.moveRoom(roomId)
  }, { aliases: ['切'], description: '换房间（主人）' })

  registry.add('recent', async ({ bot, message, args }) => {
    const n = Math.min(Number(args[0]) || 5, 20)
    const lines = bot.recent(n).map((m) => `${m.name}: ${m.content}`.slice(0, 80))
    bot.reply(message.name, lines.length ? lines.join(' | ') : '还没有消息')
  }, { aliases: ['最近'], description: '看最近几条消息' })

  return registry
}
