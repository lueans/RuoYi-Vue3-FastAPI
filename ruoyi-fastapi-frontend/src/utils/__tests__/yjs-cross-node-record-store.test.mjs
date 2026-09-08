import assert from 'node:assert/strict'
import test from 'node:test'
import * as Y from 'yjs'

import {
  applyCrossNodeRecordDeltaV2,
  CROSS_NODE_FIELDS_MAP,
  readCrossNodeRecordStateV2,
  replaceCrossNodeRecordStateV2,
} from '../yjs-cross-node-record-store.js'

const emptyDelta = () => ({
  relations: { upserts: {}, deletedKeys: [] },
  summaries: { upserts: {}, deletedKeys: [] },
  groups: { upserts: {}, deletedKeys: [] },
  assets: { upserts: {}, deletedKeys: [] },
})

function forkSeed(state) {
  const seed = new Y.Doc()
  replaceCrossNodeRecordStateV2(seed, state)
  const baseUpdate = Y.encodeStateAsUpdate(seed)
  const baseVector = Y.encodeStateVector(seed)
  const first = new Y.Doc()
  const second = new Y.Doc()
  Y.applyUpdate(first, baseUpdate)
  Y.applyUpdate(second, baseUpdate)
  return { seed, first, second, baseVector }
}

function exchangeConcurrentUpdates(first, second, baseVector) {
  const firstUpdate = Y.encodeStateAsUpdate(first, baseVector)
  const secondUpdate = Y.encodeStateAsUpdate(second, baseVector)
  Y.applyUpdate(first, secondUpdate)
  Y.applyUpdate(second, firstUpdate)
}

test('同一关系深层样式的不同字段在两个真实 Y.Doc 中并发合并', () => {
  const relation = {
    relationUid: 'assoc:root:child',
    sourceUid: 'root',
    targetUid: 'child',
    styleData: { color: 'red', width: 1, nested: { dash: 2, opacity: 1 } },
  }
  const docs = forkSeed({ relations: { relation: relation } })
  const firstDelta = emptyDelta()
  firstDelta.relations.upserts.relation = {
    ...relation,
    styleData: { ...relation.styleData, color: 'blue' },
  }
  const secondDelta = emptyDelta()
  secondDelta.relations.upserts.relation = {
    ...relation,
    styleData: {
      ...relation.styleData,
      nested: { ...relation.styleData.nested, opacity: 0.5 },
    },
  }
  applyCrossNodeRecordDeltaV2(docs.first, firstDelta)
  applyCrossNodeRecordDeltaV2(docs.second, secondDelta)
  exchangeConcurrentUpdates(docs.first, docs.second, docs.baseVector)

  for (const doc of [docs.first, docs.second]) {
    assert.deepEqual(readCrossNodeRecordStateV2(doc).relations.relation.styleData, {
      color: 'blue',
      width: 1,
      nested: { dash: 2, opacity: 0.5 },
    })
  }
  Object.values(docs).filter(value => value instanceof Y.Doc).forEach(doc => doc.destroy())
})

test('概要端点、排序和深层 payload 可在并发客户端分别修改后收敛', () => {
  const summary = {
    summaryUid: 'summary-1',
    ownerUid: 'root',
    startChildUid: 'a',
    endChildUid: 'b',
    payload: { text: '旧概要', style: { color: 'red', width: 1 } },
    sortOrder: 0,
  }
  const docs = forkSeed({ summaries: { summary: summary } })
  const firstDelta = emptyDelta()
  firstDelta.summaries.upserts.summary = {
    ...summary,
    startChildUid: 'b',
    endChildUid: 'c',
    sortOrder: 2,
  }
  const secondDelta = emptyDelta()
  secondDelta.summaries.upserts.summary = {
    ...summary,
    payload: { ...summary.payload, text: '新概要' },
  }
  applyCrossNodeRecordDeltaV2(docs.first, firstDelta)
  applyCrossNodeRecordDeltaV2(docs.second, secondDelta)
  exchangeConcurrentUpdates(docs.first, docs.second, docs.baseVector)

  const expected = {
    ...summary,
    startChildUid: 'b',
    endChildUid: 'c',
    payload: { text: '新概要', style: { color: 'red', width: 1 } },
    sortOrder: 2,
  }
  assert.deepEqual(readCrossNodeRecordStateV2(docs.first).summaries.summary, expected)
  assert.deepEqual(readCrossNodeRecordStateV2(docs.second).summaries.summary, expected)
  Object.values(docs).filter(value => value instanceof Y.Doc).forEach(doc => doc.destroy())
})

test('关系删除与字段编辑并发时删除获胜且迟到字段不会复活记录', () => {
  const relation = {
    relationUid: 'relation',
    sourceUid: 'root',
    targetUid: 'child',
    text: '旧文字',
    styleData: { color: 'red' },
  }
  const docs = forkSeed({ relations: { relation } })
  const deleteDelta = emptyDelta()
  deleteDelta.relations.deletedKeys.push('relation')
  const updateDelta = emptyDelta()
  updateDelta.relations.upserts.relation = { ...relation, text: '并发新文字' }
  applyCrossNodeRecordDeltaV2(docs.first, deleteDelta)
  applyCrossNodeRecordDeltaV2(docs.second, updateDelta)
  exchangeConcurrentUpdates(docs.first, docs.second, docs.baseVector)

  assert.deepEqual(readCrossNodeRecordStateV2(docs.first).relations, {})
  assert.deepEqual(readCrossNodeRecordStateV2(docs.second).relations, {})
  Object.values(docs).filter(value => value instanceof Y.Doc).forEach(doc => doc.destroy())
})

test('删除后重建使用新世代并隔离仍从旧世代发出的迟到编辑', () => {
  const relation = {
    relationUid: 'relation', sourceUid: 'root', targetUid: 'child',
    text: '旧文字', styleData: { color: 'red' },
  }
  const docs = forkSeed({ relations: { relation } })
  const staleBaseVector = docs.baseVector
  const deleteDelta = emptyDelta()
  deleteDelta.relations.deletedKeys.push('relation')
  applyCrossNodeRecordDeltaV2(docs.first, deleteDelta)
  const recreateDelta = emptyDelta()
  recreateDelta.relations.upserts.relation = {
    ...relation,
    text: '重建后的文字',
    styleData: { color: 'green' },
  }
  applyCrossNodeRecordDeltaV2(docs.first, recreateDelta)

  const staleDelta = emptyDelta()
  staleDelta.relations.upserts.relation = {
    ...relation,
    text: '旧标签页迟到文字',
    styleData: { color: 'blue' },
  }
  applyCrossNodeRecordDeltaV2(docs.second, staleDelta)
  exchangeConcurrentUpdates(docs.first, docs.second, staleBaseVector)

  for (const doc of [docs.first, docs.second]) {
    assert.equal(
      readCrossNodeRecordStateV2(doc).relations.relation.text,
      '重建后的文字',
    )
    assert.equal(
      readCrossNodeRecordStateV2(doc).relations.relation.styleData.color,
      'green',
    )
  }
  Object.values(docs).filter(value => value instanceof Y.Doc).forEach(doc => doc.destroy())
})

test('对象子树删除后重建会推进记录世代并隔离旧子树写入', () => {
  const relation = {
    relationUid: 'relation', sourceUid: 'root', targetUid: 'child',
    text: '保留文字', styleData: { color: 'red', width: 1 },
  }
  const docs = forkSeed({ relations: { relation } })
  const removeStyle = emptyDelta()
  const withoutStyle = { ...relation }
  delete withoutStyle.styleData
  removeStyle.relations.upserts.relation = withoutStyle
  applyCrossNodeRecordDeltaV2(docs.first, removeStyle)
  const recreateStyle = emptyDelta()
  recreateStyle.relations.upserts.relation = {
    ...relation,
    styleData: { color: 'green', width: 2 },
  }
  applyCrossNodeRecordDeltaV2(docs.first, recreateStyle)

  const staleStyle = emptyDelta()
  staleStyle.relations.upserts.relation = {
    ...relation,
    text: '另一端保留的新文字',
    styleData: { color: 'blue', width: 1 },
  }
  applyCrossNodeRecordDeltaV2(docs.second, staleStyle)
  exchangeConcurrentUpdates(docs.first, docs.second, docs.baseVector)

  for (const doc of [docs.first, docs.second]) {
    assert.deepEqual(
      readCrossNodeRecordStateV2(doc).relations.relation.styleData,
      { color: 'green', width: 2 },
    )
    assert.equal(
      readCrossNodeRecordStateV2(doc).relations.relation.text,
      '另一端保留的新文字',
    )
  }
  Object.values(docs).filter(value => value instanceof Y.Doc).forEach(doc => doc.destroy())
})

test('两个客户端并发创建同一记录时按固定字段路径合并而无容器身份冲突', () => {
  const docs = forkSeed({})
  const firstDelta = emptyDelta()
  firstDelta.relations.upserts.relation = {
    relationUid: 'relation', sourceUid: 'root', targetUid: 'child',
    text: '客户端 A', styleData: { color: 'red' },
  }
  const secondDelta = emptyDelta()
  secondDelta.relations.upserts.relation = {
    relationUid: 'relation', sourceUid: 'root', targetUid: 'child',
    text: '客户端 A', styleData: { color: 'red', width: 3 },
  }
  applyCrossNodeRecordDeltaV2(docs.first, firstDelta)
  applyCrossNodeRecordDeltaV2(docs.second, secondDelta)
  exchangeConcurrentUpdates(docs.first, docs.second, docs.baseVector)

  for (const doc of [docs.first, docs.second]) {
    assert.deepEqual(readCrossNodeRecordStateV2(doc).relations.relation, {
      relationUid: 'relation', sourceUid: 'root', targetUid: 'child',
      text: '客户端 A', styleData: { color: 'red', width: 3 },
    })
  }
  Object.values(docs).filter(value => value instanceof Y.Doc).forEach(doc => doc.destroy())
})

test('移除分组最后一个本地成员不会吞掉另一客户端并发新增的成员', () => {
  const group = {
    groupUid: 'group-1',
    groupType: 'outer_frame',
    payload: { color: 'red' },
    memberUids: ['old'],
  }
  const docs = forkSeed({ groups: { 'group-1': group } })
  const removeDelta = emptyDelta()
  removeDelta.groups.upserts['group-1'] = { ...group, memberUids: [] }
  const addDelta = emptyDelta()
  addDelta.groups.upserts['group-1'] = { ...group, memberUids: ['old', 'new'] }
  applyCrossNodeRecordDeltaV2(docs.first, removeDelta)
  applyCrossNodeRecordDeltaV2(docs.second, addDelta)
  exchangeConcurrentUpdates(docs.first, docs.second, docs.baseVector)

  for (const doc of [docs.first, docs.second]) {
    assert.deepEqual(
      readCrossNodeRecordStateV2(doc).groups['group-1'].memberUids,
      ['new'],
    )
  }
  Object.values(docs).filter(value => value instanceof Y.Doc).forEach(doc => doc.destroy())
})

test('同一分组成员移除后重加会隔离旧标签页仍发出的成员删除', () => {
  const group = {
    groupUid: 'group-1', groupType: 'outer_frame', payload: {}, memberUids: ['m'],
  }
  const docs = forkSeed({ groups: { 'group-1': group } })
  const remove = emptyDelta()
  remove.groups.upserts['group-1'] = { ...group, memberUids: [] }
  applyCrossNodeRecordDeltaV2(docs.first, remove)
  const readd = emptyDelta()
  readd.groups.upserts['group-1'] = group
  applyCrossNodeRecordDeltaV2(docs.first, readd)
  const staleRemoveWithPayload = emptyDelta()
  staleRemoveWithPayload.groups.upserts['group-1'] = {
    ...group,
    payload: { remoteSetting: 'kept' },
    memberUids: [],
  }
  applyCrossNodeRecordDeltaV2(docs.second, staleRemoveWithPayload)
  exchangeConcurrentUpdates(docs.first, docs.second, docs.baseVector)

  for (const doc of [docs.first, docs.second]) {
    assert.deepEqual(
      readCrossNodeRecordStateV2(doc).groups['group-1'].memberUids,
      ['m'],
    )
    assert.deepEqual(
      readCrossNodeRecordStateV2(doc).groups['group-1'].payload,
      { remoteSetting: 'kept' },
    )
  }
  Object.values(docs).filter(value => value instanceof Y.Doc).forEach(doc => doc.destroy())
})

test('同一 v1 语义被两个客户端同时迁移后仍共享固定字段地址', () => {
  const state = {
    relations: {
      relation: {
        relationUid: 'relation', sourceUid: 'root', targetUid: 'child',
        text: '旧文字', styleData: { color: 'red', width: 1 },
      },
    },
  }
  const first = new Y.Doc()
  const second = new Y.Doc()
  replaceCrossNodeRecordStateV2(first, state)
  replaceCrossNodeRecordStateV2(second, state)
  Y.applyUpdate(first, Y.encodeStateAsUpdate(second))
  Y.applyUpdate(second, Y.encodeStateAsUpdate(first))
  const convergedVector = Y.encodeStateVector(first)
  const firstDelta = emptyDelta()
  firstDelta.relations.upserts.relation = {
    ...state.relations.relation,
    text: '新文字',
  }
  const secondDelta = emptyDelta()
  secondDelta.relations.upserts.relation = {
    ...state.relations.relation,
    styleData: { color: 'blue', width: 1 },
  }
  applyCrossNodeRecordDeltaV2(first, firstDelta)
  applyCrossNodeRecordDeltaV2(second, secondDelta)
  exchangeConcurrentUpdates(first, second, convergedVector)

  assert.deepEqual(readCrossNodeRecordStateV2(first), readCrossNodeRecordStateV2(second))
  assert.equal(readCrossNodeRecordStateV2(first).relations.relation.text, '新文字')
  assert.equal(readCrossNodeRecordStateV2(first).relations.relation.styleData.color, 'blue')
  first.destroy()
  second.destroy()
})

test('一千层对象使用定长父路径地址并在线性体积内写入和恢复', () => {
  const depth = 1_000
  let styleData = { leaf: 'ok' }
  for (let index = 0; index < depth; index += 1) {
    styleData = { child: styleData }
  }
  const relation = {
    relationUid: 'relation',
    sourceUid: 'root',
    targetUid: 'child',
    styleData,
  }
  const doc = new Y.Doc()
  const startedAt = performance.now()

  replaceCrossNodeRecordStateV2(doc, { relations: { relation } })
  const restored = readCrossNodeRecordStateV2(doc).relations.relation
  const elapsed = performance.now() - startedAt

  const fieldKeys = [...doc.getMap(CROSS_NODE_FIELDS_MAP).keys()]
  assert.ok(fieldKeys.length >= depth)
  assert.ok(Math.max(...fieldKeys.map(key => key.length)) < 160)
  assert.ok(Y.encodeStateAsUpdate(doc).byteLength < 1_000_000)
  assert.ok(elapsed < 2_000, `深对象写入和恢复耗时 ${Math.round(elapsed)}ms`)
  let cursor = restored.styleData
  for (let index = 0; index < depth; index += 1) cursor = cursor.child
  assert.equal(cursor.leaf, 'ok')
  doc.destroy()
})

test('五千层 atomic 数组对象在 structuredClone 栈溢出时回退到迭代复制', () => {
  const depth = 5_000
  let nested = { leaf: 'ok' }
  for (let index = 0; index < depth; index += 1) nested = { child: nested }
  const previousStructuredClone = globalThis.structuredClone
  globalThis.structuredClone = () => {
    throw new RangeError('Maximum call stack size exceeded')
  }
  const first = new Y.Doc()
  const second = new Y.Doc()
  const startedAt = performance.now()
  try {
    replaceCrossNodeRecordStateV2(first, {
      assets: { asset: { assetKey: 'asset', uri: [nested] } },
    })
    Y.applyUpdate(second, Y.encodeStateAsUpdate(first))
    const restored = readCrossNodeRecordStateV2(second).assets.asset.uri[0]
    const elapsed = performance.now() - startedAt
    let cursor = restored
    for (let index = 0; index < depth; index += 1) cursor = cursor.child
    assert.equal(cursor.leaf, 'ok')
    assert.ok(elapsed < 2_000, `atomic 深对象同步和恢复耗时 ${Math.round(elapsed)}ms`)
  } finally {
    globalThis.structuredClone = previousStructuredClone
    first.destroy()
    second.destroy()
  }
})

test('structuredClone 拒绝的非 JSON 值不会在迭代回退中被静默丢弃', () => {
  const doc = new Y.Doc()
  const initialState = {
    relations: {
      existing: {
        relationUid: 'existing', sourceUid: 'root', targetUid: 'child', text: '保留',
      },
    },
  }
  try {
    replaceCrossNodeRecordStateV2(doc, initialState)
    assert.throws(
      () => replaceCrossNodeRecordStateV2(doc, {
        relations: {
          relation: {
            relationUid: 'relation',
            sourceUid: 'root',
            targetUid: 'child',
            styleData: { formatter: () => 'unsupported' },
          },
        },
      }),
      /\u65e0\u6cd5\u5b89\u5168\u590d\u5236|\u65e0\u6cd5\u5b89\u5168\u5e8f\u5217\u5316/,
    )
    const invalidDelta = emptyDelta()
    invalidDelta.relations.deletedKeys.push('existing')
    invalidDelta.assets.upserts.valid = { assetKey: 'valid', uri: 'valid.png' }
    invalidDelta.assets.upserts.invalid = {
      assetKey: 'invalid', uri: [new Map([['key', 'value']])],
    }
    assert.throws(
      () => applyCrossNodeRecordDeltaV2(doc, invalidDelta),
      /无法安全序列化/,
    )
    assert.deepEqual(readCrossNodeRecordStateV2(doc).relations, initialState.relations)
    assert.deepEqual(readCrossNodeRecordStateV2(doc).assets, {})
  } finally {
    doc.destroy()
  }
})
