import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  assertMindmapSaveMutationResponse,
  captureRejectedMindmapMutationSnapshot,
  createMindmapSaveMutation,
  rebaseMindmapSaveMutation,
  submitMindmapSaveMutation,
} from '../mindmap-save-mutation.js'
import {
  applyCrossNodeOperationIntents,
  applyMindmapOperationIntents,
  buildCrossNodeContentOperations,
} from '../mindmap-operations.js'

const editorUrl = new URL('../../components/MindMap/Edit.vue', import.meta.url)
const apiUrl = new URL('../../api/mindmap/mindmap.js', import.meta.url)
const pageUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)
const appUrl = new URL('../../App.vue', import.meta.url)
const requestUrl = new URL('../request.js', import.meta.url)

test('mindmap editor messages start below the fixed command header', async () => {
  const source = await readFile(appUrl, 'utf8')

  assert.match(source, /<el-config-provider :message="elementMessageConfig">/)
  assert.match(source, /route\.path === '\/mindmap\/edit' \? 72 : 16/)
})

test('save mutation freezes one retryable idempotency payload away from live editor values', () => {
  const operations = [{ type: 'node.update', nodeUid: 'root', payload: { text: 'before' } }]
  const document = {
    root: { data: { uid: 'root', text: 'before' }, children: [] },
    view: { scale: 1 },
    layout: 'logicalStructure',
    theme: { template: 'classic' },
    documentData: { watermark: { text: 'draft' } },
  }
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'mutation-1',
    baseRevision: 7,
    operations,
    document,
    viewChangeVersion: 3,
    yjsUpdateCount: 2,
    yjsDeliveryMode: 'reload',
  })

  operations[0].payload.text = 'after'
  document.root.data.text = 'after'
  document.view.scale = 2

  assert.equal(Object.isFrozen(mutation), true)
  assert.equal(Object.isFrozen(mutation.payload), true)
  assert.equal(mutation.payload.clientMutationId, 'mutation-1')
  assert.equal(mutation.payload.baseRevision, 7)
  assert.equal(mutation.payload.operations[0].payload.text, 'before')
  assert.equal(mutation.payload.nodeTree.data.text, 'before')
  assert.equal(mutation.payload.viewData.scale, 1)
  assert.equal(mutation.payload.yjsUpdateCount, 2)
  assert.equal(mutation.payload.yjsDeliveryMode, 'reload')
  assert.equal(mutation.document.root.data.text, 'before')
  assert.throws(() => createMindmapSaveMutation({
    clientMutationId: 'invalid-delivery-mode',
    baseRevision: 1,
    operations: [{ type: 'file.view.update' }],
    document,
    viewChangeVersion: 0,
    yjsDeliveryMode: 'best-effort',
  }), /delivery mode/)
})

test('conflict recovery preserves the rejected mutation instead of a remote-overwritten canvas', () => {
  const rejectedDocument = {
    root: { data: { uid: 'root', text: '本地被拒绝的值' }, children: [] },
    layout: 'mindMap',
    theme: {},
    view: null,
    documentData: {},
  }
  const remotePreview = {
    ...rejectedDocument,
    root: { data: { uid: 'root', text: '远端 Yjs 胜出值' }, children: [] },
  }
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'rejected-local-mutation',
    baseRevision: 9,
    operations: [{
      type: 'node.update',
      nodeUid: 'root',
      targetRevision: 9,
      payload: { dataChanged: true, childrenChanged: false },
    }],
    document: rejectedDocument,
    viewChangeVersion: 0,
    contentChangeVersion: 3,
    yjsUpdateCount: 1,
  })

  const snapshot = captureRejectedMindmapMutationSnapshot({
    mutation,
    fallbackDocument: remotePreview,
  })

  assert.equal(snapshot.document.root.data.text, '本地被拒绝的值')
  assert.equal(snapshot.clientMutationId, 'rejected-local-mutation')
  assert.equal(snapshot.baseRevision, 9)
  assert.equal(snapshot.contentChangeVersion, 3)
  assert.equal(snapshot.yjsUpdateCount, 1)
  rejectedDocument.root.data.text = '调用后修改'
  assert.equal(snapshot.document.root.data.text, '本地被拒绝的值')

  const retried = captureRejectedMindmapMutationSnapshot({
    mutation: null,
    fallbackDocument: remotePreview,
    previousSnapshot: snapshot,
  })
  assert.equal(retried.document.root.data.text, '本地被拒绝的值')
  assert.equal(retried.yjsUpdateCount, 1)
})

test('conflict draft freezes local cross-node intent after a remote preview wins the canvas field', () => {
  const before = { assetKey: 'cover', uri: 'before.png' }
  const localAfter = { assetKey: 'cover', uri: 'local.png' }
  const [operation] = buildCrossNodeContentOperations(
    { assets: { cover: before } },
    { assets: { cover: localAfter } },
  )
  const remotePreview = {
    root: {
      data: { uid: 'root', imgMap: { cover: 'remote.png' } },
      children: [],
    },
    layout: 'mindMap',
    theme: {},
    view: null,
    documentData: {},
  }
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'rejected-cross-node-intent',
    baseRevision: 4,
    operations: [operation],
    document: applyCrossNodeOperationIntents(remotePreview, [operation]),
    viewChangeVersion: 0,
    contentChangeVersion: 1,
  })

  const snapshot = captureRejectedMindmapMutationSnapshot({ mutation })

  assert.equal(snapshot.document.root.data.imgMap.cover, 'local.png')
  assert.equal(remotePreview.root.data.imgMap.cover, 'remote.png')
})

test('conflict draft freezes local node intent after a remote preview wins the same field', () => {
  const operation = {
    type: 'node.update',
    nodeUid: 'root',
    targetRevision: 4,
    payload: {
      previousData: { uid: 'root', text: 'before' },
      data: { uid: 'root', text: 'mine' },
      dataChanged: true,
      childrenChanged: false,
      childUids: [],
      oldChildUids: [],
    },
  }
  const remotePreview = {
    root: { data: { uid: 'root', text: 'theirs' }, children: [] },
    layout: 'mindMap',
    theme: {},
    view: null,
    documentData: {},
  }
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'rejected-node-intent',
    baseRevision: 4,
    operations: [operation],
    document: applyMindmapOperationIntents(remotePreview, [operation]),
    viewChangeVersion: 0,
    contentChangeVersion: 1,
    yjsUpdateCount: 1,
  })

  const snapshot = captureRejectedMindmapMutationSnapshot({ mutation })

  assert.equal(mutation.payload.nodeTree.data.text, 'mine')
  assert.equal(snapshot.document.root.data.text, 'mine')
  assert.equal(remotePreview.root.data.text, 'theirs')
})

test('save mutation validates response ownership before accepting a revision', () => {
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'mutation-2',
    baseRevision: 1,
    operations: [{ type: 'file.view.update' }],
    document: { root: {}, view: null, layout: 'mindMap', theme: {}, documentData: {} },
    viewChangeVersion: 1,
  })

  assert.doesNotThrow(() => assertMindmapSaveMutationResponse(mutation, {
    clientMutationId: 'mutation-2',
    contentRevision: 2,
  }))
  assert.throws(() => assertMindmapSaveMutationResponse(mutation, {
    clientMutationId: 'different',
    contentRevision: 2,
  }), /批次不匹配/)
})

test('granular mutation advances an incomplete-history baseline without changing its identity', () => {
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'mutation-rebase',
    baseRevision: 7,
    operations: [{
      type: 'node.create',
      nodeUid: 'new-node',
      payload: { data: { uid: 'new-node' } },
    }],
    document: {
      root: { data: { uid: 'root' }, children: [] },
      view: null,
      layout: 'mindMap',
      theme: {},
      documentData: {},
    },
    viewChangeVersion: 1,
  })

  const rebased = rebaseMindmapSaveMutation(mutation, {
    currentRevision: 10,
    requiresSnapshot: true,
  })

  assert.equal(rebased.clientMutationId, mutation.clientMutationId)
  assert.equal(rebased.baseRevision, 10)
  assert.equal(rebased.rebaseAttempts, 1)
  assert.deepEqual(rebased.operations, mutation.operations)
  assert.deepEqual(rebased.document, mutation.document)
})

test('view state can rebase together with granular node operations', () => {
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'mutation-view-rebase',
    baseRevision: 7,
    operations: [
      { type: 'file.view.update' },
      {
        type: 'node.create',
        nodeUid: 'new-node',
        payload: { data: { uid: 'new-node' } },
      },
    ],
    document: {
      root: { data: { uid: 'root' }, children: [] },
      view: { transform: { scaleX: 1.25, scaleY: 1.25 } },
      layout: 'mindMap',
      theme: {},
      documentData: {},
    },
    viewChangeVersion: 2,
  })

  const rebased = rebaseMindmapSaveMutation(mutation, {
    currentRevision: 9,
    requiresSnapshot: true,
  })

  assert.equal(rebased.baseRevision, 9)
  assert.deepEqual(rebased.operations, mutation.operations)
})

test('已发送 Yjs 帧的细粒度批次也禁止跨 revision 自动改基', async () => {
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'mutation-yjs-no-rebase',
    baseRevision: 7,
    operations: [{
      type: 'node.create',
      nodeUid: 'new-node',
      payload: { data: { uid: 'new-node' } },
    }],
    document: {
      root: { data: { uid: 'root' }, children: [] },
      view: null,
      layout: 'mindMap',
      theme: {},
      documentData: {},
    },
    viewChangeVersion: 1,
    yjsUpdateCount: 1,
  })
  const conflict = {
    currentRevision: 8,
    requiresSnapshot: true,
  }

  assert.equal(rebaseMindmapSaveMutation(mutation, conflict), null)
  let submissions = 0
  await assert.rejects(
    submitMindmapSaveMutation(mutation, async () => {
      submissions += 1
      throw Object.assign(new Error('stale'), { data: conflict })
    }),
    /stale/,
  )
  assert.equal(submissions, 1)
})

test('whole-document and semantic conflicts are never automatically rebased', () => {
  const createMutation = operations => createMindmapSaveMutation({
    clientMutationId: `mutation-${operations[0].type}`,
    baseRevision: 7,
    operations,
    document: {
      root: { data: { uid: 'root' }, children: [] },
      view: null,
      layout: 'mindMap',
      theme: {},
      documentData: {},
    },
    viewChangeVersion: 1,
  })

  assert.equal(rebaseMindmapSaveMutation(createMutation([
    { type: 'document.update' },
  ]), {
    currentRevision: 8,
    requiresSnapshot: true,
  }), null)
  assert.equal(rebaseMindmapSaveMutation(createMutation([
    { type: 'document.content.update' },
  ]), {
    currentRevision: 8,
    requiresSnapshot: true,
  }), null)
  assert.equal(rebaseMindmapSaveMutation(createMutation([
    { type: 'node.update', nodeUid: 'root', payload: {} },
  ]), {
    currentRevision: 8,
    requiresSnapshot: true,
    conflictNodeUids: ['root'],
  }), null)
  assert.equal(rebaseMindmapSaveMutation(createMutation([
    { type: 'file.theme.update' },
  ]), {
    currentRevision: 8,
    requiresSnapshot: true,
  }), null)
  assert.equal(rebaseMindmapSaveMutation(createMutation([
    {
      type: 'node.update',
      nodeUid: 'root',
      payload: { dataChanged: true, childrenChanged: false },
    },
  ]), {
    currentRevision: 8,
    requiresSnapshot: true,
  }), null)
})

test('revision-protected node data update can safely rebase when history was compacted', () => {
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'mutation-protected-update',
    baseRevision: 3,
    operations: [{
      type: 'node.update',
      nodeUid: 'root',
      targetRevision: 9,
      payload: { dataChanged: true, childrenChanged: false },
    }],
    document: {
      root: { data: { uid: 'root' }, children: [] },
      view: null,
      layout: 'mindMap',
      theme: {},
      documentData: {},
    },
    viewChangeVersion: 0,
  })

  assert.equal(rebaseMindmapSaveMutation(mutation, {
    currentRevision: 6,
    requiresSnapshot: true,
  })?.baseRevision, 6)
})

test('submission retries one granular batch on the new revision and reports the final mutation', async () => {
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'mutation-submit-rebase',
    baseRevision: 4,
    operations: [{ type: 'node.create', nodeUid: 'child', payload: { data: {} } }],
    document: {
      root: { data: { uid: 'root' }, children: [] },
      view: null,
      layout: 'mindMap',
      theme: {},
      documentData: {},
    },
    viewChangeVersion: 0,
  })
  const submittedRevisions = []
  const rebasedRevisions = []

  const result = await submitMindmapSaveMutation(
    mutation,
    async payload => {
      submittedRevisions.push(payload.baseRevision)
      if (submittedRevisions.length === 1) {
        const error = new Error('history compacted')
        error.data = { currentRevision: 7, requiresSnapshot: true }
        throw error
      }
      return { data: { clientMutationId: payload.clientMutationId, contentRevision: 8 } }
    },
    { onRebase: current => rebasedRevisions.push(current.baseRevision) },
  )

  assert.deepEqual(submittedRevisions, [4, 7])
  assert.deepEqual(rebasedRevisions, [7])
  assert.equal(result.mutation.baseRevision, 7)
  assert.equal(result.response.data.contentRevision, 8)
})

test('submission surfaces a real semantic conflict without retrying', async () => {
  const mutation = createMindmapSaveMutation({
    clientMutationId: 'mutation-submit-conflict',
    baseRevision: 4,
    operations: [{ type: 'node.update', nodeUid: 'root', payload: {} }],
    document: {
      root: { data: { uid: 'root' }, children: [] },
      view: null,
      layout: 'mindMap',
      theme: {},
      documentData: {},
    },
    viewChangeVersion: 0,
  })
  let submitCount = 0
  const conflict = new Error('same node conflict')
  conflict.data = {
    currentRevision: 5,
    requiresSnapshot: false,
    conflictNodeUids: ['root'],
  }

  await assert.rejects(
    submitMindmapSaveMutation(mutation, async () => {
      submitCount += 1
      throw conflict
    }),
    error => error === conflict,
  )
  assert.equal(submitCount, 1)
})

test('save mutation snapshots a 20,000-level compatibility document without recursion', () => {
  const root = { data: { uid: '0' }, children: [] }
  let current = root
  for (let depth = 1; depth < 20_000; depth += 1) {
    const child = { data: { uid: String(depth) }, children: [] }
    current.children.push(child)
    current = child
  }

  const mutation = createMindmapSaveMutation({
    clientMutationId: 'mutation-deep',
    baseRevision: 1,
    operations: [{ type: 'document.update' }],
    document: { root, view: null, layout: 'mindMap', theme: {}, documentData: {} },
    viewChangeVersion: 0,
  })
  current = mutation.payload.nodeTree
  let depth = 1
  while (current.children[0]) {
    current = current.children[0]
    depth += 1
  }
  assert.equal(depth, 20_000)
  assert.notEqual(mutation.payload.nodeTree, root)
})

test('editor separates in-flight and pending operations and reuses the same mutation payload', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''
  const dirtyBlock = source.match(/function hasUnsavedChanges[\s\S]*?\n\}/)?.[0] || ''
  const operationBlock = source.match(/function recordDocumentOperations[\s\S]*?\n\}/)?.[0] || ''

  assert.match(saveBlock, /if \(!activeSaveMutation\) \{[\s\S]*?createMindmapSaveMutation\(/)
  assert.match(saveBlock, /if \(activeSaveMutation\) \{[\s\S]*?pendingContentOperations = \[\]/)
  assert.match(saveBlock, /clientMutationId: pendingClientMutationId \|\| createMutationId\(\)|const clientMutationId = pendingClientMutationId \|\| createMutationId\(\)/)
  assert.match(saveBlock, /submitMindmapSaveMutation\(/)
  assert.match(
    saveBlock,
    /yjsSync\?\.markLocalMutation\?\.\(mutation\.clientMutationId\)[\s\S]*?submitMindmapSaveMutation\(/,
  )
  assert.match(saveBlock, /payload => batchUpdateMindmapContent\(props\.mindmapId, payload\)/)
  assert.match(saveBlock, /assertMindmapSaveMutationResponse\(mutation, response\.data\)/)
  assert.match(saveBlock, /activeSaveMutation\?\.clientMutationId !== mutation\.clientMutationId/)
  assert.match(
    saveBlock,
    /pendingSave\.value[\s\S]*?\|\| pendingContentOperations\.length > 0[\s\S]*?\|\| pendingClientMutationId/,
  )
  assert.doesNotMatch(saveBlock, /pendingContentOperations\.splice\(0, capturedOperationCount\)/)
  assert.doesNotMatch(saveBlock, /batchUpdateMindmapContent[\s\S]*?clientMutationId: createMutationId\(\)/)
  assert.match(dirtyBlock, /Boolean\(activeSaveMutation\)/)
  assert.match(operationBlock, /activeSaveMutation\?\.document/)
  assert.match(operationBlock, /snapshotMindmapDocumentMeta\(activeSaveMutation\.document\)/)
})

test('conflict recovery protects the rejected batch and never reports it as saved', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const recoveryBlock = source.match(
    /async function recoverFromSaveRevisionConflict[\s\S]*?async function saveToBackend/,
  )?.[0] || ''
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?function queueRemoteDocumentReset/)?.[0] || ''
  const manualSaveBlock = source.match(/async function manualSave[\s\S]*?async function recoverSave/)?.[0] || ''

  assert.ok(
    recoveryBlock.indexOf('captureRejectedMindmapMutationSnapshot({')
      < recoveryBlock.indexOf('commitActiveEditorsBeforeTermination()'),
    'the immutable rejected document must be captured before blur/await can expose a remote preview',
  )
  assert.match(
    recoveryBlock,
    /mutation: activeSaveMutation,[\s\S]*?fallbackDocument: localFullData,[\s\S]*?previousSnapshot: recoveryState\.rejectedMutationSnapshot/,
  )
  assert.match(
    recoveryBlock,
    /document: rejectedMutationSnapshot\.document,[\s\S]*?eventKey: `rejected-\$\{mutationKey\}`/,
  )
  assert.match(
    recoveryBlock,
    /currentDraftChangeVersion !== rejectedMutationSnapshot\.contentChangeVersion[\s\S]*?document: localFullData,[\s\S]*?eventKey: `pending-\$\{mutationKey\}-v\$\{currentDraftChangeVersion\}`/,
  )
  assert.match(
    recoveryBlock,
    /createDeferredRecoveryState[\s\S]*?rejectedMutationSnapshot/,
  )
  assert.ok(
    recoveryBlock.indexOf('draftProtection.getChangeVersion() !== protectedDraftChangeVersion')
      < recoveryBlock.indexOf('pendingContentOperations = []'),
    'edits made while IndexedDB is pending must abort recovery before pending operations are cleared',
  )
  assert.match(
    saveBlock,
    /const recovered = await recoverFromSaveRevisionConflict\(error\.data, localData\)[\s\S]*?return false/,
  )
  assert.doesNotMatch(saveBlock, /return recovered/)
  assert.match(manualSaveBlock, /return ok === true && viewSaved === true/)
})

test('text edit exit waits for the complete Enter or Tab command before saving', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const hideBlock = source.match(/function onHideTextEdit[\s\S]*?\n\}/)?.[0] || ''

  assert.match(hideBlock, /clearTimeout\(autoSaveTimer\)/)
  assert.match(hideBlock, /setTimeout\(\(\) => saveToBackend\(\), AUTO_SAVE_DELAY\)/)
  assert.doesNotMatch(hideBlock, /\n\s*saveToBackend\(\)/)
})

test('local detail events remain saveable while a remote render is only waiting to finish', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const detailBlock = source.match(/function onMindmapDataChangeDetail[\s\S]*?\n\}/)?.[0] || ''
  const detailGuardBlock = source.match(/function isContentDetailTrackingSuspended[\s\S]*?\n\}/)?.[0] || ''

  assert.match(detailBlock, /isContentDetailTrackingSuspended\(\)/)
  assert.match(detailBlock, /yjsSync\?\.onDataChangeDetail\(detailList, clientMutationId\)/)
  assert.match(detailBlock, /setTimeout\(\(\) => saveToBackend\(\), AUTO_SAVE_DELAY\)/)
  assert.match(detailGuardBlock, /isMutatingMindmapFromRemote/)
  assert.doesNotMatch(detailGuardBlock, /isApplyingRemote/)
})

test('fully reverted realtime edits still receive an HTTP mutation confirmation', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const recordBlock = source.match(/function recordContentOperations[\s\S]*?\n\}/)?.[0] || ''
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''

  assert.match(recordBlock, /compactMindmapContentOperations\(/)
  assert.match(
    recordBlock,
    /const crossNodeStateChanged = detailListTouchesCrossNodeState\(detailList\)[\s\S]*?crossNodeStateChanged[\s\S]*?extractCrossNodeState\(mindMap\.value\?\.getData\?\.\(true\)\)/,
  )
  assert.doesNotMatch(recordBlock, /COLLABORATION_SYNC_CONFIRM_OPERATION/)
  assert.match(saveBlock, /sealLocalMutation\?\.\(clientMutationId\)/)
  assert.match(
    saveBlock,
    /const semanticOperations = pendingContentOperations\.filter\([\s\S]*?operation\?\.type !== COLLABORATION_SYNC_CONFIRM_OPERATION/,
  )
  assert.match(
    saveBlock,
    /semanticOperations\.length === 0[\s\S]*?yjsUpdateCount > 0[\s\S]*?\? \[\{ type: COLLABORATION_SYNC_CONFIRM_OPERATION \}\][\s\S]*?: semanticOperations/,
  )
  assert.match(saveBlock, /yjsUpdateCount/)
  assert.match(saveBlock, /createMindmapSaveMutation\(\{[\s\S]*?yjsUpdateCount,/)
  assert.match(saveBlock, /getLocalMutationDeliveryMode/)
  assert.match(source, /canSendRealtimeMutation:\s*\(\)\s*=>\s*!activeSaveMutation/)
  assert.match(saveBlock, /baseRevision: mutationBaseRevision/)
  assert.match(saveBlock, /yjsDeliveryMode/)
})

test('save responses use monotonic revision and document-data generation fences', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''
  const metaBlock = source.match(/function onDocumentMetaChange[\s\S]*?\n\}/)?.[0] || ''

  assert.match(source, /let documentDataGeneration = 0/)
  assert.match(source, /let activeSaveDocumentDataGeneration = null/)
  assert.match(
    metaBlock,
    /hasOwnProperty\.call\(normalizedPatch, 'documentData'\)[\s\S]*?documentDataGeneration \+= 1/,
  )
  assert.match(
    saveBlock,
    /const frozenDocumentDataGeneration = documentDataGeneration[\s\S]*?activeSaveDocumentDataGeneration = activeSaveMutation[\s\S]*?frozenDocumentDataGeneration/,
  )
  assert.match(saveBlock, /const responseSuperseded = responseRevision < contentRevision/)
  assert.match(
    source,
    /function advancePendingUnsentMutationBaseRevision[\s\S]*?rebaseUnsentLocalMutation\?\.\([\s\S]*?pendingClientMutationBaseRevision = normalizedRevision/,
  )
  assert.match(
    saveBlock,
    /!responseSuperseded[\s\S]*?!rebasedAcrossRemoteRevision[\s\S]*?response\.data\.concurrentMerge !== true[\s\S]*?!requiresFileMetaReconciliation[\s\S]*?advancePendingUnsentMutationBaseRevision\(responseRevision\)/,
  )
  assert.match(
    saveBlock,
    /if \(!responseSuperseded\) \{[\s\S]*?contentRevision = Math\.max\(contentRevision, responseRevision\)[\s\S]*?documentDataGeneration !== activeSaveDocumentDataGeneration[\s\S]*?documentData\.value = authoritativeResponseDocumentData[\s\S]*?nodeRevisionMap\.clear\(\)[\s\S]*?rebaseMindmapOperationTargetRevisions/,
  )
  assert.match(
    saveBlock,
    /if \([\s\S]*?!responseSuperseded[\s\S]*?!rebasedAcrossRemoteRevision[\s\S]*?!ordinaryAuthoritativeReloadRequired[\s\S]*?\) \{[\s\S]*?markDocumentMetaSaved/,
  )
  assert.match(
    saveBlock,
    /responseSuperseded[\s\S]*?stopCurrentCollaborationSource\(\)[\s\S]*?markAuthoritativeReloadRequired\(\)[\s\S]*?\} else if \(response\.data\.concurrentMerge\)/,
  )
})

test('editor keeps local file metadata intent across a conflicting Yjs preview', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const recordBlock = source.match(/function recordDocumentOperations[\s\S]*?\n\}/)?.[0] || ''
  const currentDocumentBlock = source.match(/function getCurrentDocument[\s\S]*?\n\}/)?.[0] || ''
  const yjsFactoryBlock = source.match(/function createYjsSyncInstance[\s\S]*?\n\}/)?.[0] || ''
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''
  const reloadBlock = source.match(/async function reloadLatestServerDocument[\s\S]*?\n\}/)?.[0] || ''

  assert.match(recordBlock, /captureMindmapFileMetaIntents\(/)
  assert.match(currentDocumentBlock, /applyMindmapFileMetaIntents\(/)
  assert.match(currentDocumentBlock, /getProtectedFileMetaIntents\(\)/)
  assert.match(
    yjsFactoryBlock,
    /onDocumentApplied:[\s\S]*?findConflictingMindmapFileMetaIntents\([\s\S]*?fileMetaReconciliationRequired = true/,
  )
  assert.match(
    yjsFactoryBlock,
    /const effectiveMeta = applyMindmapFileMetaIntents\([\s\S]*?normalizeMindmapDocumentData\(effectiveMeta\.documentData\)/,
  )
  assert.match(
    saveBlock,
    /const mutationDocument = applyMindmapOperationIntents\([\s\S]*?activeSaveMutation = createMindmapSaveMutation\(\{[\s\S]*?document: mutationDocument[\s\S]*?pendingFileMetaIntents = \{\}/,
  )
  assert.match(
    saveBlock,
    /requiresFileMetaReconciliation[\s\S]*?stopCurrentCollaborationSource\(\)[\s\S]*?reconcilingFileMetaIntents = captureMindmapFileMetaIntents\([\s\S]*?raiseAuthoritativeReloadMinimumRevision\(responseRevision\)/,
  )
  assert.match(reloadBlock, /clearFileMetaIntentState\(\)/)
})

test('concurrent merge defers authoritative replacement while newer local edits exist', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''
  const reloadBlock = source.match(/async function reloadLatestServerDocument[\s\S]*?\n\}/)?.[0] || ''
  const startSyncBlock = source.match(/function startYjsSyncIfReady[\s\S]*?\n\}/)?.[0] || ''

  assert.match(
    saveBlock,
    /const hasNewerLocalChanges = \([\s\S]*?pendingContentOperations\.length > 0[\s\S]*?pendingClientMutationId[\s\S]*?draftProtection\.getChangeVersion\(\) !== mutation\.contentChangeVersion[\s\S]*?documentDataGeneration !== activeSaveDocumentDataGeneration[\s\S]*?viewSaveRequested[\s\S]*?viewSaveInProgress[\s\S]*?viewChangeVersion > mutation\.viewChangeVersion/,
  )
  assert.match(saveBlock, /if \(hasNewerLocalChanges \|\| !response\.data\.nodeTree\) \{[\s\S]*?markAuthoritativeReloadRequired\(\)/)
  assert.match(
    saveBlock,
    /response\.data\.concurrentMerge\) \{[\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?const hasNewerLocalChanges[\s\S]*?stopCurrentCollaborationSource\(\)/,
  )
  assert.match(saveBlock, /onYjsReinit\(response\.data\.nodeTree, contentRevision\)/)
  assert.match(startSyncBlock, /authoritativeReloadRequired/)
  assert.match(saveBlock, /authoritativeReloadRequired[\s\S]*?shouldScheduleAuthoritativeReload = true/)
  assert.match(saveBlock, /else if \(shouldScheduleAuthoritativeReload\) \{[\s\S]*?scheduleAuthoritativeReload\(\)/)
  assert.match(
    saveBlock,
    /ordinaryAuthoritativeReloadRequired[\s\S]*?stopCurrentCollaborationSource\(\)[\s\S]*?markAuthoritativeReloadRequired\(\)/,
  )
  assert.match(saveBlock, /applyAuthoritativeMindmapDocument\([\s\S]*?activeMindMap,[\s\S]*?mergedDocument/)
  assert.doesNotMatch(saveBlock, /activeMindMap\.setFullData\(mergedDocument\)/)
  assert.match(
    saveBlock,
    /await ensureMindmapDocumentPlugins\(mergedDocument, activeMindMap\)[\s\S]*?const textProtectionResult = protectActiveTextEditorBeforeRemoteDocumentApply\([\s\S]*?commitActiveEditorsBeforeTermination\(\)[\s\S]*?await nextTick\(\)[\s\S]*?textProtectionResult === 'local-edit-committed'[\s\S]*?documentDataGeneration !== prepareDocumentDataGeneration[\s\S]*?changedDuringPluginPreparation/,
  )
  assert.match(
    reloadBlock,
    /requireClean[\s\S]*?hasUnsavedChanges\(\)[\s\S]*?viewSaveRequested[\s\S]*?viewSaveInProgress[\s\S]*?return false/,
  )
  assert.match(reloadBlock, /viewChangeVersion !== cleanViewChangeVersion/)
  assert.match(reloadBlock, /applyAuthoritativeMindmapDocument\(activeMindMap, serverDocument\)/)
  assert.doesNotMatch(reloadBlock, /activeMindMap\.setFullData\(serverDocument\)/)
})

test('unconfirmed Yjs state reloads the authoritative document after a successful save', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''
  const staleBlock = source.match(/async function handleStaleCollaborationState[\s\S]*?\n\}/)?.[0] || ''

  assert.match(saveBlock, /requiresAuthoritativeReconciliation\?\.\(\)/)
  assert.match(saveBlock, /requiresAuthoritativeReconciliation[\s\S]*?markAuthoritativeReloadRequired\(\)/)
  assert.match(staleBlock, /const saved = await saveToBackend\(\)/)
  assert.match(staleBlock, /if \(!saved \|\| hasUnsavedChanges\(\)\) return/)
  assert.match(staleBlock, /authoritativeReloadRequired[\s\S]*?performAuthoritativeReload\(\)/)
})

test('mindmap batch save has a dedicated weak-network timeout and server idempotency contract', async () => {
  const source = await readFile(apiUrl, 'utf8')
  const batchBlock = source.match(/export function batchUpdateMindmapContent[\s\S]*?\n\}/)?.[0] || ''

  assert.match(source, /const MINDMAP_SAVE_TIMEOUT_MS = 30_000/)
  assert.match(batchBlock, /headers: \{ repeatSubmit: false \}/)
  assert.match(batchBlock, /timeout: MINDMAP_SAVE_TIMEOUT_MS/)
})

test('view changes use a revision-fenced endpoint and never enter drafts or Yjs', async () => {
  const [source, apiSource] = await Promise.all([
    readFile(editorUrl, 'utf8'),
    readFile(apiUrl, 'utf8'),
  ])
  const viewBlock = source.match(/function onBusViewDataChange[\s\S]*?\n\}/)?.[0] || ''
  const scheduleViewBlock = source.match(/function scheduleViewSave[\s\S]*?\n\}/)?.[0] || ''
  const flushViewBlock = source.match(/async function flushPendingViewSave[\s\S]*?\n\}/)?.[0] || ''
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''
  const viewApiBlock = apiSource.match(/export function updateMindmapView[\s\S]*?\n\}/)?.[0] || ''
  const leaveBlock = source.match(/async function flushBeforeLeave[\s\S]*?async function prepareForCloudExit/)?.[0] || ''
  const manualSaveBlock = source.match(/async function manualSave[\s\S]*?async function recoverSave/)?.[0] || ''
  const unmountBlock = source.match(/onBeforeUnmount\(\(\) => \{[\s\S]*?async function initMindMap/)?.[0] || ''
  const onlineBlock = source.match(/function handleNetworkOnline[\s\S]*?function markAuthoritativeReloadRequired/)?.[0] || ''

  assert.match(viewBlock, /scheduleViewSave\(data\)/)
  assert.doesNotMatch(viewBlock, /file\.view\.update/)
  assert.doesNotMatch(viewBlock, /scheduleLocalDraftPersist/)
  assert.doesNotMatch(viewBlock, /scheduleYjsMetaSync/)
  assert.match(scheduleViewBlock, /viewChangeVersion \+= 1/)
  assert.match(scheduleViewBlock, /cloneRequestPayload\(data\)/)
  assert.match(scheduleViewBlock, /authoritativeReloadRequired/)
  assert.match(scheduleViewBlock, /pendingRemoteDocumentReset/)
  assert.doesNotMatch(scheduleViewBlock, /\{ \.\.\.data \}/)
  assert.match(flushViewBlock, /snapshotViewChangeVersion/)
  assert.match(flushViewBlock, /snapshotContentRevision = contentRevision/)
  assert.match(flushViewBlock, /requestGeneration = viewSaveGeneration/)
  assert.match(flushViewBlock, /updateMindmapView\([\s\S]*?snapshotContentRevision/)
  assert.match(flushViewBlock, /savedViewChangeVersion = Math\.max/)
  assert.match(
    flushViewBlock,
    /error\?\.data\?\.currentRevision[\s\S]*?pendingViewData = undefined[\s\S]*?viewSaveRequested = false[\s\S]*?raiseAuthoritativeReloadMinimumRevision[\s\S]*?markAuthoritativeReloadRequired\(\)/,
  )
  assert.match(
    flushViewBlock,
    /rejectedByNewerContentRevision[\s\S]*?scheduleAuthoritativeReload\(\)/,
  )
  assert.match(
    flushViewBlock,
    /componentMounted[\s\S]*?viewSaveRequested[\s\S]*?requestSucceeded \|\| newerViewRequested/,
  )
  assert.doesNotMatch(saveBlock, /savedViewChangeVersion = Math\.max/)
  assert.match(viewApiBlock, /\/mindmap\/file\/.*\/view/)
  assert.match(viewApiBlock, /method: 'patch'/)
  assert.match(viewApiBlock, /data: \{ viewData, expectedContentRevision \}/)
  assert.match(viewApiBlock, /silentError: true/)
  assert.match(leaveBlock, /await flushPendingViewSave\(\)/)
  assert.match(manualSaveBlock, /const viewSaved = await flushPendingViewSave\(\)/)
  assert.match(onlineBlock, /viewSaveRequested[\s\S]*?flushPendingViewSave\(\)/)
  assert.ok(
    unmountBlock.indexOf('flushPendingViewSave()')
      < unmountBlock.indexOf('componentMounted = false'),
  )
})

test('restored drafts freeze their HTTP mutation before Yjs can start', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const initializationBlock = source.match(/async function initMindMap[\s\S]*?async function waitForMindMapContainer/)?.[0] || ''
  const startBlock = source.match(/function startYjsSyncIfReady[\s\S]*?\n\}/)?.[0] || ''
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''

  assert.ok(
    initializationBlock.indexOf('await waitForMindmapInitialRender(mm)')
      < initializationBlock.indexOf('if (restoredLocalDraft) void saveToBackend()'),
  )
  assert.ok(
    initializationBlock.indexOf('if (restoredLocalDraft) void saveToBackend()')
      < initializationBlock.lastIndexOf('startYjsSyncIfReady()'),
  )
  assert.match(startBlock, /restoredLocalDraft/)
  assert.match(startBlock, /!initialRenderReady/)
  assert.match(saveBlock, /clearRestoredDraft\(\)[\s\S]*?startYjsSyncIfReady\(\)/)
})

test('authoritative collaboration reload retries with a bounded visible recovery state', async () => {
  const [source, pageSource, apiSource, requestSource] = await Promise.all([
    readFile(editorUrl, 'utf8'),
    readFile(pageUrl, 'utf8'),
    readFile(apiUrl, 'utf8'),
    readFile(requestUrl, 'utf8'),
  ])
  const nextRetryBlock = source.match(/function scheduleNextAuthoritativeReload[\s\S]*?\n\}/)?.[0] || ''
  const performBlock = source.match(/async function performAuthoritativeReload[\s\S]*?\n\}/)?.[0] || ''
  const cancelBlock = source.match(/function cancelSessionAsyncWork[\s\S]*?\n\}/)?.[0] || ''
  const recoverBlock = source.match(/async function recoverSave[\s\S]*?\n\}/)?.[0] || ''

  assert.match(source, /const AUTHORITATIVE_RELOAD_RETRY_DELAYS = \[2000, 5000, 10000, 30000\]/)
  assert.match(nextRetryBlock, /authoritativeReloadAttempt >= AUTHORITATIVE_RELOAD_RETRY_DELAYS\.length/)
  assert.match(nextRetryBlock, /saveRecoveryKind\.value = 'sync'/)
  assert.match(nextRetryBlock, /setSaveStatus\('error'\)/)
  assert.match(
    performBlock,
    /reloadLatestServerDocument\(\{[\s\S]*?requireClean: true,[\s\S]*?minimumContentRevision: authoritativeReloadMinimumRevision/,
  )
  assert.match(performBlock, /scheduleNextAuthoritativeReload\(\)/)
  assert.match(source, /silentError: requireClean/)
  assert.match(apiSource, /getMindmap\(mindmapId, \{ signal, silentError = false \} = \{\}\)/)
  assert.match(apiSource, /signal,[\s\S]*?silentError,/)
  assert.match(requestSource, /const silentError = res\.config\?\.silentError === true/)
  assert.match(requestSource, /if \(!silentError\) ElNotification\.error/)
  assert.match(requestSource, /error\.config\?\.silentError === true[\s\S]*?response\?\.config\?\.silentError === true/)
  assert.match(requestSource, /responseStatus !== 401 && responseCode !== 401/)
  assert.match(requestSource, /if \(!silentError\) ElMessage\(\{ message: message, type: 'error'/)
  assert.match(cancelBlock, /clearTimeout\(authoritativeReloadTimer\)/)
  assert.match(recoverBlock, /saveRecoveryKind\.value === 'sync'/)
  assert.match(recoverBlock, /return performAuthoritativeReload\(\)/)
  assert.match(pageSource, /class="meta-save-status"[\s\S]*?:class="saveStatus"[\s\S]*?\{\{ saveStatusText \}\}/)
  assert.match(pageSource, /&\.syncing \{[\s\S]*?color: #8f6b20/)
  assert.match(pageSource, /syncing: '正在同步画布'/)
})

test('overlapping stale notifications keep a monotonic authoritative revision floor', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const staleBlock = source.match(
    /async function handleStaleCollaborationState[\s\S]*?\n\}/,
  )?.[0] || ''
  const reloadBlock = source.match(
    /async function reloadLatestServerDocument[\s\S]*?\n\}/,
  )?.[0] || ''
  const resolveBlock = source.match(
    /function resolveAuthoritativeReload[\s\S]*?\n\}/,
  )?.[0] || ''

  assert.match(
    source,
    /function raiseAuthoritativeReloadMinimumRevision[\s\S]*?contentRevision \?\? dataOrRevision\.currentRevision[\s\S]*?Math\.max\([\s\S]*?authoritativeReloadMinimumRevision[\s\S]*?candidate/,
  )
  assert.ok(
    staleBlock.indexOf('raiseAuthoritativeReloadMinimumRevision(data)')
      < staleBlock.indexOf('if (versionChangeTrackingPaused || resolvingStaleState || !mindMap.value) return'),
    'a newer stale event must raise the floor before an in-progress recovery returns',
  )
  assert.match(
    reloadBlock,
    /const isBelowRequiredRevision = \(\) => \([\s\S]*?getAuthoritativeReloadMinimumRevision\([\s\S]*?minimumContentRevision/,
  )
  assert.ok(
    (reloadBlock.match(/isBelowRequiredRevision\(\)/g) || []).length >= 3,
    'the live floor must be checked after GET/plugin preparation, editor commit, and render',
  )
  assert.match(
    resolveBlock,
    /contentRevision < authoritativeReloadMinimumRevision[\s\S]*?setAuthoritativeReloadRequiredState\(true\)[\s\S]*?return false[\s\S]*?authoritativeReloadMinimumRevision = 0/,
  )
})
