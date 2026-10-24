import { IiroseClient } from '../src/client.js';
import { loadConfig } from '../src/config.js';
const c = new IiroseClient({ ...(await loadConfig()), debug: false });
try { const info = await c.connect(); console.log('✔ 能登录', info.users.length); c.close(); }
catch (e) { console.log('✘', e.message); }
process.exit(0);
