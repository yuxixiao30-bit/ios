const post = async (path, body) => (await fetch('http://127.0.0.1:7788' + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })).status;
console.log('r2:', await post('/raw', { text: 'r2' }));
await new Promise(r => setTimeout(r, 3000));
console.log('say:', await post('/say', { text: '在吗' }));
