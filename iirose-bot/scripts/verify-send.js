import { IiroseClient } from '../src/client.js'
import { loadConfig } from '../src/config.js'
import { buildChat, nextMessageId } from '../src/protocol.js'

/**
 * 投递验证：说一句话 -> 断开 -> 重新登录 -> 在初始化包里找这句话。
 * 服务端不回显自己的消息，所以用"重连后历史里有没有"来证明真的发出去了。
 */
const config = await loadConfig()
const marker = '自检' + Math.random().toString(36).slice(2, 8)

const first = new IiroseClient(config)
await first.connect()
first.send(buildChat(marker, config.uid, nextMessageId()))
console.log('已发送标记：', marker)
await new Promise((r) => setTimeout(r, 3000))
first.close()

await new Promise((r) => setTimeout(r, 1000))
const second = new IiroseClient(config)
const info = await second.connect()
second.close()

const idx = info.raw ? info.raw.indexOf(marker) : -1
console.log(idx >= 0 ? `✅ 初始化包里找到标记（偏移 ${idx}）` : '❌ 初始化包里没找到标记')
process.exit(idx >= 0 ? 0 : 1)
