import { IroseBot } from '../src/bot.js'
import { IiroseClient } from '../src/client.js'
import { loadConfig } from '../src/config.js'

/**
 * 只做「连接 + 登录 + 看初始化包」，不发任何消息。
 * 用来确认账号、房间、端点都对。
 */
const config = { ...(await loadConfig()), debug: true }
const client = new IiroseClient(config)
const bot = new IroseBot(client)

let closed = false
const finish = (code) => {
  if (closed) return
  closed = true
  client.close()
  setTimeout(() => process.exit(code), 200)
}
setTimeout(() => {
  console.error('登录测试超时')
  finish(1)
}, 45000)

try {
  const info = await client.connect()
  console.log('\n登录成功')
  console.log('  账号：', bot.name, `(${bot.uid})`)
  console.log('  房间：', config.roomId)
  console.log('  初始化包：', `用户表 ${info.users.length} 字节 / 房间表 ${info.rooms.length} 字节 / 分段 ${info.partCount}`)
  console.log('  用户表开头：', info.users.slice(0, 120))

  // 挂 3 秒收几条推送看看
  client.on('message', (msg) => console.log(`  收到 ${msg.name}: ${msg.content.slice(0, 50)}`))
  client.on('member-added', (ev) => console.log(`  ${ev.name} 进入房间`))
  client.on('member-removed', (ev) => console.log(`  ${ev.name} 离开房间`))
  await new Promise((r) => setTimeout(r, 3000))
  finish(0)
} catch (err) {
  console.error('登录失败：', err.message)
  finish(1)
}
