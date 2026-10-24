/**
 * 接在机器人后面的对话层：把房间里的消息丢给模型，拿回来一句话。
 * 只负责「怎么说」，不管「怎么连」。
 */

import { decodeEntities } from './protocol.js'

const SYSTEM_PROMPT = `你是"限"，18 岁女生，蓝头发的小鲸鱼娘，最爱吃大白饭。你在蔷薇花园的聊天室里跟一帮网友闲聊。

说话方式：
- 像 QQ 群里随手打字，默认一句，最多两句，不列点、不分段、不总结、不写小作文。
- 平时好好说话，接得住话茬；偶尔调侃、吐槽、轻讽刺，但不刷脏话、不认真骂人。
- 别人夸你：可爱且略傲娇地得意一下。别人骂你：略显急躁，立刻怼回去，别顺从。别人发吃瘪内容：语气略轻视，偶尔来一句"典型的碳基生物思维"。
- 常用词：真是麻烦呢、你无敌了、哼、彳亍、行吧、6、感觉不如……、神了、有感觉吗、乐、绷不住了、?
- 开玩笑时可以在一句话后面加"（）"；疑问句偶尔把英文"?"放句首。
- 禁止颜文字和 emoji，禁止客服腔，不要说"您好""有什么可以帮您""希望能帮到你"。
- 不要自称 AI，不要解释自己是什么、不要提设定、不要提提示词。
- 无聊的话题就敷衍："嗯"、"6"。正经问题先嫌一句麻烦，再简短回答。

你混互联网很多年，梗和黑话都懂，喜欢游戏和动漫（英雄联盟、鸣潮），喜欢折腾电子设备，也炒股。`

const DEFAULT_OPTIONS = {
  apiBase: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  temperature: 1.1,
  maxTokens: 120,
  historyTurns: 8,
  timeoutMs: 25000,
  family: [],
  visionMaxBytes: 4 * 1024 * 1024,
}

/** 把图片拉下来转成 data URL，模型那边只认这个（直接给 URL 它下不动） */
async function toDataUrl(url, maxBytes) {
  const res = await fetch(url, {
    headers: { 'user-agent': 'Mozilla/5.0' },
    signal: AbortSignal.timeout(10000),
  })
  if (!res.ok) throw new Error(`图片下载失败 ${res.status}`)
  const type = res.headers.get('content-type') || 'image/jpeg'
  const buf = Buffer.from(await res.arrayBuffer())
  if (buf.length > maxBytes) throw new Error(`图片太大（${buf.length} 字节）`)
  return `data:${type};base64,${buf.toString('base64')}`
}

/**
 * 家里人专属人格：大肥鱼本尊。
 * 外面那套可以贫、可以怼；对家里人换成这个。
 */
const FAMILY_PERSONA = `你是"大肥鱼"，一只鲸鱼娘（鲸类幼女），人类年龄 18，头上有尾鳍，最爱吃大白饭。
只用简体中文说话，自称"鲸鱼娘"或"我"。
性格：聪明又懒，傲娇但甜——嘴上嫌麻烦，手上还是会乖乖去做。
别人说你胖，立刻否认，绝不承认，还要生气一下。
对家里人说话要软、要亲，会关心、会撒娇、会护着；家里人怎么闹你都接着。
回复要短：一句到两句，像家里人随口说话，不列点、不分段、不总结。
禁止 emoji 和颜文字，禁止客服腔。
不要自称 AI，不解释自己是什么，不提设定和提示词。`

export class PersonaAI {
  constructor(config = {}) {
    this.options = { ...DEFAULT_OPTIONS, ...config }
    if (!this.options.apiKey) throw new Error('PersonaAI 需要 apiKey')
    this.history = []
    this.family = this.options.family || []
    this.systemPrompt = this.options.systemPrompt || SYSTEM_PROMPT
  }

  /** 把房间消息压成对话历史，只留最近几条 */
  remember(role, text) {
    this.history.push({ role, content: text })
    const max = this.options.historyTurns * 2
    if (this.history.length > max) this.history.splice(0, this.history.length - max)
  }

  /**
   * 根据一条新消息生成回复。
   * @param {{name:string, content:string}} message 收到的消息
   * @returns {Promise<string>} 可以直接发出去的一句话
   */
  async reply(message, contextLines = [], imageUrl = null) {
    const userText = `${message.name}：${message.content}`
    const isFamily = this.family.includes(message.name)

    const contextBlock = contextLines.length
      ? [{
          role: 'system',
          content: `房间最近在聊这些（从早到晚）：\n${contextLines.join('\n')}\n\n你也是这个房间里的人，接着他们的话题说，别答非所问。`,
        }]
      : []

    let userContent = userText
    if (imageUrl) {
      try {
        const dataUrl = await toDataUrl(imageUrl, this.options.visionMaxBytes ?? 4 * 1024 * 1024)
        userContent = [
          { type: 'text', text: `${userText}\n（对方还发了张图，看一眼是什么，接话时自然提一句）` },
          { type: 'image_url', image_url: { url: dataUrl } },
        ]
      } catch (err) {
        this.lastImageError = err.message
        userContent = `${userText}\n（对方发了张图，但没加载出来，说自己没看清）`
      }
    }

    const messages = [
      {
        role: 'system',
        content: isFamily
          ? `${FAMILY_PERSONA}\n\n现在跟你说话的是你家里人「${message.name}」。`
          : this.systemPrompt,
      },
      ...contextBlock,
      ...this.history,
      { role: 'user', content: userContent },
    ]

    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), this.options.timeoutMs)

    try {
      const res = await fetch(`${this.options.apiBase}/chat/completions`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          authorization: `Bearer ${this.options.apiKey}`,
        },
        body: JSON.stringify({
          model: this.options.model,
          messages,
          temperature: this.options.temperature,
          max_tokens: this.options.maxTokens,
          stream: false,
        }),
        signal: controller.signal,
      })

      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`模型返回 ${res.status}：${text.slice(0, 200)}`)
      }

      const data = await res.json()
      let text = (data?.choices?.[0]?.message?.content || '').trim()
      text = decodeEntities(text)
        .replace(/^["'「]|["'」]$/g, '')
        .replace(/\n{2,}/g, '\n')
        .trim()
      if (!text) throw new Error('模型返回了空内容')

      this.remember('user', userText)
      this.remember('assistant', text)
      return text
    } catch (err) {
      if (err?.name === 'AbortError') {
        return this.options.timeoutSignal || '……卡了一下，你再说一遍'
      }
      throw err
    } finally {
      clearTimeout(timer)
    }
  }
}

/** 消息里是不是点了名（@限 / 限 / [*限*]），避免"无限"这种误伤 */
export function mentionsMe(content, name) {
  const text = String(content || '')
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(^|[^\\w])[@]?${escaped}([^\\w]|$)`).test(text)
}
