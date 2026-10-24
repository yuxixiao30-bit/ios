const room = '689812b29202b';
const r = await fetch('http://127.0.0.1:7788/room', {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ roomId: room }),
});
console.log('move:', r.status, await r.text());
await new Promise((res) => setTimeout(res, 3000));
const s = await fetch('http://127.0.0.1:7788/status');
console.log('status:', await s.text());
const say = await fetch('http://127.0.0.1:7788/say', {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ text: '跟过来了' }),
});
console.log('say:', say.status, await say.text());
