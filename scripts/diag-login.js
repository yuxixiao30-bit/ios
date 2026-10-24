import { IiroseClient } from '../src/client.js';
import { loadConfig } from '../src/config.js';
const base = await loadConfig();
const cases = [
  { label: '正确密码', cfg: {} },
  { label: '故意错密码', cfg: { passwordMd5: '00000000000000000000000000000000' } },
  { label: '换房号', cfg: { roomId: '65c49a968faef' } },
];
for (const c of cases) {
  const cli = new IiroseClient({ ...base, ...c.cfg, debug: false, maxRetries: 0 });
  try { await cli.connect(); console.log('✔', c.label, '登录成功'); cli.close(); }
  catch (e) { console.log('✘', c.label, e.message); }
  await new Promise(r => setTimeout(r, 1500));
}
process.exit(0);
