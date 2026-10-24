import { IiroseClient } from '../src/client.js';
import { loadConfig } from '../src/config.js';
const config = await loadConfig();
const c = new IiroseClient({ ...config, debug: false });
const info = await c.connect();
const raw = info.raw;
const name = '雨雨不吃鱼';
let i = -1, hits = [];
while ((i = raw.indexOf(name, i + 1)) >= 0) hits.push(i);
console.log('hits:', hits.length);
for (const idx of hits.slice(0, 3)) {
  console.log('--- at', idx);
  console.log(JSON.stringify(raw.slice(Math.max(0, idx - 200), idx + 200)));
}
c.close();
process.exit(0);
