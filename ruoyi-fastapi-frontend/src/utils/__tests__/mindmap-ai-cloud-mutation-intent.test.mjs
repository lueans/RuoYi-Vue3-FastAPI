import assert from 'node:assert/strict'
import test from 'node:test'
import {
  MINDMAP_AI_CLOUD_MUTATION_STORAGE_KEY,
  enqueueMindmapAiCloudMutationIntent,
  getMindmapAiCloudMutationIntent,
  listMindmapAiCloudMutationIntents as listRawMindmapAiCloudMutationIntents,
  markMindmapAiCloudMutationConfirmed,
  markMindmapAiCloudMutationFailed,
  removeMindmapAiCloudMutationIntent,
} from '../mindmap-ai-cloud-mutation-intent.js'
import { memoryStorage } from './helpers/memory-storage.mjs'

const proposalId = '11111111-1111-4111-8111-111111111111'
const jobId = '22222222-2222-4222-8222-222222222222'
const applyIdentity = {
  ownerUserId: 7,
  action: 'apply',
  proposalId,
  idempotencyKey: `mindmap-ai-apply:${proposalId}`,
}
const applyInput = {
  ...applyIdentity,
  jobId,
  mindmapId: 42,
  requestPayload: {
    contentRevision: 7,
    baseHash: `mmf2:sha256:${'a'.repeat(64)}`,
    roomEpoch: 'epoch-7',
    forceOverwrite: false,
  },
  ignoredSecret: 'must-not-be-persisted',
}

function listMindmapAiCloudMutationIntents(storage, ownerUserId = '7') {
  return listRawMindmapAiCloudMutationIntents(ownerUserId, storage)
}

test('云端 mutation intent 先按 V1 schema 持久化并写后读验证', () => {
  const storage = memoryStorage()
  const entry = enqueueMindmapAiCloudMutationIntent(applyInput, storage)

  assert.deepEqual(entry.requestPayload, applyInput.requestPayload)
  assert.equal(entry.expectedStatus, 'applied')
  assert.equal(entry.phase, 'pending_server')
  assert.equal(entry.confirmedContentRevision, null)
  assert.equal(Object.hasOwn(entry, 'ignoredSecret'), false)
  const envelope = JSON.parse(storage.getItem(MINDMAP_AI_CLOUD_MUTATION_STORAGE_KEY))
  assert.equal(envelope.schemaVersion, 1)
  assert.equal(envelope.entries[0].schemaVersion, 1)
  assert.equal(listMindmapAiCloudMutationIntents(storage).length, 1)
})

test('存储抛错或静默丢弃写入时 enqueue 均失败关闭', () => {
  assert.throws(
    () => enqueueMindmapAiCloudMutationIntent(applyInput, memoryStorage({ throwOnWrite: true })),
    /无法持久化/,
  )
  assert.throws(
    () => enqueueMindmapAiCloudMutationIntent(applyInput, memoryStorage({ ignoreWrites: true })),
    /写入后校验失败/,
  )
})

test('apply 与 undo 使用 action:proposal 独立分区且同分区拒绝不同幂等键', () => {
  const storage = memoryStorage()
  enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  const undoIdentity = {
    ownerUserId: 7,
    action: 'undo',
    proposalId,
    idempotencyKey: `mindmap-ai-undo:${proposalId}`,
  }
  enqueueMindmapAiCloudMutationIntent({
    ...undoIdentity,
    jobId,
    mindmapId: 42,
    requestPayload: null,
  }, storage)
  assert.deepEqual(
    listMindmapAiCloudMutationIntents(storage).map(entry => entry.action),
    ['apply', 'undo'],
  )

  assert.throws(() => enqueueMindmapAiCloudMutationIntent({
    ...applyInput,
    idempotencyKey: `mindmap-ai-apply-retry:${proposalId}`,
  }, storage), /不同的幂等请求/)
  assert.equal(listMindmapAiCloudMutationIntents(storage).length, 2)
})

test('相同 identity 可幂等入队但不能改变已经绑定的请求参数', () => {
  const storage = memoryStorage()
  const first = enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  const replay = enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  assert.deepEqual(replay, first)
  assert.equal(listMindmapAiCloudMutationIntents(storage).length, 1)

  assert.throws(() => enqueueMindmapAiCloudMutationIntent({
    ...applyInput,
    requestPayload: { ...applyInput.requestPayload, contentRevision: 8 },
  }, storage), /已保存参数不一致/)
  assert.equal(getMindmapAiCloudMutationIntent(applyIdentity, storage).requestPayload.contentRevision, 7)
})

test('确认覆盖标志会进入持久化请求，且需要独立幂等键', () => {
  const storage = memoryStorage()
  const forceInput = {
    ...applyInput,
    idempotencyKey: `mindmap-ai-force-apply:${proposalId}`,
    requestPayload: { ...applyInput.requestPayload, forceOverwrite: true },
  }
  const entry = enqueueMindmapAiCloudMutationIntent(forceInput, storage)
  assert.equal(entry.requestPayload.forceOverwrite, true)
  assert.equal(entry.idempotencyKey, forceInput.idempotencyKey)
})

test('旧版普通应用因版本冲突终止后可由用户确认升级为整图覆盖', () => {
  const storage = memoryStorage()
  enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  markMindmapAiCloudMutationFailed(applyIdentity, 'AI_APPLY_CONFLICT', storage)

  const forceInput = {
    ...applyInput,
    idempotencyKey: `mindmap-ai-force-apply:${proposalId}`,
    requestPayload: { ...applyInput.requestPayload, forceOverwrite: true },
  }
  const upgraded = enqueueMindmapAiCloudMutationIntent(forceInput, storage)

  assert.equal(upgraded.phase, 'pending_server')
  assert.equal(upgraded.errorCode, null)
  assert.equal(upgraded.requestPayload.forceOverwrite, true)
  assert.equal(upgraded.idempotencyKey, forceInput.idempotencyKey)
  assert.equal(listMindmapAiCloudMutationIntents(storage).length, 1)
  assert.equal(getMindmapAiCloudMutationIntent(applyIdentity, storage), null)
})

test('整图覆盖只在确定未提交的协作冲突后允许按原幂等请求重试', () => {
  const storage = memoryStorage()
  const forceIdentity = {
    ...applyIdentity,
    idempotencyKey: `mindmap-ai-force-apply:${proposalId}`,
  }
  const forceInput = {
    ...applyInput,
    ...forceIdentity,
    requestPayload: { ...applyInput.requestPayload, forceOverwrite: true },
  }
  enqueueMindmapAiCloudMutationIntent(forceInput, storage)
  markMindmapAiCloudMutationFailed(forceIdentity, 'AI_APPLY_CONFLICT', storage)

  const retried = enqueueMindmapAiCloudMutationIntent(forceInput, storage)
  assert.equal(retried.phase, 'pending_server')
  assert.equal(retried.errorCode, null)

  markMindmapAiCloudMutationFailed(forceIdentity, 'AI_PROPOSAL_STALE', storage)
  const stale = enqueueMindmapAiCloudMutationIntent(forceInput, storage)
  assert.equal(stale.phase, 'permanent_failed')
  assert.equal(stale.errorCode, 'AI_PROPOSAL_STALE')
})

test('待确认、已确认或非版本冲突的普通请求不能被覆盖请求替换', () => {
  const forceInput = {
    ...applyInput,
    idempotencyKey: `mindmap-ai-force-apply:${proposalId}`,
    requestPayload: { ...applyInput.requestPayload, forceOverwrite: true },
  }

  const pendingStorage = memoryStorage()
  enqueueMindmapAiCloudMutationIntent(applyInput, pendingStorage)
  assert.throws(
    () => enqueueMindmapAiCloudMutationIntent(forceInput, pendingStorage),
    /不同的幂等请求/,
  )

  const confirmedStorage = memoryStorage()
  enqueueMindmapAiCloudMutationIntent(applyInput, confirmedStorage)
  markMindmapAiCloudMutationConfirmed(applyIdentity, 8, confirmedStorage)
  assert.throws(
    () => enqueueMindmapAiCloudMutationIntent(forceInput, confirmedStorage),
    /不同的幂等请求/,
  )

  const integrityStorage = memoryStorage()
  enqueueMindmapAiCloudMutationIntent(applyInput, integrityStorage)
  markMindmapAiCloudMutationFailed(applyIdentity, 'AI_PROPOSAL_INTEGRITY_INVALID', integrityStorage)
  assert.throws(
    () => enqueueMindmapAiCloudMutationIntent(forceInput, integrityStorage),
    /不同的幂等请求/,
  )
})

test('get、confirmed、failed 与 remove 都要求 action/proposal/key 精确匹配', () => {
  const storage = memoryStorage()
  enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  const wrongIdentity = { ...applyIdentity, idempotencyKey: `mindmap-ai-apply-wrong:${proposalId}` }

  assert.equal(getMindmapAiCloudMutationIntent(wrongIdentity, storage), null)
  assert.equal(markMindmapAiCloudMutationConfirmed(wrongIdentity, 8, storage), null)
  assert.equal(markMindmapAiCloudMutationFailed(wrongIdentity, 'AI_APPLY_CONFLICT', storage), null)
  assert.equal(removeMindmapAiCloudMutationIntent(wrongIdentity, storage), false)

  const confirmed = markMindmapAiCloudMutationConfirmed(applyIdentity, 8, storage)
  assert.equal(confirmed.phase, 'server_confirmed')
  assert.equal(confirmed.confirmedContentRevision, 8)
  assert.equal(confirmed.errorCode, null)

  const failed = markMindmapAiCloudMutationFailed(applyIdentity, 'AI_APPLY_CONFLICT', storage)
  assert.equal(failed.phase, 'permanent_failed')
  assert.equal(failed.confirmedContentRevision, null)
  assert.equal(failed.errorCode, 'AI_APPLY_CONFLICT')
  assert.equal(removeMindmapAiCloudMutationIntent(applyIdentity, storage), true)
  assert.equal(listMindmapAiCloudMutationIntents(storage).length, 0)
})

test('永久失败只接受稳定错误码且不持久化异常详情', () => {
  const storage = memoryStorage()
  enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  assert.throws(
    () => markMindmapAiCloudMutationFailed(applyIdentity, 'database password=secret', storage),
    /失败码无效/,
  )
  const failed = markMindmapAiCloudMutationFailed(applyIdentity, 'AI_UNDO_CONFLICT', storage)
  assert.deepEqual(
    Object.keys(failed).filter(key => /message|detail|lastError/i.test(key)),
    [],
  )
  assert.doesNotMatch(storage.getItem(MINDMAP_AI_CLOUD_MUTATION_STORAGE_KEY), /password|secret/)
})

test('读取会按 schema、TTL 和字段白名单清洗不可信存储', () => {
  const storage = memoryStorage()
  const now = Date.now()
  const valid = enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  const expired = {
    ...valid,
    proposalId: '33333333-3333-4333-8333-333333333333',
    idempotencyKey: 'mindmap-ai-apply:33333333-3333-4333-8333-333333333333',
    createdAt: now - 31 * 24 * 60 * 60 * 1000,
    updatedAt: now - 31 * 24 * 60 * 60 * 1000,
  }
  const malformed = { ...valid, proposalId: '', lastError: 'token=secret' }
  const legacyWithoutOwner = { ...valid }
  delete legacyWithoutOwner.ownerUserId
  storage.setItem(MINDMAP_AI_CLOUD_MUTATION_STORAGE_KEY, JSON.stringify({
    schemaVersion: 1,
    entries: [
      { ...valid, unknown: 'drop-me', lastError: 'token=secret' },
      expired,
      malformed,
      legacyWithoutOwner,
    ],
  }))

  const listed = listMindmapAiCloudMutationIntents(storage)
  assert.equal(listed.length, 1)
  assert.equal(Object.hasOwn(listed[0], 'unknown'), false)
  assert.equal(Object.hasOwn(listed[0], 'lastError'), false)

  storage.setItem(MINDMAP_AI_CLOUD_MUTATION_STORAGE_KEY, JSON.stringify({
    schemaVersion: 2,
    entries: [valid],
  }))
  assert.deepEqual(listMindmapAiCloudMutationIntents(storage), [])
})

test('无效输入、确认版本和失败码不会污染已有 outbox', () => {
  const storage = memoryStorage()
  enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  assert.throws(() => enqueueMindmapAiCloudMutationIntent({
    ...applyInput,
    requestPayload: { ...applyInput.requestPayload, roomEpoch: '\nsecret' },
  }, storage), TypeError)
  assert.throws(
    () => markMindmapAiCloudMutationConfirmed(applyIdentity, 0, storage),
    /确认版本无效/,
  )
  assert.throws(
    () => getMindmapAiCloudMutationIntent({ ...applyIdentity, action: 'delete' }, storage),
    /恢复标识无效/,
  )
  assert.equal(listMindmapAiCloudMutationIntents(storage).length, 1)
})

test('owner 是 identity 与 action:proposal 分区的一部分且数字会规范为字符串', () => {
  const storage = memoryStorage()
  const first = enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  const secondOwnerIdentity = {
    ...applyIdentity,
    ownerUserId: 'user-b',
    idempotencyKey: `mindmap-ai-apply-user-b:${proposalId}`,
  }
  enqueueMindmapAiCloudMutationIntent({
    ...applyInput,
    ...secondOwnerIdentity,
  }, storage)

  assert.equal(first.ownerUserId, '7')
  assert.equal(listMindmapAiCloudMutationIntents(storage).length, 1)
  assert.equal(listMindmapAiCloudMutationIntents(storage, 'user-b').length, 1)
  assert.equal(getMindmapAiCloudMutationIntent({ ...applyIdentity, ownerUserId: '7' }, storage)?.ownerUserId, '7')
  assert.equal(getMindmapAiCloudMutationIntent({ ...applyIdentity, ownerUserId: 8 }, storage), null)
  assert.equal(removeMindmapAiCloudMutationIntent({ ...applyIdentity, ownerUserId: 8 }, storage), false)
  assert.equal(removeMindmapAiCloudMutationIntent(secondOwnerIdentity, storage), true)
  assert.equal(listMindmapAiCloudMutationIntents(storage)[0].ownerUserId, '7')
})

test('云端 mutation 列表按 owner 隔离且未知 owner fail-closed', () => {
  const storage = memoryStorage()
  enqueueMindmapAiCloudMutationIntent(applyInput, storage)
  enqueueMindmapAiCloudMutationIntent({
    ...applyInput,
    ownerUserId: 'user-b',
    idempotencyKey: `mindmap-ai-apply-user-b:${proposalId}`,
  }, storage)

  assert.deepEqual(
    listMindmapAiCloudMutationIntents(storage).map(entry => entry.ownerUserId),
    ['7'],
  )
  assert.deepEqual(
    listMindmapAiCloudMutationIntents(storage, 'user-b').map(entry => entry.ownerUserId),
    ['user-b'],
  )
  assert.deepEqual(listRawMindmapAiCloudMutationIntents('', storage), [])
  assert.deepEqual(listRawMindmapAiCloudMutationIntents(undefined, storage), [])
})

test('所有接口拒绝缺少 owner 的旧 identity/input', () => {
  const storage = memoryStorage()
  const { ownerUserId: _ownerUserId, ...ownerlessInput } = applyInput
  const { ownerUserId: _identityOwner, ...ownerlessIdentity } = applyIdentity
  assert.throws(
    () => enqueueMindmapAiCloudMutationIntent(ownerlessInput, storage),
    /恢复标识无效/,
  )
  for (const operation of [
    () => getMindmapAiCloudMutationIntent(ownerlessIdentity, storage),
    () => markMindmapAiCloudMutationConfirmed(ownerlessIdentity, 8, storage),
    () => markMindmapAiCloudMutationFailed(ownerlessIdentity, 'AI_APPLY_CONFLICT', storage),
    () => removeMindmapAiCloudMutationIntent(ownerlessIdentity, storage),
  ]) assert.throws(operation, /恢复标识无效/)
})
