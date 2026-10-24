import { readFileSync } from 'node:fs';
const cfg = JSON.parse(readFileSync('D:/大肥鱼/iirose-bot/config.json', 'utf8'));
const out = {};
try {
  const s = await (await fetch('http://127.0.0.1:7788/status')).json();
  out.control = s;
} catch (e) { out.control = 'FAIL ' + e.message; }
const t0 = Date.now();
try {
  const r = await fetch(cfg.apiBase + '/chat/completions', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: 'Bearer ' + cfg.apiKey },
    body: JSON.stringify({ model: cfg.model, messages: [{ role: 'user', content: '回一个字：好' }], max_tokens: 8 }),
  });
  const j = await r.json();
  out.model = { ok: r.ok, model: j.model, reply: j.choices?.[0]?.message?.content, ms: Date.now() - t0 };
} catch (e) { out.model = { ok: false, error: e.message }; }
console.log(JSON.stringify(out, null, 1));
