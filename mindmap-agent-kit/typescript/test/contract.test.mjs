import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MAX_AGENT_MESSAGE_LENGTH,
  MAX_AGENT_MESSAGE_TITLE_LENGTH,
  MindmapBuilder,
  buildAgentMessageResult,
  normalizeAgentManifest,
  normalizeAgentMessageResult,
  resolveResultTypes,
  validateAgentRequest,
} from '../dist/index.js'

test('addNodes leaves the document unchanged when any batch item is invalid', () => {
  const builder = new MindmapBuilder('Payment tests')

  assert.throws(() => builder.addNodes([
    { parentUid: builder.rootUid, text: 'Successful payment' },
    { parentUid: 'missing-parent', text: 'Invalid branch' },
  ]), /parent node does not exist/)
  assert.deepEqual(builder.document.root.children, [])
})

test('legacy manifests remain artifact-only', () => {
  const manifest = { intents: ['create'] }
  assert.deepEqual(resolveResultTypes(manifest), ['artifact'])
  assert.deepEqual(normalizeAgentManifest(manifest).resultTypes, ['artifact'])
  assert.equal(validateAgentRequest('create', 'file', manifest).resultType, 'artifact')
})

test('discussion capability requires an explicit message result', () => {
  assert.throws(
    () => normalizeAgentManifest({ intents: ['create', 'discuss'] }),
    /resultTypes message/,
  )
  const manifest = {
    intents: ['create', 'discuss'],
    resultTypes: ['artifact', 'message'],
  }
  assert.deepEqual(validateAgentRequest('discuss', 'message', manifest), {
    intent: 'discuss',
    target: 'message',
    resultType: 'message',
  })
})

test('message target is reserved for discussion', () => {
  assert.throws(() => validateAgentRequest('discuss', 'proposal'), /must target message/)
  assert.throws(() => validateAgentRequest('create', 'message'), /only discuss/)
})

test('message completion is closed, normalized, and allows safe whitespace', () => {
  const result = normalizeAgentMessageResult({
    completionState: 'message_completed',
    title: '  支付\n 用例  ',
    content: '\n可先梳理支付失败分支。\n',
    contentType: 'text/plain',
  })
  assert.equal(result.title, '支付 用例')
  assert.equal(result.content, '可先梳理支付失败分支。')
  assert.deepEqual(buildAgentMessageResult('允许\n多行和\t制表符'), {
    completionState: 'message_completed',
    title: null,
    content: '允许\n多行和\t制表符',
    contentType: 'text/plain',
  })
  assert.deepEqual(normalizeAgentMessageResult(JSON.stringify(result)), result)
  assert.throws(() => normalizeAgentMessageResult({ ...result, unexpected: true }), /structured contract/)
})

test('message completion enforces controls, code-point length, and byte length', () => {
  assert.throws(() => buildAgentMessageResult('unsafe\u0000value'), /unsafe or overlong/)
  assert.throws(() => buildAgentMessageResult('a'.repeat(MAX_AGENT_MESSAGE_LENGTH + 1)), /unsafe or overlong/)
  assert.throws(() => buildAgentMessageResult('content', 't'.repeat(MAX_AGENT_MESSAGE_TITLE_LENGTH + 1)), /unsafe or overlong/)
  assert.throws(() => buildAgentMessageResult('\u{1F642}'.repeat(17_000)), /unsafe or overlong/)
})
