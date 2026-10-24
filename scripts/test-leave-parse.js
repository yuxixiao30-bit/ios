import { parseSystemEvent } from '../src/protocol.js';
const raw = "1792847195>http://r.iirose.com/i/26/10/12/10/5749-IB.jpg>雨雨不吃鱼>'2689812b29202b>s>86a7a6>0>>5d4e559f99e21>''13925'1055'50,95.7,1.14>>3689812b29202b";
const ev = parseSystemEvent(raw);
console.log('解析:', JSON.stringify({ name: ev.name, uid: ev.uid, targetRoom: ev.targetRoom }));
console.log(ev.targetRoom === '689812b29202b' ? '✔ 目标房间对' : '✘ 目标房间不对');
