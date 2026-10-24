import WebSocket from 'ws'
import { DEFAULT_ENDPOINTS } from '../src/config.js'

const endpoints = process.argv.length > 2 ? process.argv.slice(2) : DEFAULT_ENDPOINTS

function test(url, timeoutMs = 6000) {
  return new Promise((resolve) => {
    const started = Date.now()
    let settled = false
    const ws = new WebSocket(url, { handshakeTimeout: timeoutMs, perMessageDeflate: false })

    const done = (result) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      try {
        ws.terminate()
      } catch {}
      resolve({ url, ms: Date.now() - started, ...result })
    }

    const timer = setTimeout(() => done({ ok: false, note: '超时' }), timeoutMs)

    ws.on('open', () => done({ ok: true, note: '握手成功' }))
    ws.on('error', (err) => done({ ok: false, note: err.message }))
    ws.on('unexpected-response', (_req, res) => done({ ok: false, note: `HTTP ${res.statusCode}` }))
  })
}

console.log(`探测 ${endpoints.length} 个端点…\n`)
const results = []
for (const url of endpoints) {
  const r = await test(url)
  results.push(r)
  const flag = r.ok ? 'OK  ' : 'FAIL'
  console.log(`${flag} ${r.url.padEnd(34)} ${String(r.ms).padStart(5)}ms  ${r.note}`)
}

const best = results.filter((r) => r.ok).sort((a, b) => a.ms - b.ms)[0]
console.log('\n' + (best ? `最快：${best.url}（${best.ms}ms）` : '没有可用端点'))

// 以退出码提示结果，方便脚本串联
process.exit(best ? 0 : 1)
