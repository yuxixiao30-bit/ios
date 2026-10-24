import { IiroseClient } from '../src/client.js';
import { loadConfig } from '../src/config.js';
const config = await loadConfig();
const c = new IiroseClient({ ...config, debug: false });
const info = await c.connect();
const raw = info.raw;
c.close();
const key = '碎碎念念';
let i = -1;
while ((i = raw.indexOf(key, i + 1)) >= 0) {
  console.log('--- at', i);
  console.log(JSON.stringify(raw.slice(Math.max(0, i - 260), i + 120)));
}
process.exit(0);
