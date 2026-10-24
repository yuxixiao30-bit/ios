import { cleanContent, decodeEntities } from '../src/protocol.js';
const samples = [
  '&#092;&#092;&#092;* # 猪！！！',
  '三个分号;;;然后呢',
  '&amp;lt;b&amp;gt; 不是标签',
  '正常一句话',
];
for (const s of samples) console.log(JSON.stringify(s), '->', JSON.stringify(cleanContent(s)));
