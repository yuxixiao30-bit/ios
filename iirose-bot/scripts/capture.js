import { IiroseClient } from '../src/client.js'
import { loadConfig } from '../src/config.js'

/**
 * 抓包：把所有下行都打出来，看看聊天消息到底有没有到。
 * 用法：node scripts/capture.js [秒数] [房间ID]
 */
const seconds = Number(process.argv[2] || 60)
const roomOverride = process.argv[3]
const config = await loadConfig()
if (roomOverride) config.roomId = roomOverride
const client = new IiroseClient({ ...config, debug: true })

let count = 0
client.on('packet', (text) => {
  count += 1
  console.log(`#${count} len=${text.length} ${JSON.stringify(text.slice(0, 140))}`)
})

await client.connect()
console.log(`已登录，房间 ${config.roomId}，开始抓 ${seconds} 秒…`)

await new Promise((r) => setTimeout(r, seconds * 1000))
console.log(`抓包结束，共 ${count} 条下行`)
client.close()
process.exit(0)
