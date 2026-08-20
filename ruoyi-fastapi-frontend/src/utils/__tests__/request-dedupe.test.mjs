import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  createRepeatSubmitRecord,
  fingerprintRequestPayload,
  isDuplicateRepeatSubmit,
  isRepeatSubmitMethod,
  MAX_REPEAT_SUBMIT_PAYLOAD_BYTES,
} from '../requestDedupe.js'
import {
  cloneRequestPayload,
  stringifyRequestPayload,
} from '../requestPayload.js'

const requestUrl = new URL('../request.js', import.meta.url)
const transportCryptoUrl = new URL('../transportCrypto.js', import.meta.url)
const mindmapApiUrl = new URL('../../api/mindmap/mindmap.js', import.meta.url)

test('write request protection includes PATCH and excludes read methods', () => {
  assert.equal(isRepeatSubmitMethod('POST'), true)
  assert.equal(isRepeatSubmitMethod('put'), true)
  assert.equal(isRepeatSubmitMethod('patch'), true)
  assert.equal(isRepeatSubmitMethod('get'), false)
  assert.equal(isRepeatSubmitMethod('delete'), false)
})

test('request fingerprint stores a compact SHA-256 value and exact UTF-8 byte length', async () => {
  const payload = { text: '脑图🙂', enabled: true }
  const serialized = JSON.stringify(payload)
  const result = await fingerprintRequestPayload(payload)

  assert.match(result.fingerprint, /^sha256:[0-9a-f]{64}$/)
  assert.equal(result.byteLength, new TextEncoder().encode(serialized).byteLength)
  assert.ok(result.fingerprint.length < serialized.length + 80)
  assert.deepEqual(await fingerprintRequestPayload(payload), result)
  assert.notEqual(
    (await fingerprintRequestPayload({ ...payload, enabled: false })).fingerprint,
    result.fingerprint,
  )
})

test('request fingerprint separates no body, null, JSON objects and URL encoded bodies', async () => {
  const noBody = await fingerprintRequestPayload(undefined)
  const nullBody = await fingerprintRequestPayload(null)
  const objectBody = await fingerprintRequestPayload({})
  const urlEncodedBody = await fingerprintRequestPayload(new URLSearchParams('value=null'))

  assert.equal(noBody.byteLength, 0)
  assert.equal(nullBody.byteLength, new TextEncoder().encode('null').byteLength)
  assert.equal(objectBody.byteLength, new TextEncoder().encode('{}').byteLength)
  assert.equal(urlEncodedBody.byteLength, new TextEncoder().encode('value=null').byteLength)
  assert.equal(new Set([
    noBody.fingerprint,
    nullBody.fingerprint,
    objectBody.fingerprint,
    urlEncodedBody.fingerprint,
  ]).size, 4)
})

test('request fingerprint handles a 20,000-level JSON document without recursion', async () => {
  const root = { value: 0 }
  let current = root
  for (let depth = 1; depth < 20_000; depth += 1) {
    current.child = { value: depth }
    current = current.child
  }

  const result = await fingerprintRequestPayload(root)
  assert.match(result.fingerprint, /^sha256:[0-9a-f]{64}$/)
  assert.ok(result.byteLength > 20_000)
})

test('request payload serialization and retry snapshot both handle 20,000 levels', () => {
  const root = { value: 0 }
  let current = root
  for (let depth = 1; depth < 20_000; depth += 1) {
    current.child = { value: depth }
    current = current.child
  }

  const serialized = stringifyRequestPayload(root)
  const cloned = cloneRequestPayload(root)
  assert.equal(serialized.startsWith('{"value":0,"child":'), true)
  assert.notEqual(cloned, root)
  current = cloned
  let depth = 1
  while (current.child) {
    current = current.child
    depth += 1
  }
  assert.equal(depth, 20_000)
  assert.equal(current.value, 19_999)
})

test('binary and stream-style request bodies skip JSON duplicate detection', async () => {
  assert.equal(await fingerprintRequestPayload(new Uint8Array([1, 2, 3])), null)
  assert.equal(await fingerprintRequestPayload(new ArrayBuffer(4)), null)
  assert.equal(await fingerprintRequestPayload(new Blob(['data'])), null)
  assert.equal(await fingerprintRequestPayload(new FormData()), null)
})

test('oversized request bodies skip duplicate detection before hashing', async () => {
  const oversizedAscii = 'x'.repeat(MAX_REPEAT_SUBMIT_PAYLOAD_BYTES + 1)
  const oversizedUtf8 = '脑'.repeat(Math.floor(MAX_REPEAT_SUBMIT_PAYLOAD_BYTES / 3) + 1)

  assert.equal(await fingerprintRequestPayload(oversizedAscii), null)
  assert.equal(await fingerprintRequestPayload(oversizedUtf8), null)
})

test('duplicate decision includes method, URL, body size, fingerprint and forward time window', async () => {
  const previous = await createRepeatSubmitRecord({
    url: '/mindmap/file/1/content/batch',
    method: 'patch',
    data: { revision: 1 },
  }, 1_000)
  const current = await createRepeatSubmitRecord({
    url: '/mindmap/file/1/content/batch',
    method: 'PATCH',
    data: { revision: 1 },
  }, 1_500)

  assert.equal(isDuplicateRepeatSubmit(previous, current, 1_000), true)
  assert.equal(isDuplicateRepeatSubmit(previous, { ...current, method: 'put' }, 1_000), false)
  assert.equal(isDuplicateRepeatSubmit(previous, { ...current, url: '/other' }, 1_000), false)
  assert.equal(isDuplicateRepeatSubmit(previous, { ...current, byteLength: current.byteLength + 1 }, 1_000), false)
  assert.equal(isDuplicateRepeatSubmit(previous, { ...current, fingerprint: 'sha256:other' }, 1_000), false)
  assert.equal(isDuplicateRepeatSubmit(previous, { ...current, time: 2_000 }, 1_000), false)
  assert.equal(isDuplicateRepeatSubmit(previous, { ...current, time: 999 }, 1_000), false)
})

test('request interceptor never bypasses transport encryption when dedupe degrades', async () => {
  const source = await readFile(requestUrl, 'utf8')
  const dedupeStart = source.indexOf('if (!isRepeatSubmit && isRepeatSubmitMethod(config.method))')
  const encryptionStart = source.indexOf('config = await encryptTransportRequest(config)')

  assert.ok(dedupeStart >= 0)
  assert.ok(encryptionStart > dedupeStart)
  assert.match(source, /const requestRecord = await createRepeatSubmitRecord\(config\)/)
  assert.match(source, /catch \(error\) \{[\s\S]*?不得跳过后续传输加密与请求发送/)
  assert.doesNotMatch(source, /requestSize|limitSize|Object\.keys\(JSON\.stringify\(requestObj\)\)/)
})

test('transport encryption uses the stack-safe serializer for body and query payloads', async () => {
  const source = await readFile(transportCryptoUrl, 'utf8')

  assert.match(source, /cloneRequestPayload,[\s\S]*?stringifyRequestPayload/)
  assert.match(source, /const plainText = stringifyRequestPayload\(config\.data\)/)
  assert.match(source, /stringifyRequestPayload\(config\.params\)/)
  assert.match(source, /params: cloneRequestPayload\(config\.params\)/)
  assert.match(source, /data: cloneRequestPayload\(config\.data\)/)
  assert.doesNotMatch(source, /JSON\.parse\(JSON\.stringify\(value\)\)/)
  assert.doesNotMatch(source, /JSON\.stringify\(normalizePlainPayload/)
})

test('mindmap batch save relies on its server idempotency key instead of whole-tree client hashing', async () => {
  const source = await readFile(mindmapApiUrl, 'utf8')
  const batchBlock = source.match(/export function batchUpdateMindmapContent[\s\S]*?\n\}/)?.[0] || ''

  assert.match(batchBlock, /method: 'patch'/)
  assert.match(batchBlock, /headers: \{ repeatSubmit: false \}/)
})
