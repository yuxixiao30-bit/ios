import { PersonaAI } from '../src/ai.js'
import { loadConfig } from '../src/config.js'

/**
 * 不连服务器，单测对话层：给几条假消息，看它怎么回。
 */
const config = await loadConfig()
const ai = new PersonaAI({
  apiKey: config.apiKey,
  apiBase: config.apiBase,
  model: config.model,
  temperature: config.temperature,
  maxTokens: config.maxTokens,
})

const cases = [
  { name: '豪德寺三花', content: '@限 小猪小猪' },
  { name: '喵喵乐队吉他手', content: '@限 你是机器人吧' },
  { name: '雨雨不吃鱼', content: '@限 在干嘛' },
]

for (const c of cases) {
  try {
    const out = await ai.reply(c)
    console.log(`${c.name}：${c.content}\n  -> ${out}\n`)
  } catch (err) {
    console.error(`${c.name} 失败：${err.message}`)
  }
}
