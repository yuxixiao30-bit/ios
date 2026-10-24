import { IiroseClient } from '../src/client.js';
import { loadConfig } from '../src/config.js';
const config = await loadConfig();
const c = new IiroseClient({ ...config, debug: false });
const info = await c.connect();
const raw = info.raw;
c.close();
// 找房间记录：房名后面跟一个 13 位 id，再跟成员列表
const re = /。([\w\u4e00-\u9fa5_｜|·\-\s]{2,20})>([0-9a-f]{13})/g;
let m, out = [];
while ((m = re.exec(raw)) && out.length < 40) out.push([m[1], m[2]]);
console.log('rooms:', JSON.stringify(out.slice(0, 25)));
const i = raw.indexOf('雨雨不吃鱼', 136000);
console.log('CONTEXT:', JSON.stringify(raw.slice(i - 500, i + 120)));
process.exit(0);
