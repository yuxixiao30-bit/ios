/**
 * 接在机器人后面的对话层：把房间里的消息丢给模型，拿回来一句话。
 * 只负责「怎么说」，不管「怎么连」。
 */

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
}

export class PersonaAI {
  constructor(config = {}) {
    this.options = { ...DEFAULT_OPTIONS, ...config }
    if (!this.options.apiKey) throw new Error('PersonaAI 需要 apiKey')
    this.history = []
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
  async reply(message) {
    const userText = `${message.name}：${message.content}`

    const messages = [
      { role: 'system', content: this.options.systemPrompt || SYSTEM_PROMPT },
      ...this.history,
      { role: 'user', content: userText },
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
      text = text.replace(/^["'「]|["'」]$/g, '').replace(/\n{2,}/g, '\n').trim()
      if (!text) throw new Error('模型返回了空内容')

      this.remember('user', userText)
      this.remember('assistant', text)
      return text
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
