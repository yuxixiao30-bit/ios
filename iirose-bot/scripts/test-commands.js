import { CommandRegistry } from '../src/commands.js'
import { registerBasicCommands } from '../src/plugins/basic.js'

/**
 * 离线自检命令分发，不连服务器。
 */
const calls = []
const fakeBot = {
  name: '限',
  uid: '61f03365a2ad5',
  roomId: '5ce6a4b520a90',
  reply: (to, text) => calls.push(['reply', to, text]),
  say: (text) => calls.push(['say', text]),
  like: (uid, note) => calls.push(['like', uid, note]),
  dislike: (uid, note) => calls.push(['dislike', uid, note]),
  follow: (uid) => calls.push(['follow', uid]),
  moveRoom: (room) => calls.push(['move', room]),
  recent: (n) => [{ name: '甲', content: '你好' }].slice(0, n),
}

const registry = new CommandRegistry({ prefix: '/' })
registerBasicCommands(registry, { ownerUid: '61f03365a2ad5' })

const run = async (content, senderId = '61f03365a2ad5') => {
  calls.length = 0
  const handled = await registry.handle(fakeBot, { content, name: '甲', senderId })
  const out = calls.map((c) => c.join(' | ')).join(' ;; ')
  console.log(`${handled ? '✔' : '✘'} ${content.padEnd(18)} -> ${out || '(无输出)'}`)
  return handled
}

await run('/ping')
await run('/help')
await run('/status')
await run('/like 68af217fea585 不错')
await run('/move 679a51f1d4893')
await run('/move 679a51f1d4893', '别人')
await run('/say 大家好')
await run('/say 大家好', '别人')
await run('/recent 3')
await run('今天天气不错')
console.log('\n命令总数：', registry.list().length)
