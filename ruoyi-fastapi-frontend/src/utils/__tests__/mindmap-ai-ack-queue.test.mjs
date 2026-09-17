import assert from 'node:assert/strict'
import test from 'node:test'
import {
  enqueueMindmapAiLocalAck as enqueueRawMindmapAiLocalAck,
  flushMindmapAiLocalAcks as flushRawMindmapAiLocalAcks,
  listMindmapAiLocalAcks as listRawMindmapAiLocalAcks,
} from '../mindmap-ai-ack-queue.js'
import { memoryStorage } from './helpers/memory-storage.mjs'

const ownerUserId = '42'

function enqueueMindmapAiLocalAck(payload, storage, owner = ownerUserId) {
  return enqueueRawMindmapAiLocalAck({ ownerUserId: owner, ...payload }, storage)
}

function flushMindmapAiLocalAcks(send, storage, owner = ownerUserId) {
  return flushRawMindmapAiLocalAcks(send, owner, storage)
}

function listMindmapAiLocalAcks(storage, owner = ownerUserId) {
  return listRawMindmapAiLocalAcks(owner, storage)
}

const hash = `mmf2:sha256:${'a'.repeat(64)}`

test('本地 AI 应用回执先持久化并在成功发送后移除', async () => {
  const storage = memoryStorage()
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-1', documentId: 'local:document-1', revision: 2, resultHash: hash,
  }, storage)
  assert.equal(listMindmapAiLocalAcks(storage).length, 1)
  const received = []
  const result = await flushMindmapAiLocalAcks(async (proposalId, payload) => {
    received.push({ proposalId, payload })
  }, storage)
  assert.deepEqual(result, { sent: 1, pending: 0, discarded: 0 })
  assert.equal(received[0].proposalId, 'proposal-1')
  assert.equal(listMindmapAiLocalAcks(storage).length, 0)
})

test('网络失败只增加尝试次数，不会要求再次修改脑图', async () => {
  const storage = memoryStorage()
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-2', documentId: 'local:document-2', revision: 3, resultHash: hash,
  }, storage)
  const result = await flushMindmapAiLocalAcks(async () => {
    throw new Error('offline')
  }, storage)
  assert.deepEqual(result, { sent: 0, pending: 1, discarded: 0 })
  assert.equal(listMindmapAiLocalAcks(storage)[0].attempts, 1)
})

test('发送期间新入队的回执不会被旧 flush 覆盖丢失', async () => {
  const storage = memoryStorage()
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-old', documentId: 'local:document-old', revision: 2, resultHash: hash,
  }, storage)
  let release
  const gate = new Promise(resolve => { release = resolve })
  const flushing = flushMindmapAiLocalAcks(async () => gate, storage)
  await Promise.resolve()

  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-new', documentId: 'local:document-new', revision: 4, resultHash: hash,
  }, storage)
  release()
  const result = await flushing

  assert.deepEqual(result, { sent: 1, pending: 1, discarded: 0 })
  assert.deepEqual(
    listMindmapAiLocalAcks(storage).map(entry => entry.proposalId),
    ['proposal-new'],
  )
})

test('不同存储实例的 flush 不会错误复用同一个进行中任务', async () => {
  const firstStorage = memoryStorage()
  const secondStorage = memoryStorage()
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-a', documentId: 'local:document-a', revision: 2, resultHash: hash,
  }, firstStorage)
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-b', documentId: 'local:document-b', revision: 3, resultHash: hash,
  }, secondStorage)
  const sent = []

  await Promise.all([
    flushMindmapAiLocalAcks(async proposalId => { sent.push(proposalId) }, firstStorage),
    flushMindmapAiLocalAcks(async proposalId => { sent.push(proposalId) }, secondStorage),
  ])

  assert.deepEqual(sent.sort(), ['proposal-a', 'proposal-b'])
  assert.equal(listMindmapAiLocalAcks(firstStorage).length, 0)
  assert.equal(listMindmapAiLocalAcks(secondStorage).length, 0)
})

test('永久 4xx 回执失败会丢弃，避免无限重试', async () => {
  const storage = memoryStorage()
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-invalid', documentId: 'local:document-invalid', revision: 2, resultHash: hash,
  }, storage)

  const result = await flushMindmapAiLocalAcks(async () => {
    throw { response: { status: 409 } }
  }, storage)

  assert.deepEqual(result, {
    sent: 0,
    pending: 0,
    discarded: 1,
    discardedFailures: [{
      proposalId: 'proposal-invalid',
      action: 'apply',
      businessCode: '',
      message: '服务端拒绝了本地 AI 回执',
    }],
  })
  assert.equal(listMindmapAiLocalAcks(storage).length, 0)
})

test('HTTP 200 响应中的确定性 ACK 业务冲突会停止重试', async () => {
  const storage = memoryStorage()
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-conflict', documentId: 'local:document-conflict',
    revision: 2, resultHash: hash,
  }, storage)

  const result = await flushMindmapAiLocalAcks(async () => {
    throw Object.assign(new Error('AI 脑图提案应用回执冲突'), {
      code: 500,
      data: { errorCode: 'AI_LOCAL_ACK_CONFLICT' },
    })
  }, storage)

  assert.equal(result.sent, 0)
  assert.equal(result.pending, 0)
  assert.equal(result.discarded, 1)
  assert.equal(result.discardedFailures[0].businessCode, 'AI_LOCAL_ACK_CONFLICT')
  assert.match(result.discardedFailures[0].message, /回执冲突/)
  assert.equal(listMindmapAiLocalAcks(storage).length, 0)
})

test('未分类的业务 500 仍按服务端暂时故障保留重试', async () => {
  const storage = memoryStorage()
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-server-error', documentId: 'local:document-server-error',
    revision: 2, resultHash: hash,
  }, storage)

  const result = await flushMindmapAiLocalAcks(async () => {
    throw Object.assign(new Error('服务器内部错误，请稍后重试'), { code: 500 })
  }, storage)

  assert.deepEqual(result, { sent: 0, pending: 1, discarded: 0 })
  assert.equal(listMindmapAiLocalAcks(storage)[0].attempts, 1)
})

test('可恢复的 401 与 429 回执失败仍保留在队列', async () => {
  for (const status of [401, 429]) {
    const storage = memoryStorage()
    enqueueMindmapAiLocalAck({
      proposalId: `proposal-${status}`,
      documentId: `local:document-${status}`,
      revision: 2,
      resultHash: hash,
    }, storage)
    const result = await flushMindmapAiLocalAcks(async () => {
      throw { response: { status } }
    }, storage)
    assert.deepEqual(result, { sent: 0, pending: 1, discarded: 0 })
    assert.equal(listMindmapAiLocalAcks(storage)[0].attempts, 1)
  }
})

test('本地撤销回执会替换尚未发送的应用回执并调用 undo 发送器', async () => {
  const storage = memoryStorage()
  const revertedHash = `mmf2:sha256:${'b'.repeat(64)}`
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-undo', documentId: 'local:document-undo', revision: 2,
    resultHash: hash,
  }, storage)
  enqueueMindmapAiLocalAck({
    action: 'undo', proposalId: 'proposal-undo', documentId: 'local:document-undo',
    revision: 3, resultHash: hash, revertedHash,
  }, storage)

  const received = []
  const result = await flushMindmapAiLocalAcks(async (proposalId, payload, action) => {
    received.push({ proposalId, payload, action })
  }, storage)

  assert.deepEqual(result, { sent: 1, pending: 0, discarded: 0 })
  assert.deepEqual(received, [{
    proposalId: 'proposal-undo',
    action: 'undo',
    payload: {
      documentId: 'local:document-undo', revision: 3, resultHash: hash, revertedHash,
    },
  }])
})

test('带用户分区的旧版无 action 回执按 apply 兼容读取', () => {
  const storage = memoryStorage()
  storage.setItem('MINDMAP_AI_ACK_QUEUE_V1', JSON.stringify([{
    ownerUserId,
    proposalId: 'proposal-v1', documentId: 'local:document-v1', revision: 2,
    resultHash: hash, createdAt: Date.now(), attempts: 0,
  }]))

  assert.equal(listMindmapAiLocalAcks(storage)[0].action, 'apply')
})

test('可以按 proposal 精确识别待发送的本地撤销', () => {
  const storage = memoryStorage()
  const revertedHash = `mmf2:sha256:${'b'.repeat(64)}`
  enqueueMindmapAiLocalAck({
    action: 'undo', proposalId: 'proposal-pending-undo', documentId: 'local:pending',
    revision: 4, resultHash: hash, revertedHash,
  }, storage)
  const pendingUndoProposalIds = listMindmapAiLocalAcks(storage)
    .filter(entry => entry.action === 'undo')
    .map(entry => entry.proposalId)
  assert.equal(pendingUndoProposalIds.includes('proposal-pending-undo'), true)
  assert.equal(pendingUndoProposalIds.includes('proposal-other'), false)
})

test('本地 ACK 仅发送当前用户分区且不会删除其他账号记录', async () => {
  const storage = memoryStorage()
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-user-a', documentId: 'local:user-a', revision: 2, resultHash: hash,
  }, storage, '1001')
  enqueueMindmapAiLocalAck({
    proposalId: 'proposal-user-b', documentId: 'local:user-b', revision: 3, resultHash: hash,
  }, storage, '1002')
  const sent = []
  const result = await flushMindmapAiLocalAcks(async proposalId => sent.push(proposalId), storage, '1002')

  assert.deepEqual(sent, ['proposal-user-b'])
  assert.deepEqual(result, { sent: 1, pending: 0, discarded: 0 })
  assert.deepEqual(listMindmapAiLocalAcks(storage, '1001').map(item => item.proposalId), [
    'proposal-user-a',
  ])
  assert.deepEqual(listMindmapAiLocalAcks(storage, '1002'), [])
})

test('缺少 owner 的历史 ACK fail-closed，不会由当前账号发送', async () => {
  const storage = memoryStorage()
  storage.setItem('MINDMAP_AI_ACK_QUEUE_V1', JSON.stringify([{
    proposalId: 'legacy-unknown-owner', documentId: 'local:legacy', revision: 2,
    resultHash: hash, createdAt: Date.now(), attempts: 0,
  }]))
  let sendCount = 0
  const result = await flushMindmapAiLocalAcks(async () => { sendCount += 1 }, storage, '1002')

  assert.equal(sendCount, 0)
  assert.deepEqual(result, { sent: 0, pending: 0, discarded: 0 })
  assert.deepEqual(listMindmapAiLocalAcks(storage, '1002'), [])
})
