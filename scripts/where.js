const r = await fetch('http://127.0.0.1:7788/status');
console.log('status:', await r.text());
const w = await fetch('http://127.0.0.1:7788/where?name=' + encodeURIComponent('雨雨不吃鱼'));
console.log('where:', await w.text());
