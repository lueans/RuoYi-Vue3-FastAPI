import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  assertMindmapSaveMutationResponse,
  createMindmapSaveMutation,
  rebaseMindmapSaveMutation,
  submitMindmapSaveMutation,
} from '../mindmap-save-mutation.js'

const editorUrl = new URL('../../components/MindMap/Edit.vue', import.meta.url)
const apiUrl = new URL('../../api/mindmap/mindmap.js', import.meta.url)
const pageUrl = new URL('../../views/mindmap/edit.vue', import.meta.url)
const requestUrl = new URL('../request.js', import.meta.url)

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
  assert.equal(mutation.document.root.data.text, 'before')
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
  assert.match(saveBlock, /if \(activeSaveMutation\) pendingContentOperations = \[\]/)
  assert.match(saveBlock, /submitMindmapSaveMutation\(/)
  assert.match(saveBlock, /payload => batchUpdateMindmapContent\(props\.mindmapId, payload\)/)
  assert.match(saveBlock, /assertMindmapSaveMutationResponse\(mutation, response\.data\)/)
  assert.match(saveBlock, /activeSaveMutation\?\.clientMutationId !== mutation\.clientMutationId/)
  assert.match(saveBlock, /pendingSave\.value \|\| pendingContentOperations\.length > 0/)
  assert.doesNotMatch(saveBlock, /pendingContentOperations\.splice\(0, capturedOperationCount\)/)
  assert.doesNotMatch(saveBlock, /batchUpdateMindmapContent[\s\S]*?clientMutationId: createMutationId\(\)/)
  assert.match(dirtyBlock, /Boolean\(activeSaveMutation\)/)
  assert.match(operationBlock, /activeSaveMutation\?\.document/)
  assert.match(operationBlock, /snapshotMindmapDocumentMeta\(activeSaveMutation\.document\)/)
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
  assert.match(detailBlock, /yjsSync\?\.onDataChangeDetail\(detailList\)/)
  assert.match(detailBlock, /setTimeout\(\(\) => saveToBackend\(\), AUTO_SAVE_DELAY\)/)
  assert.match(detailGuardBlock, /isMutatingMindmapFromRemote/)
  assert.doesNotMatch(detailGuardBlock, /isApplyingRemote/)
})

test('concurrent merge defers authoritative replacement while newer local edits exist', async () => {
  const source = await readFile(editorUrl, 'utf8')
  const saveBlock = source.match(/async function saveToBackend[\s\S]*?\n\}/)?.[0] || ''
  const reloadBlock = source.match(/async function reloadLatestServerDocument[\s\S]*?\n\}/)?.[0] || ''

  assert.match(saveBlock, /const hasNewerLocalChanges = \([\s\S]*?pendingContentOperations\.length > 0[\s\S]*?viewChangeVersion > mutation\.viewChangeVersion/)
  assert.match(saveBlock, /if \(hasNewerLocalChanges\) \{[\s\S]*?markAuthoritativeReloadRequired\(\)/)
  assert.match(saveBlock, /authoritativeReloadRequired[\s\S]*?shouldScheduleAuthoritativeReload = true/)
  assert.match(saveBlock, /else if \(shouldScheduleAuthoritativeReload\) \{[\s\S]*?scheduleAuthoritativeReload\(\)/)
  assert.match(saveBlock, /applyMindmapDocumentPreservingRuntimeState\([\s\S]*?activeMindMap,[\s\S]*?mergedDocument/)
  assert.doesNotMatch(saveBlock, /activeMindMap\.setFullData\(mergedDocument\)/)
  assert.match(reloadBlock, /if \(requireClean && hasUnsavedChanges\(\)\) return false/)
  assert.match(reloadBlock, /viewChangeVersion !== cleanViewChangeVersion/)
  assert.match(reloadBlock, /applyMindmapDocumentPreservingRuntimeState\(activeMindMap, serverDocument\)/)
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
  assert.match(performBlock, /reloadLatestServerDocument\(\{ requireClean: true \}\)/)
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
  assert.match(pageSource, /\['saving', 'retrying', 'syncing'\]/)
  assert.match(pageSource, /syncing: '正在同步画布'/)
})
