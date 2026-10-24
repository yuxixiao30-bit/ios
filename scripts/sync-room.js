const s = await (await fetch('http://127.0.0.1:7788/status')).json();
console.log('bot:', JSON.stringify(s));
const w = await (await fetch('http://127.0.0.1:7788/where?name=' + encodeURIComponent('雨雨不吃鱼'))).json();
console.log('user:', JSON.stringify(w));
if (w.roomId && w.roomId !== s.roomId) {
  await fetch('http://127.0.0.1:7788/room', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ roomId: w.roomId }) });
  console.log('moved to user room:', w.roomId);
}
