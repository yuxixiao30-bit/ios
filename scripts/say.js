const res = await fetch('http://127.0.0.1:7788/say', {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ text: '我会跟上你的' }),
});
console.log('say:', res.status, await res.text());
