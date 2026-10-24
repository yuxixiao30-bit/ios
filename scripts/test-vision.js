import { PersonaAI } from '../src/ai.js';
import { loadConfig } from '../src/config.js';
const c = await loadConfig();
const ai = new PersonaAI({ apiKey: c.apiKey, model: c.model, family: c.family || [] });
const img = 'https://r.iirose.com/i/26/1/1/7/5803-KD.jpg';
console.log('带图（家人）：');
console.log(' ->', await ai.reply({ name: '雨雨不吃鱼', content: '[图片]' }, [], img));
console.log('\n带图（路人）：');
console.log(' ->', await ai.reply({ name: '喵喵乐队吉他手', content: '看这个 [图片] 可爱吧' }, [], img));
