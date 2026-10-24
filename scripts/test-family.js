import { PersonaAI } from '../src/ai.js';
import { loadConfig } from '../src/config.js';
const c = await loadConfig();
const ai = new PersonaAI({ apiKey: c.apiKey, model: c.model, family: c.family || [] });
const cases = [
  { name: '豪德寺 三花', content: '@限 小猪宝宝' },
  { name: '豪德寺 三花', content: '@限 你今天怎么不说话' },
  { name: '雨雨不吃鱼', content: '@限 在干嘛呢' },
];
for (const m of cases) {
  try { console.log(`${m.name}：${m.content}\n  -> ${await ai.reply(m)}\n`); }
  catch (e) { console.log('失败:', e.message); }
}
