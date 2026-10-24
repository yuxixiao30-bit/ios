import WebSocket from 'ws';
import { gzipSync, gunzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const cfg = JSON.parse(readFileSync('D:/大肥鱼/iirose-bot/config.json', 'utf8'));
const md5 = (s) => createHash('md5').update(s, 'utf8').digest('hex');
const login = '*' + JSON.stringify({
  r: cfg.roomId, n: cfg.username, p: cfg.passwordMd5,
  st: 'n', mo: cfg.signature || '', mb: '', mu: '01', fp: '@' + md5(cfg.username),
});
console.log('SEND:', login.slice(0, 160));

const ws = new WebSocket('wss://m1.iirose.com', { perMessageDeflate: false, handshakeTimeout: 8000 });
ws.on('open', () => ws.send(Buffer.from(login, 'utf8')));
ws.on('message', (data) => {
  const buf = Buffer.from(data);
  let text;
  if (buf[0] === 0x01) { try { text = gunzipSync(buf.subarray(1)).toString('utf8'); } catch (e) { text = 'GUNZIP FAIL ' + e.message; } }
  else text = buf.toString('utf8');
  console.log('RECV len=' + text.length + ' head=' + JSON.stringify(text.slice(0, 300)));
  setTimeout(() => { ws.terminate(); process.exit(0); }, 1500);
});
ws.on('error', (e) => { console.log('ERR', e.message); process.exit(1); });
setTimeout(() => { console.log('TIMEOUT'); process.exit(1); }, 15000);
