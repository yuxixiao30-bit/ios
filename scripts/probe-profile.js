await new Promise(r => setTimeout(r, 6000));
const post = async (path, body) => {
  const r = await fetch('http://127.0.0.1:7788' + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  return r.status + ' ' + await r.text();
};
console.log('status:', await (await fetch('http://127.0.0.1:7788/status')).text());
console.log('profile:', await post('/raw', { text: '+-雨雨不吃鱼' }));
await new Promise(r => setTimeout(r, 4000));
