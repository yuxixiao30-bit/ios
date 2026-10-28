const s = await (await fetch('http://127.0.0.1:7788/status')).json();
const w = await (await fetch('http://127.0.0.1:7788/where?name=' + encodeURIComponent('雨雨不吃鱼'))).json();
console.log('bot:', JSON.stringify(s), 'user:', JSON.stringify(w));
if (w.roomId) {
  await fetch('http://127.0.0.1:7788/room', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ roomId: w.roomId }) });
  await new Promise(r => setTimeout(r, 4000));
  console.log('after move:', await (await fetch('http://127.0.0.1:7788/status')).text());
}
