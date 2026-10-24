/**
 * 极简命令注册表。
 *
 * 一条下行消息长这样：{ name, content, senderId, ... }
 * 命令就是"正文以 prefix 开头"的那种消息。
 */
export class CommandRegistry {
  constructor({ prefix = '/', onUnknown } = {}) {
    this.prefix = prefix
    this.commands = new Map()
    this.onUnknown = onUnknown
  }

  add(name, handler, { aliases = [], description = '' } = {}) {
    const entry = { name, handler, description, aliases }
    this.commands.set(name, entry)
    for (const alias of aliases) this.commands.set(alias, entry)
    return this
  }

  list() {
    const seen = new Set()
    const out = []
    for (const entry of this.commands.values()) {
      if (seen.has(entry.name)) continue
      seen.add(entry.name)
      out.push(entry)
    }
    return out
  }

  /** 返回 true 表示这条消息被当成命令处理了 */
  async handle(bot, message) {
    const text = String(message.content || '')
    if (!text.startsWith(this.prefix)) return false
    const body = text.slice(this.prefix.length).trim()
    if (!body) return false
    const [name, ...rest] = body.split(/\s+/)
    const entry = this.commands.get(name)
    if (!entry) {
      this.onUnknown?.(bot, message, name)
      return true
    }
    await entry.handler({ bot, message, args: rest, command: entry })
    return true
  }
}
