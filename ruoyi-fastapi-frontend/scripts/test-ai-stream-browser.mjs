// Run against Vite: npm run dev, then node scripts/test-ai-stream-browser.mjs.
// Uses an isolated Chrome profile and the real SVG renderer, no account/API.
import { spawn } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

const profile = await mkdtemp(join(tmpdir(), 'mindmap-ai-stream-test-'))
const chrome = spawn(process.env.CHROME_BIN || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-background-networking', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] })
let socket
try {
  const endpoint = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Chrome startup timed out')), 15000)
    chrome.once('error', error => { clearTimeout(timer); reject(error) })
    chrome.stderr.on('data', chunk => {
      const match = String(chunk).match(/DevTools listening on (ws:\/\/\S+)/)
      if (match) { clearTimeout(timer); resolve(match[1]) }
    })
  })
  const pages = await (await fetch(new URL('/json/list', endpoint.replace('ws:', 'http:')))).json()
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject })
  let sequence = 0
  const pending = new Map()
  socket.onmessage = event => {
    const message = JSON.parse(event.data)
    const request = pending.get(message.id)
    if (!request) return
    pending.delete(message.id)
    if (message.error) request.reject(new Error(JSON.stringify(message.error)))
    else request.resolve(message.result)
  }
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence
    pending.set(id, { resolve, reject })
    socket.send(JSON.stringify({ id, method, params }))
  })
  await send('Page.navigate', { url: `${process.env.VITE_TEST_URL || 'http://127.0.0.1:5173'}/scripts/ai-stream-browser.html` })
  let result
  for (let index = 0; index < 600; index++) {
    const response = await send('Runtime.evaluate', { expression: 'window.__aiStreamTestResult', returnByValue: true })
    result = response.result?.value
    if (result) break
    await delay(100)
  }
  if (!result) throw new Error('Browser test timed out (check Vite module loading)')
  console.log(JSON.stringify(result, null, 2))
  if (result.status !== 'PASS') process.exitCode = 1
} finally {
  socket?.close()
  chrome.kill('SIGTERM')
  await new Promise(resolve => { if (chrome.exitCode !== null) resolve(); else chrome.once('exit', resolve) })
  await rm(profile, { recursive: true, force: true })
}
