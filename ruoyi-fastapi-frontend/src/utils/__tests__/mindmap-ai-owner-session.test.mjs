import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildMindmapAiOwnerSessionKey,
  clearMindmapAiOwnerSessionItem,
  readMindmapAiOwnerSessionItem,
  writeMindmapAiOwnerSessionItem,
} from '../mindmap-ai-owner-session.js'
import { memoryStorage } from './helpers/memory-storage.mjs'

test('AI task recovery values are independently partitioned by account', () => {
  const storage = memoryStorage()
  assert.equal(writeMindmapAiOwnerSessionItem('AI_JOB', '7', '{"jobId":"a"}', storage), true)
  assert.equal(writeMindmapAiOwnerSessionItem('AI_JOB', '8', '{"jobId":"b"}', storage), true)

  assert.equal(readMindmapAiOwnerSessionItem('AI_JOB', '7', storage), '{"jobId":"a"}')
  assert.equal(readMindmapAiOwnerSessionItem('AI_JOB', '8', storage), '{"jobId":"b"}')
  assert.equal(clearMindmapAiOwnerSessionItem('AI_JOB', '7', storage), true)
  assert.equal(readMindmapAiOwnerSessionItem('AI_JOB', '7', storage), null)
  assert.equal(readMindmapAiOwnerSessionItem('AI_JOB', '8', storage), '{"jobId":"b"}')
})

test('a scoped tombstone prevents a cleared account from reviving legacy V1 state', () => {
  const storage = memoryStorage({ initial: { AI_JOB: '{"ownerUserId":"7","jobId":"legacy"}' } })
  assert.equal(
    readMindmapAiOwnerSessionItem('AI_JOB', '7', storage),
    '{"ownerUserId":"7","jobId":"legacy"}',
  )
  assert.equal(clearMindmapAiOwnerSessionItem('AI_JOB', '7', storage), true)
  assert.equal(readMindmapAiOwnerSessionItem('AI_JOB', '7', storage), null)
  assert.equal(storage.getItem('AI_JOB'), '{"ownerUserId":"7","jobId":"legacy"}')
})

test('invalid owners and silently discarded writes fail closed', () => {
  const storage = {
    getItem() { return null },
    setItem() {},
  }
  assert.equal(buildMindmapAiOwnerSessionKey('AI_JOB', '../8'), '')
  assert.equal(writeMindmapAiOwnerSessionItem('AI_JOB', '7', '{}', storage), false)
  assert.equal(clearMindmapAiOwnerSessionItem('AI_JOB', '7', storage), false)
})
