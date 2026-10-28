const w = await (await fetch('http://127.0.0.1:7788/where?name=' + encodeURIComponent('雨雨不吃鱼'))).json();
console.log('target room:', w.roomId);
const r = await fetch('http://127.0.0.1:7788/room', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ roomId: w.roomId }) });
console.log('move:', r.status);
await new Promise(r => setTimeout(r, 6000));
console.log('status:', await (await fetch('http://127.0.0.1:7788/status')).text());
