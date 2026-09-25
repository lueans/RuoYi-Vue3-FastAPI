import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MINDMAP_AI_LOCAL_JOURNAL_DEFAULT_TTL_MS,
  MINDMAP_AI_LOCAL_JOURNAL_PHASES,
  MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY,
  classifyMindmapAiLocalRecovery,
  getMindmapAiLocalJournal,
  inspectMindmapAiLocalRecovery,
  listMindmapAiLocalJournals,
  prepareMindmapAiLocalJournal,
  removeMindmapAiLocalJournal,
  transitionMindmapAiLocalJournal,
} from '../mindmap-ai-local-journal.js'
import { memoryStorage } from './helpers/memory-storage.mjs'

const NOW = 1_800_000_000_000
const baseHash = `mmf2:sha256:${'a'.repeat(64)}`
const resultHash = `mmf2:sha256:${'b'.repeat(64)}`
const identity = {
  ownerUserId: 42,
  documentId: 'local:document-0001',
  proposalId: 'proposal-0001',
}

function root(text) {
  return {
    data: { uid: 'root', text },
    children: [{ data: { uid: 'child', text: `${text} child` }, children: [] }],
  }
}

function beforeWorkspace(overrides = {}) {
  return {
    root: root('base'),
    layout: 'logicalStructure',
    theme: { template: 'default', config: { lineColor: '#123456' } },
    view: { state: { scale: 1, x: 8, y: -3 } },
    documentData: { custom: { enabled: true } },
    documentId: identity.documentId,
    revision: 7,
    documentHash: baseHash,
    lastAppliedProposal: null,
    ...overrides,
  }
}

function input(overrides = {}) {
  return {
    ...identity,
    beforeWorkspace: beforeWorkspace(),
    baseRevision: 7,
    appliedRevision: 8,
    baseHash,
    resultHash,
    ...overrides,
  }
}

function baseState(overrides = {}) {
  return beforeWorkspace(overrides)
}

function appliedState(overrides = {}) {
  return beforeWorkspace({
    root: root('result'),
    revision: 8,
    documentHash: resultHash,
    lastAppliedProposal: identity.proposalId,
    ...overrides,
  })
}

function undoneState(overrides = {}) {
  return beforeWorkspace({
    revision: 9,
    documentHash: baseHash,
    lastAppliedProposal: null,
    ...overrides,
  })
}

function prepare(storage, overrides = {}, options = {}) {
  return prepareMindmapAiLocalJournal(input(overrides), storage, { now: NOW, ...options })
}

test('journal identity validation stays strict while UI account keys may normalize whitespace', () => {
  for (const ownerUserId of [' 42 ', '01', 'account-name', Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => prepare(memoryStorage(), { ownerUserId }), /用户|身份|日志/)
  }
  assert.equal(prepare(memoryStorage(), { ownerUserId: '42' }).ownerUserId, '42')
})

test('prepared 日志按白名单持久化完整基线并执行写后读校验', () => {
  const storage = memoryStorage()
  const entry = prepare(storage, {
    ignoredSecret: 'token=must-not-persist',
    operations: [{ type: 'remove_node', uid: 'root' }],
  })

  assert.equal(entry.ownerUserId, '42')
  assert.equal(entry.phase, 'prepared')
  assert.equal(entry.baseRevision, 7)
  assert.equal(entry.appliedRevision, 8)
  assert.equal(entry.beforeWorkspace.schemaVersion, 2)
  assert.equal(entry.beforeWorkspace.values.root.children[0].data.text, 'base child')
  assert.equal(entry.createdAt, NOW)
  assert.equal(entry.updatedAt, NOW)
  assert.equal(entry.expiresAt, NOW + MINDMAP_AI_LOCAL_JOURNAL_DEFAULT_TTL_MS)
  assert.equal(Object.hasOwn(entry, 'operations'), false)
  assert.equal(Object.hasOwn(entry, 'ignoredSecret'), false)
  assert.doesNotMatch(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY), /token|remove_node/)

  entry.beforeWorkspace.values.root.data.text = 'mutated-return-value'
  assert.equal(
    getMindmapAiLocalJournal(identity, storage, { now: NOW }).beforeWorkspace.values.root.data.text,
    'base',
  )
})

test('日志存储抛错和静默丢弃写入都在画布变更前失败关闭', () => {
  assert.throws(
    () => prepare(memoryStorage({ throwOnWrite: true })),
    error => error?.code === 'AI_LOCAL_JOURNAL_PERSIST_FAILED',
  )
  assert.throws(
    () => prepare(memoryStorage({ ignoreWrites: true })),
    error => error?.code === 'AI_LOCAL_JOURNAL_VERIFY_FAILED',
  )
})

test('相同事务重复 prepare 幂等且不会重置已推进的阶段或延长 TTL', () => {
  const storage = memoryStorage()
  const first = prepare(storage)
  const pending = transitionMindmapAiLocalJournal(
    identity,
    'applied_ack_pending',
    storage,
    { now: NOW + 10, expectedPhase: 'prepared' },
  )
  const replay = prepareMindmapAiLocalJournal(input(), storage, { now: NOW + 20 })

  assert.equal(first.phase, 'prepared')
  assert.equal(pending.phase, 'applied_ack_pending')
  assert.equal(replay.phase, 'applied_ack_pending')
  assert.equal(replay.createdAt, NOW)
  assert.equal(replay.expiresAt, first.expiresAt)
  assert.equal(listMindmapAiLocalJournals('42', storage, { now: NOW + 20 }).length, 1)
})

test('同一 owner/document 的未完成提案互斥，不同用户和文档严格隔离', () => {
  const storage = memoryStorage()
  prepare(storage)
  assert.throws(
    () => prepareMindmapAiLocalJournal(input({ proposalId: 'proposal-0002' }), storage, { now: NOW }),
    error => error?.code === 'AI_LOCAL_JOURNAL_CONFLICT',
  )

  prepareMindmapAiLocalJournal(input({
    ownerUserId: 43,
    proposalId: 'proposal-user-43',
  }), storage, { now: NOW })
  prepareMindmapAiLocalJournal(input({
    documentId: 'local:document-0002',
    proposalId: 'proposal-document-2',
    beforeWorkspace: beforeWorkspace({ documentId: 'local:document-0002' }),
  }), storage, { now: NOW })

  assert.equal(listMindmapAiLocalJournals('42', storage, { now: NOW }).length, 2)
  assert.equal(listMindmapAiLocalJournals('43', storage, { now: NOW }).length, 1)
  assert.equal(getMindmapAiLocalJournal({ ...identity, ownerUserId: 43 }, storage, { now: NOW }), null)
  assert.equal(getMindmapAiLocalJournal({ ...identity, documentId: 'local:wrong' }, storage, { now: NOW }), null)
  assert.equal(getMindmapAiLocalJournal({ ...identity, proposalId: 'wrong' }, storage, { now: NOW }), null)
})

test('已确认提案可作为下一条提案的精确基线，旧撤销日志不会提前丢失', () => {
  const storage = memoryStorage()
  prepare(storage)
  transitionMindmapAiLocalJournal(identity, 'applied_ack_pending', storage, { now: NOW + 1 })
  transitionMindmapAiLocalJournal(identity, 'applied_ack_confirmed', storage, { now: NOW + 2 })
  const nextResultHash = `mmf2:sha256:${'c'.repeat(64)}`
  const next = prepareMindmapAiLocalJournal({
    ownerUserId: identity.ownerUserId,
    documentId: identity.documentId,
    proposalId: 'proposal-0002',
    beforeWorkspace: appliedState(),
    baseRevision: 8,
    appliedRevision: 9,
    baseHash: resultHash,
    resultHash: nextResultHash,
  }, storage, { now: NOW + 3 })

  assert.equal(next.phase, 'prepared')
  assert.deepEqual(
    listMindmapAiLocalJournals(identity.ownerUserId, storage, { now: NOW + 3 })
      .map(entry => [entry.proposalId, entry.phase]),
    [
      ['proposal-0001', 'applied_ack_confirmed'],
      ['proposal-0002', 'prepared'],
    ],
  )
})

test('新事务不会清理其他账号的终态日志，容量满时失败而不驱逐其他分区', () => {
  const storage = memoryStorage()
  for (let owner = 1; owner <= 20; owner += 1) {
    const documentId = `local:capacity-document-${owner}`
    const proposalId = `capacity-proposal-${owner}`
    const entryInput = input({
      ownerUserId: owner,
      documentId,
      proposalId,
      beforeWorkspace: beforeWorkspace({ documentId }),
    })
    prepareMindmapAiLocalJournal(entryInput, storage, { now: NOW })
    if (owner === 1) {
      transitionMindmapAiLocalJournal(
        { ownerUserId: owner, documentId, proposalId },
        'done',
        storage,
        { now: NOW + 1 },
      )
    }
  }
  const before = storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY)
  const documentId = 'local:capacity-document-21'
  assert.throws(
    () => prepareMindmapAiLocalJournal(input({
      ownerUserId: 21,
      documentId,
      proposalId: 'capacity-proposal-21',
      beforeWorkspace: beforeWorkspace({ documentId }),
    }), storage, { now: NOW + 2 }),
    error => error?.code === 'AI_LOCAL_JOURNAL_CAPACITY_EXCEEDED',
  )
  assert.equal(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY), before)
  assert.equal(listMindmapAiLocalJournals('1', storage, { now: NOW + 2 })[0].phase, 'done')
})

test('阶段机只允许 prepared -> apply pending -> confirmed -> undo pending -> done', () => {
  const storage = memoryStorage()
  prepare(storage)
  assert.deepEqual(MINDMAP_AI_LOCAL_JOURNAL_PHASES, [
    'prepared',
    'applied_ack_pending',
    'applied_ack_confirmed',
    'undone_ack_pending',
    'done',
  ])
  assert.throws(
    () => transitionMindmapAiLocalJournal(
      identity,
      'applied_ack_confirmed',
      storage,
      { now: NOW + 1 },
    ),
    error => error?.code === 'AI_LOCAL_JOURNAL_PHASE_CONFLICT',
  )
  assert.equal(transitionMindmapAiLocalJournal(
    identity, 'applied_ack_pending', storage, { now: NOW + 1 },
  ).phase, 'applied_ack_pending')
  assert.equal(transitionMindmapAiLocalJournal(
    identity, 'applied_ack_confirmed', storage, { now: NOW + 2 },
  ).phase, 'applied_ack_confirmed')
  assert.equal(transitionMindmapAiLocalJournal(
    identity, 'undone_ack_pending', storage, { now: NOW + 3 },
  ).phase, 'undone_ack_pending')
  assert.equal(transitionMindmapAiLocalJournal(
    identity, 'done', storage, { now: NOW + 4 },
  ).phase, 'done')
  assert.throws(
    () => transitionMindmapAiLocalJournal(
      identity, 'prepared', storage, { now: NOW + 5 },
    ),
    error => error?.code === 'AI_LOCAL_JOURNAL_PHASE_CONFLICT',
  )
})

test('阶段表统一后所有合法、幂等和非法迁移保持原契约', () => {
  const allowed = {
    prepared: ['applied_ack_pending', 'done'],
    applied_ack_pending: ['applied_ack_confirmed', 'done'],
    applied_ack_confirmed: ['undone_ack_pending', 'done'],
    undone_ack_pending: ['done'],
    done: [],
  }
  for (const phase of Object.keys(allowed)) {
    for (const next of [...Object.keys(allowed), 'constructor', 'unknown']) {
      const storage = memoryStorage()
      prepare(storage)
      const envelope = JSON.parse(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY))
      envelope.entries[0].phase = phase
      storage.setItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY, JSON.stringify(envelope))
      const before = storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY)
      const advance = () => transitionMindmapAiLocalJournal(identity, next, storage, { now: NOW + 1 })
      if (next === phase || allowed[phase].includes(next)) {
        assert.equal(advance().phase, next)
        if (next === phase) assert.equal(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY), before)
      } else {
        assert.throws(advance, error => error.code.startsWith('AI_LOCAL_JOURNAL_PHASE_'))
        assert.equal(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY), before)
      }
    }
  }
})

test('CAS expectedPhase 阻止旧异步回调覆盖较新的事务阶段', () => {
  const storage = memoryStorage()
  prepare(storage)
  transitionMindmapAiLocalJournal(
    identity,
    'applied_ack_pending',
    storage,
    { now: NOW + 1, expectedPhase: 'prepared' },
  )
  assert.throws(
    () => transitionMindmapAiLocalJournal(
      identity,
      'applied_ack_confirmed',
      storage,
      { now: NOW + 2, expectedPhase: 'prepared' },
    ),
    error => error?.code === 'AI_LOCAL_JOURNAL_PHASE_CONFLICT',
  )
  assert.equal(getMindmapAiLocalJournal(identity, storage, { now: NOW + 2 }).phase, 'applied_ack_pending')
})

test('恢复分类：base 是未应用，绝不自动重放 operations', () => {
  const storage = memoryStorage()
  const entry = prepare(storage)
  let operationsRead = 0
  Object.defineProperty(entry, 'operations', {
    enumerable: true,
    get() {
      operationsRead += 1
      throw new Error('operations must never be read')
    },
  })
  const workspace = baseState()
  const original = structuredClone(workspace)
  const result = classifyMindmapAiLocalRecovery(entry, workspace, {
    now: NOW,
    identity,
  })

  assert.equal(result.classification, 'not_applied')
  assert.equal(result.reason, 'workspace_at_base')
  assert.equal(result.actionable, false)
  assert.deepEqual(result.requiredAcks, [])
  assert.equal(result.recommendedPhase, 'done')
  assert.equal(operationsRead, 0)
  assert.deepEqual(workspace, original)
})

test('恢复分类：result 只补 apply ACK，确认后恢复持久化撤销能力', () => {
  const storage = memoryStorage()
  prepare(storage)

  let result = inspectMindmapAiLocalRecovery(identity, appliedState(), storage, { now: NOW })
  assert.equal(result.classification, 'applied')
  assert.deepEqual(result.requiredAcks, ['apply'])
  assert.deepEqual(result.ackPlan, [{
    ownerUserId: '42',
    action: 'apply',
    proposalId: identity.proposalId,
    documentId: identity.documentId,
    revision: 8,
    resultHash,
  }])
  assert.equal(result.recommendedPhase, 'applied_ack_pending')
  assert.equal(result.undoAvailable, false)
  assert.equal(result.entry.beforeWorkspace.values.root.data.text, 'base')

  transitionMindmapAiLocalJournal(
    identity, 'applied_ack_pending', storage, { now: NOW + 1 },
  )
  transitionMindmapAiLocalJournal(
    identity, 'applied_ack_confirmed', storage, { now: NOW + 2 },
  )
  result = inspectMindmapAiLocalRecovery(identity, appliedState(), storage, { now: NOW + 3 })
  assert.deepEqual(result.requiredAcks, [])
  assert.equal(result.undoAvailable, true)
})

test('恢复分类：base revision+2 且 lastAppliedProposal=null 是已撤销', () => {
  const storage = memoryStorage()
  prepare(storage)
  transitionMindmapAiLocalJournal(
    identity, 'applied_ack_pending', storage, { now: NOW + 1 },
  )
  transitionMindmapAiLocalJournal(
    identity, 'applied_ack_confirmed', storage, { now: NOW + 2 },
  )

  const result = inspectMindmapAiLocalRecovery(identity, undoneState(), storage, { now: NOW + 3 })
  assert.equal(result.classification, 'undone')
  assert.equal(result.reason, 'workspace_at_undone_base')
  assert.deepEqual(result.requiredAcks, ['undo'])
  assert.deepEqual(result.ackPlan, [{
    ownerUserId: '42',
    action: 'undo',
    proposalId: identity.proposalId,
    documentId: identity.documentId,
    revision: 9,
    resultHash,
    revertedHash: baseHash,
  }])
  assert.equal(result.recommendedPhase, 'undone_ack_pending')
  assert.equal(result.undoAvailable, false)
})

test('崩溃跨越 apply 和 undo 两次落盘时，恢复计划要求顺序补齐两个 ACK', () => {
  const storage = memoryStorage()
  prepare(storage)
  const result = inspectMindmapAiLocalRecovery(identity, undoneState(), storage, { now: NOW + 1 })
  assert.equal(result.classification, 'undone')
  assert.deepEqual(result.requiredAcks, ['apply', 'undo'])
  assert.deepEqual(result.ackPlan.map(item => [item.action, item.revision]), [
    ['apply', 8],
    ['undo', 9],
  ])
  assert.equal(result.recommendedPhase, 'applied_ack_pending')
})

test('其他版本、哈希、lastAppliedProposal 或文档身份一律判定 superseded', () => {
  const storage = memoryStorage()
  prepare(storage)
  for (const workspace of [
    appliedState({ revision: 10 }),
    appliedState({ documentHash: baseHash }),
    appliedState({ lastAppliedProposal: 'another-proposal' }),
    appliedState({ documentId: 'local:another-document' }),
    { invalid: true },
  ]) {
    const result = inspectMindmapAiLocalRecovery(identity, workspace, storage, { now: NOW })
    assert.equal(result.classification, 'superseded')
    assert.deepEqual(result.requiredAcks, [])
    assert.equal(result.undoAvailable, false)
  }
})

test('错误账号/文档/提案不能取得或恢复别的分区', () => {
  const storage = memoryStorage()
  const entry = prepare(storage)
  const workspace = appliedState()
  const storageBefore = storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY)
  const workspaceBefore = structuredClone(workspace)

  for (const wrongIdentity of [
    { ...identity, ownerUserId: 99 },
    { ...identity, documentId: 'local:another-document' },
    { ...identity, proposalId: 'another-proposal' },
  ]) {
    assert.equal(
      inspectMindmapAiLocalRecovery(wrongIdentity, workspace, storage, { now: NOW }).reason,
      'journal_missing',
    )
    assert.equal(
      classifyMindmapAiLocalRecovery(entry, workspace, { now: NOW, identity: wrongIdentity }).reason,
      'identity_mismatch',
    )
  }
  assert.equal(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY), storageBefore)
  assert.deepEqual(workspace, workspaceBefore)
})

test('过期日志只返回 fail-closed 分类，不清理、不 ACK、不改变工作区', () => {
  const storage = memoryStorage()
  prepare(storage, {}, { ttlMs: 100 })
  const workspace = appliedState()
  const workspaceBefore = structuredClone(workspace)
  const storageBefore = storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY)

  const result = inspectMindmapAiLocalRecovery(identity, workspace, storage, { now: NOW + 100 })
  assert.equal(result.classification, 'superseded')
  assert.equal(result.reason, 'journal_expired')
  assert.equal(result.actionable, false)
  assert.equal(getMindmapAiLocalJournal(identity, storage, { now: NOW + 100 }), null)
  assert.equal(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY), storageBefore)
  assert.deepEqual(workspace, workspaceBefore)
  assert.throws(
    () => transitionMindmapAiLocalJournal(
      identity, 'applied_ack_pending', storage, { now: NOW + 100 },
    ),
    error => error?.code === 'AI_LOCAL_JOURNAL_EXPIRED',
  )
})

test('损坏、未来 schema、重复 identity 均失败关闭且不会覆盖原记录', () => {
  for (const corrupted of [
    '{not-json',
    JSON.stringify({ schemaVersion: 99, entries: [] }),
    JSON.stringify({ schemaVersion: 1, entries: [{ malformed: true }] }),
  ]) {
    const storage = memoryStorage()
    storage.setItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY, corrupted)
    const original = storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY)
    assert.throws(
      () => inspectMindmapAiLocalRecovery(identity, appliedState(), storage, { now: NOW }),
      error => error?.code === 'AI_LOCAL_JOURNAL_CORRUPT',
    )
    assert.throws(
      () => prepare(storage),
      error => error?.code === 'AI_LOCAL_JOURNAL_CORRUPT',
    )
    assert.equal(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY), original)
  }

  const storage = memoryStorage()
  prepare(storage)
  const envelope = JSON.parse(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY))
  envelope.entries.push(structuredClone(envelope.entries[0]))
  storage.setItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY, JSON.stringify(envelope))
  assert.throws(
    () => listMindmapAiLocalJournals('42', storage, { now: NOW }),
    error => error?.code === 'AI_LOCAL_JOURNAL_CORRUPT',
  )
})

test('基线、版本和哈希必须相互绑定，非法输入不会写日志', () => {
  for (const overrides of [
    { appliedRevision: 9 },
    { baseHash: resultHash },
    { resultHash: 'invalid' },
    { beforeWorkspace: beforeWorkspace({ documentId: 'local:wrong' }) },
    { beforeWorkspace: beforeWorkspace({ revision: 8 }) },
    { beforeWorkspace: beforeWorkspace({ documentHash: resultHash }) },
  ]) {
    const storage = memoryStorage()
    assert.throws(() => prepare(storage, overrides), /事务日志/)
    assert.equal(storage.getItem(MINDMAP_AI_LOCAL_JOURNAL_STORAGE_KEY), null)
  }
})

test('done 日志可精确删除，错误 identity 不会删除任何记录', () => {
  const storage = memoryStorage()
  prepare(storage)
  transitionMindmapAiLocalJournal(identity, 'done', storage, { now: NOW + 1 })
  assert.equal(removeMindmapAiLocalJournal(
    { ...identity, proposalId: 'wrong' }, storage, { now: NOW + 2 },
  ), false)
  assert.equal(listMindmapAiLocalJournals('42', storage, { now: NOW + 2 }).length, 1)
  assert.equal(removeMindmapAiLocalJournal(identity, storage, { now: NOW + 2 }), true)
  assert.deepEqual(listMindmapAiLocalJournals('42', storage, { now: NOW + 2 }), [])
})
