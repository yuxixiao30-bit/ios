import WebSocket from 'ws';
import { gunzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';
const md5 = (s) => createHash('md5').update(s, 'utf8').digest('hex');
const name = '路人' + Math.floor(Math.random() * 900 + 100);
const guest = '*' + JSON.stringify({
  r: '5ce6a4b520a90', n: name, i: '', nc: '', s: '', st: 'n', mo: '',
  uid: '', li: '', mb: '', mu: '', la: '', vc: '', fp: '@' + md5(name),
});
console.log('guest name:', name);
const ws = new WebSocket('wss://m1.iirose.com', { perMessageDeflate: false, handshakeTimeout: 8000 });
ws.on('open', () => ws.send(Buffer.from(guest, 'utf8')));
ws.on('message', (data) => {
  const buf = Buffer.from(data);
  const text = buf[0] === 0x01 ? gunzipSync(buf.subarray(1)).toString('utf8') : buf.toString('utf8');
  console.log('RECV len=' + text.length + ' head=' + JSON.stringify(text.slice(0, 160)));
});
ws.on('error', (e) => { console.log('ERR', e.message); process.exit(1); });
setTimeout(() => { ws.terminate(); process.exit(0); }, 6000);
