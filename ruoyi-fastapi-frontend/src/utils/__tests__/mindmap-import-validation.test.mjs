import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  MAX_MINDMAP_NODE_COUNT,
  MAX_MINDMAP_STABLE_UID_LENGTH,
  MAX_MINDMAP_TREE_DEPTH,
  assertMindmapImportDocument,
} from '../mindmap-import-validation.js'

const createNode = (uid, children) => ({
  data: uid === undefined ? {} : { uid },
  ...(children === undefined ? {} : { children }),
})

const createChain = length => {
  const root = createNode('1')
  let current = root
  for (let depth = 2; depth <= length; depth += 1) {
    const child = createNode(String(depth))
    current.children = [child]
    current = child
  }
  return root
}

test('import validation accepts bare and full documents and reports stable metrics', () => {
  const root = createNode('root', [createNode(2), createNode(undefined)])
  assert.deepEqual(assertMindmapImportDocument(root), {
    root,
    nodeCount: 3,
    treeDepth: 2,
  })
  assert.deepEqual(assertMindmapImportDocument({ root, layout: 'mindMap' }), {
    root,
    nodeCount: 3,
    treeDepth: 2,
  })
})

test('import validation rejects malformed root, data, children and child nodes', () => {
  assert.throws(() => assertMindmapImportDocument(null), /不是有效的脑图文档/)
  assert.throws(() => assertMindmapImportDocument({ children: [] }), /有效的脑图根节点/)
  assert.throws(
    () => assertMindmapImportDocument({ root: [], data: {} }),
    /有效的脑图根节点/
  )
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', {})),
    /children 必须是数组/
  )
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', [null])),
    /子节点必须是对象/
  )
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', [{ data: 'bad' }])),
    /data 必须是对象/
  )
})

test('import validation enforces the 20,000-node persistence boundary', () => {
  const root = createNode('root', Array.from(
    { length: MAX_MINDMAP_NODE_COUNT - 1 },
    (_, index) => createNode(String(index + 1))
  ))
  assert.equal(assertMindmapImportDocument(root).nodeCount, MAX_MINDMAP_NODE_COUNT)
  root.children.push(createNode('overflow'))
  assert.throws(
    () => assertMindmapImportDocument(root),
    /节点数量不能超过 20000/
  )
})

test('import validation enforces the 256-level persistence boundary iteratively', () => {
  assert.equal(
    assertMindmapImportDocument(createChain(MAX_MINDMAP_TREE_DEPTH)).treeDepth,
    MAX_MINDMAP_TREE_DEPTH
  )
  assert.throws(
    () => assertMindmapImportDocument(createChain(MAX_MINDMAP_TREE_DEPTH + 1)),
    /脑图层级不能超过 256/
  )
})

test('import validation rejects cycles, shared objects and unstable identifiers', () => {
  const cycle = createNode('cycle', [])
  cycle.children.push(cycle)
  assert.throws(() => assertMindmapImportDocument(cycle), /循环或重复引用/)

  const shared = createNode('shared')
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', [shared, shared])),
    /循环或重复引用/
  )

  const sharedData = {}
  assert.throws(
    () => assertMindmapImportDocument({
      data: sharedData,
      children: [{ data: sharedData }],
    }),
    /重复数据引用/
  )
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', [createNode('root')])),
    /UID 重复: root/
  )
  assert.throws(() => assertMindmapImportDocument(createNode(' padded ')), /首尾空白/)
  assert.throws(
    () => assertMindmapImportDocument(createNode('x'.repeat(MAX_MINDMAP_STABLE_UID_LENGTH + 1))),
    /UID 不能超过 64 个字符/
  )
  assert.throws(() => assertMindmapImportDocument(createNode({})), /字符串或数字/)
  assert.throws(() => assertMindmapImportDocument(createNode(Infinity)), /有限数字/)
})

test('import parsing and editor replacement both use the shared validation boundary', async () => {
  const [importSource, editSource] = await Promise.all([
    readFile(new URL('../../components/MindMap/Import.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
  ])
  assert.match(importSource, /import \{ assertMindmapImportDocument \}/)
  assert.equal((importSource.match(/assertMindmapImportDocument\(data\)/g) || []).length, 1)
  assert.doesNotMatch(importSource, /function isMindmapDocument/)
  assert.match(editSource, /async function onSetData\(data, request = \{\}\)/)
  assert.match(editSource, /assertMindmapImportDocument\(data\)/)
})

test('cloud import replaces the document through one durable snapshot before reporting success', async () => {
  const editSource = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const importBlock = editSource.match(
    /async function onSetData\(data, request = \{\}\)[\s\S]*?^\}/m,
  )?.[0] || ''

  const flushExisting = importBlock.indexOf('await flushBeforeLeave()')
  const blockEditing = importBlock.indexOf('setImportTransitionEditingBlocked(true)')
  const finalCommit = importBlock.indexOf(
    'commitActiveEditorsBeforeTermination()',
    flushExisting,
  )
  const finalTick = importBlock.indexOf('await nextTick()', finalCommit)
  const generationFence = importBlock.indexOf(
    'draftProtection.getChangeVersion() !== importBoundaryChangeVersion',
    finalTick,
  )
  const stopOldYjs = importBlock.indexOf('stopCurrentCollaborationSource()')
  const replaceTree = Math.min(
    ...[
      importBlock.indexOf('activeMindMap.setFullData(data)'),
      importBlock.indexOf('activeMindMap.setData(data)'),
    ].filter(index => index >= 0),
  )
  const flushInitialHistory = importBlock.indexOf(
    'activeMindMap.command?.flushPendingHistory?.()',
  )
  const stageSnapshot = importBlock.indexOf(
    'pendingContentOperations = [{ type: CONTENT_SNAPSHOT_OPERATION }]',
  )
  const persistSnapshot = importBlock.indexOf('await flushPendingMindmapChanges({')
  const reportSuccess = importBlock.indexOf('request.resolve?.(true)')

  assert.match(editSource, /const CONTENT_SNAPSHOT_OPERATION = 'document\.content\.update'/)
  assert.ok([
    flushExisting,
    blockEditing,
    finalCommit,
    finalTick,
    generationFence,
    stopOldYjs,
    replaceTree,
    flushInitialHistory,
    stageSnapshot,
    persistSnapshot,
    reportSuccess,
  ].every(index => index >= 0))
  assert.ok(blockEditing < flushExisting)
  assert.ok(flushExisting < stopOldYjs)
  assert.ok(flushExisting < finalCommit)
  assert.ok(finalCommit < finalTick)
  assert.ok(finalTick < generationFence)
  assert.ok(generationFence < stopOldYjs)
  assert.ok(stopOldYjs < replaceTree)
  assert.ok(replaceTree < flushInitialHistory)
  assert.ok(flushInitialHistory < stageSnapshot)
  assert.ok(stageSnapshot < persistSnapshot)
  assert.ok(persistSnapshot < reportSuccess)
  assert.match(importBlock, /persistLocalBackup: persistLocalDraftBeforeUnload/)
  assert.match(
    importBlock,
    /serverCanEdit\.value !== true[\s\S]*?authoritativeRecoveryEditingBlocked\.value/,
  )
  assert.match(
    importBlock,
    /finally \{[\s\S]*?setImportTransitionEditingBlocked\(false\)[\s\S]*?resumeAfterEditingTransition\(\)/,
  )
  assert.doesNotMatch(
    importBlock.slice(blockEditing, stopOldYjs),
    /\|\| isReadonly\.value/,
  )
  assert.doesNotMatch(importBlock, /\bmanualSave\(\)/)
})

test('cloud import keeps collaboration detached until its snapshot is saved and fences partial apply failures', async () => {
  const editSource = await readFile(
    new URL('../../components/MindMap/Edit.vue', import.meta.url),
    'utf8',
  )
  const importBlock = editSource.match(
    /async function onSetData\(data, request = \{\}\)[\s\S]*?^\}/m,
  )?.[0] || ''
  const startBlock = editSource.match(
    /function startYjsSyncIfReady[\s\S]*?^\}/m,
  )?.[0] || ''
  const saveBlock = editSource.match(
    /async function saveToBackend[\s\S]*?function queueRemoteDocumentReset/,
  )?.[0] || ''

  const captureIndex = importBlock.indexOf(
    'protectedDocumentBeforeImportApply = getCurrentDocument()',
  )
  const deferIndex = importBlock.indexOf(
    'collaborationRestartDeferredUntilSave = true',
  )
  const stopIndex = importBlock.indexOf('stopCurrentCollaborationSource()', deferIndex)
  const replaceIndex = importBlock.indexOf('activeMindMap.setFullData(data)', stopIndex)
  const recoveryIndex = importBlock.indexOf(
    'await enterAuthoritativeApplyFailureRecovery(',
    replaceIndex,
  )
  const abandonIndex = importBlock.indexOf(
    'abandonPendingContentForAuthoritativeReload()',
    recoveryIndex,
  )
  const retryIndex = importBlock.indexOf('scheduleAuthoritativeReload()', abandonIndex)

  assert.ok(captureIndex >= 0)
  assert.ok(deferIndex > captureIndex)
  assert.ok(stopIndex > deferIndex)
  assert.ok(replaceIndex > stopIndex)
  assert.ok(recoveryIndex > replaceIndex)
  assert.ok(abandonIndex > recoveryIndex)
  assert.ok(retryIndex > abandonIndex)
  assert.match(startBlock, /\|\| collaborationRestartDeferredUntilSave/)
  assert.match(
    saveBlock,
    /collaborationRestartDeferredUntilSave = false[\s\S]*?startYjsSyncIfReady\(\)/,
  )
  assert.match(
    importBlock,
    /catch \(applyError\)[\s\S]*?protectedDocumentBeforeImportApply[\s\S]*?enterAuthoritativeApplyFailureRecovery/,
  )
})
