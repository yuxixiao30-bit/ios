import { PersonaAI } from '../src/ai.js';
import { loadConfig } from '../src/config.js';
const c = await loadConfig();
const ai = new PersonaAI({ apiKey: c.apiKey, model: c.model, family: c.family || [] });
const ctx = ['豪德寺 三花：今天吃了三碗饭', '雨雨不吃鱼：真的假的', '鲸鱼娘：三碗不多啊，我能吃五碗'];
console.log('有钩子：');
console.log(' ->', await ai.reply({ name: '豪德寺 三花', content: '那你五碗吃得完吗' }, ctx, null, { continuation: 1 }));
console.log('\n没钩子：');
console.log(' ->', await ai.reply({ name: '百叶蔷薇lr', content: '打卡' }, ctx, null, { continuation: 2 }));
