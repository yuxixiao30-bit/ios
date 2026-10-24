import { IroseBot } from '../src/bot.js'
import { IiroseClient } from '../src/client.js'
import { loadConfig } from '../src/config.js'

/**
 * 端到端自检：登录 -> 等 2 秒 -> 在房间里说一句话 -> 收 8 秒消息 -> 退出
 */
const config = { ...(await loadConfig()), debug: false }
const client = new IiroseClient(config)
const bot = new IroseBot(client)

client.on('message', (msg) => {
  console.log(`[收] ${msg.name}: ${msg.content}`)
})
client.on('member-added', (ev) => console.log(`[进] ${ev.name}`))
client.on('member-removed', (ev) => console.log(`[出] ${ev.name}`))
client.on('unknown', (text) => console.log(`[?] ${text.slice(0, 80)}`))

await client.connect()
console.log(`[在线] ${bot.name} (${bot.uid}) 房间 ${bot.roomId}`)
await new Promise((r) => setTimeout(r, 2000))

const text = '测试一下，机器人上线了'
console.log(`[发] ${text}`)
bot.say(text)

await new Promise((r) => setTimeout(r, 8000))
client.close()
process.exit(0)
