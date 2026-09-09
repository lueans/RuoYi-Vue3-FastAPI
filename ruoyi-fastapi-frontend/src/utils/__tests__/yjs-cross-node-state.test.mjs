import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyCrossNodeState,
  buildCrossNodeStateDelta,
  detailListTouchesCrossNodeState,
  extractCrossNodeState,
  mergeJsonValueDelta,
  stripCrossNodeData,
} from '../yjs-cross-node-state.js'

function createCrossNodeTree() {
  return {
    data: {
      uid: 'root',
      text: '根节点',
      associativeLineTargets: ['right'],
      associativeLineTargetControlOffsets: [[1, 2]],
      associativeLinePoint: [[3, 4]],
      associativeLineText: { right: '关联' },
      associativeLineStyle: { right: { lineColor: '#f00' } },
      generalization: [{ uid: 'summary-1', range: [0, 1], text: '概要' }],
      imgMap: { cover: 'data:image/png;base64,AA==' },
    },
    children: [
      {
        data: { uid: 'left', text: '左', outerFrame: { groupId: 'group-1', lineColor: '#0f0' } },
        children: [],
      },
      {
        data: { uid: 'right', text: '右', outerFrame: { groupId: 'group-1', lineColor: '#0f0' } },
        children: [],
      },
    ],
  }
}

test('跨节点状态可拆分并无损恢复 simple-mind-map 数据形态', () => {
  const tree = createCrossNodeTree()
  const state = extractCrossNodeState(tree)
  assert.deepEqual(Object.keys(state.relations), ['assoc:root:right'])
  assert.equal(Object.values(state.summaries)[0].startChildUid, 'left')
  assert.deepEqual(state.groups['group-1'].memberUids, ['left', 'right'])
  assert.equal(state.assets.cover.uri, 'data:image/png;base64,AA==')

  const stripped = structuredClone(tree)
  const walk = node => {
    node.data = stripCrossNodeData(node.data)
    node.children.forEach(walk)
  }
  walk(stripped)
  applyCrossNodeState(stripped, state)

  assert.deepEqual(stripped, tree)
})

test('概要选中态不会进入协作记录且旧记录也不会恢复到画布', () => {
  const tree = createCrossNodeTree()
  tree.data.generalization[0].isActive = true

  const state = extractCrossNodeState(tree)
  const summary = state.summaries['root:summary-1']
  assert.equal(
    Object.prototype.hasOwnProperty.call(summary.payload, 'isActive'),
    false,
  )

  summary.payload.isActive = true
  const stripped = structuredClone(tree)
  stripped.data = stripCrossNodeData(stripped.data)
  applyCrossNodeState(stripped, state)

  assert.equal(
    Object.prototype.hasOwnProperty.call(
      stripped.data.generalization[0],
      'isActive',
    ),
    false,
  )
})

test('关联数据被移除时旧节点快照也会触发独立状态同步', () => {
  const oldNode = createCrossNodeTree()
  const nextNode = structuredClone(oldNode)
  delete nextNode.data.associativeLineTargets
  delete nextNode.data.associativeLineTargetControlOffsets
  delete nextNode.data.associativeLinePoint
  delete nextNode.data.associativeLineText
  delete nextNode.data.associativeLineStyle

  assert.equal(detailListTouchesCrossNodeState([{
    action: 'update',
    oldData: oldNode,
    data: nextNode,
  }]), true)
})

test('普通节点字段更新不会用整树快照回写未变化的跨节点记录', () => {
  const oldNode = createCrossNodeTree()
  const nextNode = structuredClone(oldNode)
  nextNode.data.text = '只修改节点文字'

  assert.equal(detailListTouchesCrossNodeState([{
    action: 'update',
    oldData: oldNode,
    data: nextNode,
  }]), false)
})

test('跨节点增量只更新本地改动的关系记录', () => {
  const previous = createCrossNodeTree()
  previous.data.associativeLineTargets = ['left', 'right']
  previous.data.associativeLineText = { left: 'A-old', right: 'B-old' }
  const current = structuredClone(previous)
  current.data.associativeLineText.left = 'A-local'
  const existing = extractCrossNodeState(previous)
  existing.relations['assoc:root:right'].text = 'B-remote'

  const delta = buildCrossNodeStateDelta([{
    action: 'update',
    oldData: previous,
    data: current,
  }], current, existing)

  assert.deepEqual(Object.keys(delta.relations.upserts), ['assoc:root:left'])
  assert.equal(delta.relations.upserts['assoc:root:left'].text, 'A-local')
  assert.deepEqual(delta.relations.deletedKeys, [])
  assert.equal(
    Object.prototype.hasOwnProperty.call(delta.relations.upserts, 'assoc:root:right'),
    false,
  )
})

test('缺少 oldData 的完整节点更新仍能清理已移除关系', () => {
  const previous = createCrossNodeTree()
  const current = structuredClone(previous)
  delete current.data.associativeLineTargets
  delete current.data.associativeLineTargetControlOffsets
  delete current.data.associativeLinePoint
  delete current.data.associativeLineText
  delete current.data.associativeLineStyle

  const delta = buildCrossNodeStateDelta([{
    action: 'update',
    data: current,
  }], current, extractCrossNodeState(previous), extractCrossNodeState(previous))

  assert.deepEqual(delta.relations.deletedKeys, ['assoc:root:right'])
  assert.deepEqual(delta.relations.upserts, {})
})

test('缺少 oldData 的旧运行时快照只提交相对画布基线的本地变化', () => {
  const runtimeBefore = createCrossNodeTree()
  runtimeBefore.data.associativeLineTargets = ['left']
  runtimeBefore.data.associativeLineText = { left: 'A-old' }
  const runtimeAfter = structuredClone(runtimeBefore)
  runtimeAfter.data.text = '仅修改普通文字'
  const existing = extractCrossNodeState(runtimeBefore)
  existing.relations['assoc:root:left'].text = 'A-remote'
  existing.relations['assoc:root:right'] = {
    relationUid: 'assoc:root:right',
    relationType: 'associative_line',
    sourceUid: 'root',
    targetUid: 'right',
    text: 'C-remote',
    controlData: {},
    sortOrder: 1,
  }

  const delta = buildCrossNodeStateDelta([{
    action: 'update',
    data: runtimeAfter,
  }], runtimeAfter, existing, extractCrossNodeState(runtimeBefore))

  assert.equal(delta, null)
})

test('关系顺移只合并排序字段并保留同记录的远端文字', () => {
  const runtimeBefore = createCrossNodeTree()
  runtimeBefore.data.associativeLineTargets = ['left', 'right']
  runtimeBefore.data.associativeLineText = { left: 'A-old', right: 'B-old' }
  const runtimeAfter = structuredClone(runtimeBefore)
  runtimeAfter.data.associativeLineTargets = ['right']
  runtimeAfter.data.associativeLineText = { right: 'B-old' }
  const existing = extractCrossNodeState(runtimeBefore)
  existing.relations['assoc:root:right'].text = 'B-remote'

  const delta = buildCrossNodeStateDelta([{
    action: 'update',
    oldData: runtimeBefore,
    data: runtimeAfter,
  }], runtimeAfter, existing, extractCrossNodeState(runtimeBefore))

  assert.deepEqual(delta.relations.deletedKeys, ['assoc:root:left'])
  assert.equal(delta.relations.upserts['assoc:root:right'].sortOrder, 0)
  assert.equal(delta.relations.upserts['assoc:root:right'].text, 'B-remote')
})

test('远端已删除的关系不会被旧画布上的本地编辑残缺复活', () => {
  const runtimeBefore = createCrossNodeTree()
  const runtimeAfter = structuredClone(runtimeBefore)
  runtimeAfter.data.associativeLineText.right = '本地迟到编辑'
  const existing = extractCrossNodeState(runtimeBefore)
  delete existing.relations['assoc:root:right']

  const delta = buildCrossNodeStateDelta([{
    action: 'update',
    oldData: runtimeBefore,
    data: runtimeAfter,
  }], runtimeAfter, existing, extractCrossNodeState(runtimeBefore))

  assert.equal(delta, null)
})

test('概要端点和内容分别三方合并且分组成员按集合增量合并', () => {
  const runtimeBefore = createCrossNodeTree()
  const runtimeAfter = structuredClone(runtimeBefore)
  runtimeAfter.children.reverse()
  runtimeAfter.children.find(child => child.data.uid === 'left').data.outerFrame = undefined

  const existing = extractCrossNodeState(runtimeBefore)
  existing.summaries['root:summary-1'].payload.text = '远端概要文字'
  existing.groups['group-1'].memberUids.push('remote-member')

  const delta = buildCrossNodeStateDelta([{
    action: 'update',
    oldData: runtimeBefore,
    data: runtimeAfter,
  }], runtimeAfter, existing, extractCrossNodeState(runtimeBefore))

  assert.equal(delta.summaries.upserts['root:summary-1'].payload.text, '远端概要文字')
  assert.equal(delta.summaries.upserts['root:summary-1'].startChildUid, 'right')
  assert.deepEqual(
    delta.groups.upserts['group-1'].memberUids,
    ['remote-member', 'right'],
  )
})

test('JSON 字段三方合并保留远端分支并严格处理增删、类型和原子数组', () => {
  const previous = {
    unchanged: { value: 'base' },
    changed: { local: 'old', untouched: 'base' },
    removed: 'old',
    strict: false,
    atomic: [{ value: 1 }],
    typeToObject: 1,
    objectToPrimitive: { value: 1 },
  }
  const next = {
    unchanged: { value: 'base' },
    changed: { local: 'new', untouched: 'base' },
    strict: 0,
    atomic: [{ value: 2 }],
    typeToObject: { local: true },
    objectToPrimitive: 'local',
    added: { local: true },
  }
  Object.defineProperty(next, '__proto__', {
    enumerable: true,
    value: { local: 'safe' },
  })
  const existing = {
    remoteTop: 'kept',
    unchanged: { value: 'remote' },
    changed: { local: 'remote', untouched: 'remote-kept', remote: true },
    removed: 'remote',
    strict: true,
    atomic: [{ value: 'remote' }],
    typeToObject: { remote: true },
    objectToPrimitive: { remote: true },
    added: { remote: true },
  }

  const merged = mergeJsonValueDelta(existing, previous, next)

  assert.equal(merged.remoteTop, 'kept')
  assert.deepEqual(merged.unchanged, { value: 'remote' })
  assert.deepEqual(merged.changed, {
    local: 'new', untouched: 'remote-kept', remote: true,
  })
  assert.equal(Object.prototype.hasOwnProperty.call(merged, 'removed'), false)
  assert.equal(merged.strict, 0)
  assert.deepEqual(merged.atomic, [{ value: 2 }])
  assert.deepEqual(merged.typeToObject, { local: true })
  assert.equal(merged.objectToPrimitive, 'local')
  assert.deepEqual(merged.added, { local: true })
  assert.equal(Object.getPrototypeOf(merged), Object.prototype)
  assert.deepEqual(merged.__proto__, { local: 'safe' })

  merged.changed.remote = false
  merged.atomic[0].value = 3
  merged.added.local = false
  assert.equal(existing.changed.remote, true)
  assert.equal(next.atomic[0].value, 2)
  assert.equal(next.added.local, true)
  assert.equal(existing.added.remote, true)

  const rootExisting = { remote: { value: true } }
  const unchangedRoot = mergeJsonValueDelta(
    rootExisting,
    { stable: {} },
    { stable: {} },
  )
  unchangedRoot.remote.value = false
  assert.equal(rootExisting.remote.value, true)
  assert.deepEqual(
    mergeJsonValueDelta({ remote: true }, 1, { local: true }),
    { local: true },
  )
})

test('5k/20k 深层叶子变化用单次迭代三方遍历合并', () => {
  for (const depth of [5_000, 20_000]) {
    let previous = { local: 'old', stable: 'same' }
    let next = { local: 'new', stable: 'same' }
    let existing = { local: 'remote', stable: 'remote-kept', remote: true }
    for (let index = 0; index < depth; index += 1) {
      previous = { child: previous }
      next = { child: next }
      existing = { child: existing }
    }

    const startedAt = performance.now()
    const merged = mergeJsonValueDelta(existing, previous, next)
    const elapsed = performance.now() - startedAt
    let leaf = merged
    for (let index = 0; index < depth; index += 1) leaf = leaf.child

    assert.deepEqual(leaf, {
      local: 'new', stable: 'remote-kept', remote: true,
    })
    assert.ok(elapsed < 2_000, `${depth} 层三方合并耗时 ${Math.round(elapsed)}ms`)
    leaf.remote = false
    let existingLeaf = existing
    for (let index = 0; index < depth; index += 1) existingLeaf = existingLeaf.child
    assert.equal(existingLeaf.remote, true)
  }
})

test('同排序值的关系和概要始终按稳定标识重建', () => {
  const createBareTree = () => ({
    data: { uid: 'root' },
    children: [
      { data: { uid: 'a' }, children: [] },
      { data: { uid: 'b' }, children: [] },
    ],
  })
  const relations = {
    'assoc:root:b': {
      relationUid: 'assoc:root:b',
      relationType: 'associative_line',
      sourceUid: 'root',
      targetUid: 'b',
      sortOrder: 0,
    },
    'assoc:root:a': {
      relationUid: 'assoc:root:a',
      relationType: 'associative_line',
      sourceUid: 'root',
      targetUid: 'a',
      sortOrder: 0,
    },
  }
  const summaries = {
    'root:summary-b': {
      summaryUid: 'summary-b',
      ownerUid: 'root',
      startChildUid: 'b',
      endChildUid: 'b',
      payload: { text: 'B' },
      sortOrder: 0,
    },
    'root:summary-a': {
      summaryUid: 'summary-a',
      ownerUid: 'root',
      startChildUid: 'a',
      endChildUid: 'a',
      payload: { text: 'A' },
      sortOrder: 0,
    },
  }
  const forward = applyCrossNodeState(createBareTree(), { relations, summaries })
  const reverse = applyCrossNodeState(createBareTree(), {
    relations: Object.fromEntries(Object.entries(relations).reverse()),
    summaries: Object.fromEntries(Object.entries(summaries).reverse()),
  })

  assert.deepEqual(forward.data.associativeLineTargets, ['a', 'b'])
  assert.deepEqual(reverse.data.associativeLineTargets, ['a', 'b'])
  assert.deepEqual(
    forward.data.generalization.map(item => item.uid),
    ['summary-a', 'summary-b'],
  )
  assert.deepEqual(forward.data.generalization, reverse.data.generalization)
})

test('概要记录在子节点重排后重新绑定范围端点', () => {
  const previous = {
    data: {
      uid: 'root',
      generalization: [{ uid: 'summary-1', range: [0, 0], text: '第一项概要' }],
    },
    children: [
      { data: { uid: 'a' }, children: [] },
      { data: { uid: 'b' }, children: [] },
    ],
  }
  const current = structuredClone(previous)
  current.children.reverse()
  assert.equal(detailListTouchesCrossNodeState([{
    action: 'update',
    oldData: previous,
    data: current,
  }]), true)

  const delta = buildCrossNodeStateDelta([{
    action: 'update',
    oldData: previous,
    data: current,
  }], current, extractCrossNodeState(previous))
  const summary = delta.summaries.upserts['root:summary-1']

  assert.equal(summary.startChildUid, 'b')
  assert.equal(summary.endChildUid, 'b')
})

test('关联目标节点删除后不会保留悬空关联记录', () => {
  const tree = createCrossNodeTree()
  tree.children = tree.children.filter(child => child.data.uid !== 'right')

  const state = extractCrossNodeState(tree)

  assert.deepEqual(state.relations, {})
})

test('一万二千层跨节点状态可拆分恢复且循环引用不会耗尽调用栈', () => {
  const root = {
    data: {
      uid: 'node-0',
      associativeLineTargets: ['node-11999'],
      associativeLineText: { 'node-11999': '深层关联' },
    },
    children: [],
  }
  let cursor = root
  for (let index = 1; index < 12000; index += 1) {
    const child = { data: { uid: `node-${index}` }, children: [] }
    cursor.children.push(child)
    cursor = child
  }
  cursor.data.outerFrame = { groupId: 'deep-group', lineColor: '#0f0' }
  cursor.children.push(root)

  const state = extractCrossNodeState(root)
  assert.equal(state.relations['assoc:node-0:node-11999'].text, '深层关联')
  assert.deepEqual(state.groups['deep-group'].memberUids, ['node-11999'])

  applyCrossNodeState(root, state)
  assert.deepEqual(root.data.associativeLineTargets, ['node-11999'])
  assert.equal(root.data.associativeLineText['node-11999'], '深层关联')
  assert.equal(cursor.data.outerFrame.groupId, 'deep-group')
})

test('structuredClone 缺失或栈溢出时跨节点数据使用迭代复制并拒绝循环对象', () => {
  const previousStructuredClone = globalThis.structuredClone
  globalThis.structuredClone = () => {
    throw new RangeError('Maximum call stack size exceeded')
  }
  try {
    const deepStyle = { level: 0 }
    let cursor = deepStyle
    for (let level = 1; level < 20_000; level += 1) {
      cursor.child = { level }
      cursor = cursor.child
    }
    const tree = createCrossNodeTree()
    tree.data.associativeLineStyle.right = deepStyle
    const state = extractCrossNodeState(tree)
    cursor = state.relations['assoc:root:right'].styleData
    let depth = 1
    while (cursor.child) {
      cursor = cursor.child
      depth += 1
    }
    assert.equal(depth, 20_000)

    const cycle = {}
    cycle.self = cycle
    tree.data.associativeLineStyle.right = cycle
    assert.throws(() => extractCrossNodeState(tree), /无法安全复制/)
  } finally {
    globalThis.structuredClone = previousStructuredClone
  }
})
