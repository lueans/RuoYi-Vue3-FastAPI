import assert from 'node:assert/strict'
import { createHash, webcrypto } from 'node:crypto'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  isNumericOwnerUserId,
  normalizeNumericOwnerUserId,
  normalizeOwnerUserId,
  sha256Hex,
} from '../mindmap-ai-shared.js'
import { canonicalMindmapJson, computeMindmapDocumentHash } from '../mindmap-ai-artifact.js'
import { buildMindmapAiOwnerSessionKey } from '../mindmap-ai-owner-session.js'
import {
  enqueueMindmapAiLocalAck,
  flushMindmapAiLocalAcks,
  listMindmapAiLocalAcks,
} from '../mindmap-ai-ack-queue.js'
import { isMindmapAiAbortError, formatMindmapAiError } from '../mindmap-ai-errors.js'
import { memoryStorage } from './helpers/memory-storage.mjs'

if (!globalThis.crypto) globalThis.crypto = webcrypto

const dialog = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const editor = readFileSync(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8')

function compileFunction(source, name, scope) {
  const start = source.search(new RegExp(`(?:async )?function ${name}\\(`))
  assert.ok(start >= 0, name)
  const tail = source.slice(start)
  const end = tail.slice(1).search(/\n(?:async )?function \w+\(/)
  assert.ok(end >= 0, name)
  return new Function('scope', `with (scope) { ${tail.slice(0, end + 1)}; return ${name}; }`)(scope)
}

test('numeric owner normalization preserves input coercion without weakening strict stored identity validation', () => {
  for (const [input, expected] of [
    [42, '42'], ['42', '42'], [' 42 ', '42'], ['1'.repeat(64), '1'.repeat(64)],
    [null, ''], [undefined, ''], [0, ''], [-1, ''], ['01', ''], ['+1', ''],
    [1.5, ''], ['1e3', ''], ['1'.repeat(65), ''], ['account-name', ''],
  ]) {
    assert.equal(normalizeNumericOwnerUserId(input), expected, String(input))
  }
  assert.equal(isNumericOwnerUserId('42'), true)
  assert.equal(isNumericOwnerUserId(42), false)
  assert.equal(isNumericOwnerUserId(' 42 '), false)
  // Cloud mutation intents deliberately support a broader bounded owner key.
  assert.equal(normalizeOwnerUserId('account-name'), 'account-name')
})

test('Dialog and Edit resolve the current actor through the same validator without caching the previous account', () => {
  const userStore = { id: 42 }
  const scope = { userStore, normalizeNumericOwnerUserId }
  const readDialogOwner = compileFunction(dialog, 'currentAiOwnerUserId', scope)
  const readEditorOwner = compileFunction(editor, 'currentLocalAiOwnerUserId', scope)
  for (const [id, expected] of [[42, '42'], [' 43 ', '43'], [null, ''], ['../42', '']]) {
    userStore.id = id
    assert.equal(readDialogOwner(), expected)
    assert.equal(readEditorOwner(), expected)
    assert.equal(buildMindmapAiOwnerSessionKey('AI_JOB', id), expected ? `AI_JOB:${expected}` : '')
  }
})

test('ACK consumers normalize requested owner keys but reject malformed persisted owners and preserve partitions', async () => {
  const storage = memoryStorage()
  const payload = { documentId: 'local:d', revision: 2, resultHash: `mmf2:sha256:${'a'.repeat(64)}` }
  const first = enqueueMindmapAiLocalAck({ ...payload, proposalId: 'p42', ownerUserId: ' 42 ' }, storage)
  enqueueMindmapAiLocalAck({ ...payload, proposalId: 'p43', ownerUserId: 43 }, storage)
  const key = 'MINDMAP_AI_ACK_QUEUE_V1'
  const entries = JSON.parse(storage.getItem(key))
  entries.push({ ...first, proposalId: 'malformed', ownerUserId: ' 42 ' })
  entries.push({ ...first, proposalId: 'numeric-storage', ownerUserId: 42 })
  storage.setItem(key, JSON.stringify(entries))
  assert.deepEqual(listMindmapAiLocalAcks(' 42 ', storage).map(entry => entry.proposalId), ['p42'])
  const sent = []
  assert.deepEqual(await flushMindmapAiLocalAcks(async id => sent.push(id), 42, storage), {
    sent: 1, pending: 0, discarded: 0,
  })
  assert.deepEqual(sent, ['p42'])
  assert.deepEqual(listMindmapAiLocalAcks(43, storage).map(entry => entry.proposalId), ['p43'])
  assert.deepEqual(listMindmapAiLocalAcks('account-name', storage), [])
  await assert.rejects(flushMindmapAiLocalAcks(async () => {}, 'account-name', storage), /用户分区无效/)
})

test('shared SHA-256 preserves UTF-8 bytes, lowercase padded hex and both existing caller formats', async () => {
  const hashAttemptFingerprint = compileFunction(dialog, 'hashAttemptFingerprint', { sha256Hex })
  for (const text of ['', '脑图🔖', '{"scope":"document"}']) {
    const expected = createHash('sha256').update(text).digest('hex')
    assert.equal(await sha256Hex(new TextEncoder().encode(text)), expected)
    assert.equal(await hashAttemptFingerprint(text), expected)
  }
  const document = { root: { children: [], data: { text: '脑图', uid: 'root' } }, layout: 'logicalStructure' }
  const expected = createHash('sha256').update(canonicalMindmapJson(document)).digest('hex')
  assert.equal(await computeMindmapDocumentHash(document), `mmf2:sha256:${expected}`)
})

test('hash consumers retain their own unavailable-crypto error contract', async () => {
  const hashAttemptFingerprint = compileFunction(dialog, 'hashAttemptFingerprint', { sha256Hex })
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value: undefined })
  try {
    await assert.rejects(computeMindmapDocumentHash({}), { code: 'AI_HASH_UNAVAILABLE' })
    await assert.rejects(hashAttemptFingerprint('request'), /当前浏览器无法安全保存请求恢复标识/)
  } finally {
    Object.defineProperty(globalThis, 'crypto', descriptor)
  }
})

test('Dialog proposal loading ignores shared cancellation errors but reports genuine failures', async () => {
  assert.match(dialog, /isMindmapAiAbortError as isAbortError/)
  for (const error of [
    { name: 'AbortError' }, { name: 'CanceledError' }, { code: 'ERR_CANCELED' }, new Error('offline'),
  ]) {
    const previous = { id: 'previous' }
    const scope = {
      job: { value: { id: 'job1', proposalId: 'p1' } },
      proposal: { value: previous }, proposalError: { value: '' },
      proposalLoading: { value: false }, diffConfirmed: { value: true },
      proposalLoadGeneration: 0,
      getMindmapAiProposal: async () => { throw error },
      isAbortError: isMindmapAiAbortError,
      formatMindmapAiError,
    }
    assert.equal(await compileFunction(dialog, 'loadProposal', scope)(), false)
    assert.equal(scope.proposalLoading.value, false)
    assert.equal(scope.proposal.value, isMindmapAiAbortError(error) ? previous : null)
    assert.equal(scope.proposalError.value, isMindmapAiAbortError(error) ? '' : 'offline')
  }
})
