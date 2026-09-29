import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, babelParse, compileTemplate } from '@vue/compiler-sfc'
import { agentToolNodeTargets, resolveAgentToolDocumentScope, focusMindmapToolNode } from '../mindmap-agent-node-links.js'
import { projectRuntimeEvents } from '../mindmap-ai-runtime.js'

const entry = (name, output, extra = {}) => ({ kind: 'tool', key: 'tool:1', name, status: 'completed', output: JSON.stringify(output), ...extra })
const cloud = { id: 'job-1', sourceType: 'cloud_document', sourceMindmapId: 130, status: 'running' }
const context = { ownerUserId: '1', currentJob: cloud, editorContext: { mindmapId: 130, documentId: 'cloud:130' } }

test('links use explicit successful output IDs, never input or display-name suffixes', () => {
  for (const prefix of ['', 'mcp__mindmap__', 'mindmap/']) {
    assert.deepEqual(agentToolNodeTargets(entry(`${prefix}add_nodes`, { created: [{ nodeUid: 'a' }, { nodeUid: 'b' }] })), ['a', 'b'])
  }
  for (const name of ['evil/add_nodes', 'mcp__other__add_nodes', 'not_mindmap_add_nodes', 'mindmap_add_nodes', 'constructor', 'remove_nodes', 'read_projection']) {
    assert.deepEqual(agentToolNodeTargets(entry(name, { created: [{ nodeUid: 'a' }], nodeUids: ['a'] })), [])
  }
  assert.deepEqual(agentToolNodeTargets(entry('update_nodes', { updated: 3 }, { input: '{"updates":[{"nodeUid":"guessed"}]}' })), [])
  for (const status of ['running', 'failed', 'cancelled', 'unknown']) assert.deepEqual(agentToolNodeTargets(entry('update_nodes', { nodeUids: ['a'] }, { status })), [])
})

test('bounded receipt targets preserve unique UID identity and reject invalid detail', () => {
  assert.deepEqual(agentToolNodeTargets(entry('update_nodes', { nodeUids: ['a', 'a', '', 1, true, null, ' b', 'b\n', 'x'.repeat(65), 'valid中文'] })), ['a', 'valid中文'])
  const ids = Array.from({ length: 50 }, (_, i) => `node-${i}`)
  assert.deepEqual(agentToolNodeTargets(entry('move_nodes', { nodeUids: ids, moved: 50 })), ids.slice(0, 12))
  for (const output of ['null', '[]', '{', ' '.repeat(6001)]) assert.deepEqual(agentToolNodeTargets(entry('move_nodes', {}, { output })), [])
  for (const name of ['edit_node_text', 'edit_node_tags']) assert.deepEqual(agentToolNodeTargets(entry(name, { nodeUids: ['child'] })), ['child'])
  assert.deepEqual(agentToolNodeTargets(entry('start_document', { rootUid: 'root' })), ['root'])
  assert.deepEqual(agentToolNodeTargets(entry('add_comment', { nodeUid: 'a', accepted: true })), ['a'])
  assert.deepEqual(agentToolNodeTargets(entry('add_comment', { nodeUid: 'a', accepted: false })), [])
})

test('cloud navigation requires exact current document identity; historical cloud receipts remain current-node links', () => {
  assert.equal(resolveAgentToolDocumentScope(cloud, context).documentId, 'cloud:130')
  assert.equal(resolveAgentToolDocumentScope({ ...cloud, id: 'history', status: 'applied' }, context).reason, '')
  for (const change of [{ sourceMindmapId: 131 }, { sourceMindmapId: 'bad' }, { sourceType: 'uploaded_artifact' }, { sourceType: 'none' }]) {
    assert.ok(resolveAgentToolDocumentScope({ ...cloud, ...change }, context).reason)
  }
  for (const patch of [{ ownerUserId: '' }, { editorContext: { mindmapId: 130, documentId: 'cloud:131' } }]) assert.ok(resolveAgentToolDocumentScope(cloud, { ...context, ...patch }).reason)
  for (const status of ['rejected', 'undone', 'expired']) assert.ok(resolveAgentToolDocumentScope({ ...cloud, status }, context).reason)
})

test('local snapshots require the bound current job and stable editor/source identity', () => {
  const candidate = { id: 'local-job', sourceType: 'local_snapshot' }
  const local = { ownerUserId: '1', currentJob: candidate, editorContext: { documentId: 'local-1' }, sourceContext: { documentId: 'local-1' } }
  assert.equal(resolveAgentToolDocumentScope(candidate, local).documentId, 'local-1')
  for (const patch of [{ currentJob: { id: 'another' } }, { sourceContext: null }, { editorContext: { documentId: 'local-2' } }, { sourceContext: { documentId: 'local-1', mindmapId: 130 } }]) {
    assert.ok(resolveAgentToolDocumentScope(candidate, { ...local, ...patch }).reason)
  }
})

function focusHarness() {
  const calls = []
  const node = { left: 20, top: 30, width: 100, height: 35, group: { node: { isConnected: true }, visible: () => true }, getData: () => '<p>当前节点</p>' }
  const renderer = { findNodeByUid: id => id === 'child' ? node : null, moveNodeToCenter: () => {} }
  const input = { request: { jobId: 'job-1', documentId: 'cloud:130', ownerUserId: '1', nodeUid: 'child' }, ownerUserId: '1', documentId: 'cloud:130', mindMap: { renderer, width: 800, height: 600 }, navigate: target => calls.push(target) }
  return { node, renderer, input, calls, focus: () => focusMindmapToolNode(input) }
}

test('focus is a synchronous camera-only operation using the current node label', () => {
  const h = focusHarness()
  assert.deepEqual(h.focus(), { ok: true, message: '已定位当前节点：当前节点' })
  assert.deepEqual(h.calls, [h.node])
})

test('focus rejects wrong owner/document/preview and never accesses a stale renderer', () => {
  for (const patch of [{ ownerUserId: '2' }, { ownerUserId: '' }, { documentId: 'cloud:131' }, { previewJobId: 'another' }, { blocked: true }]) {
    const h = focusHarness()
    Object.assign(h.input, patch)
    h.renderer.findNodeByUid = () => { throw new Error('must not read renderer') }
    assert.equal(h.focus().ok, false)
    assert.equal(h.calls.length, 0)
  }
})

test('busy, detached, hidden, deleted and not-laid-out nodes do not expand or move', () => {
  for (const mutate of [h => { h.renderer.isRendering = true }, h => { h.renderer.renderTimer = 3 }, h => { h.node.group.node.isConnected = false }, h => { h.node.group.visible = () => false }, h => { h.node.isHide = true }, h => { h.input.request.nodeUid = 'deleted' }, h => { h.node.left = NaN }, h => { h.node.width = 0 }, h => { h.input.mindMap.width = 0 }, h => { h.input.mindMap.width = Infinity }]) {
    const h = focusHarness()
    mutate(h)
    assert.equal(h.focus().ok, false)
    assert.equal(h.calls.length, 0)
  }
})

function declarations(path, names, scope) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const script = parse(source).descriptor.scriptSetup.content
  const nodes = babelParse(script, { sourceType: 'module' }).program.body.filter(node => names.includes(node.id?.name))
  assert.equal(nodes.length, names.length)
  return new Function('scope', `with(scope) { ${nodes.map(node => script.slice(node.start, node.end)).join('\n')}; return {${names.join(',')}} }`)(scope)
}

test('actual editor handler suppresses synchronous view saves, preserves zoom, and restores tracking on throw', () => {
  const h = focusHarness()
  const saved = []
  let receipt
  const scope = {
    mindMap: { value: h.input.mindMap }, props: { mindmapId: 130 }, actions: { getData: () => { throw new Error('cloud must not read local storage') } },
    currentLocalAiOwnerUserId: () => '1', focusMindmapToolNode,
    aiDraftPreviewState: null, componentMounted: true, initialRenderReady: true, terminalState: '', terminatingSession: false,
    sessionController: null, localAiJournalRecoveryPromise: null, aiCanvasPreparation: null, applyingServerTree: false,
    versionChangeTrackingPaused: false, hasActiveEditingTransition: () => false, authoritativeReloadRequired: false, authoritativeReloadInProgress: false,
    aiToolNodeNavigationActive: false, isCurrentMindmapEventSource: () => true, localAiUndoInProgress: false, isReadonly: { value: false },
    isChangeTrackingSuspended: () => false, scheduleViewSave: value => saved.push(value),
  }
  const api = declarations('../../components/MindMap/Edit.vue', ['onRequestAiToolNodeFocus', 'onBusViewDataChange'], scope)
  h.renderer.moveNodeToCenter = (node, resetZoom) => {
    assert.equal(node, h.node)
    assert.equal(resetZoom, false)
    api.onBusViewDataChange({ x: 20 }, h.input.mindMap)
  }
  const request = { ...h.input.request, editor: h.input.mindMap }
  api.onRequestAiToolNodeFocus(request, { resolve: value => { receipt = value } })
  assert.equal(receipt.ok, true)
  assert.deepEqual(saved, [])
  assert.equal(scope.aiToolNodeNavigationActive, false)
  api.onBusViewDataChange({ x: 30 }, h.input.mindMap)
  assert.deepEqual(saved, [{ x: 30 }], 'ordinary user panning still saves')
  h.renderer.moveNodeToCenter = () => { throw new Error('renderer failed') }
  api.onRequestAiToolNodeFocus(request, { resolve: value => { receipt = value } })
  assert.equal(receipt.ok, false)
  assert.equal(scope.aiToolNodeNavigationActive, false)
  receipt = null
  api.onRequestAiToolNodeFocus({ ...request, editor: {} }, { resolve: value => { receipt = value } })
  assert.equal(receipt, null, 'other editor instances cannot answer')
  for (const state of ['terminalState', 'terminatingSession', 'authoritativeReloadRequired', 'applyingServerTree', 'versionChangeTrackingPaused']) {
    const prior = scope[state]
    scope[state] = true
    api.onRequestAiToolNodeFocus(request, { resolve: value => { receipt = value } })
    assert.match(receipt.message, /尚未就绪/)
    scope[state] = prior
  }
  let localReads = 0
  scope.props.mindmapId = null
  scope.actions.getData = () => { localReads++; return { documentId: 'local-1' } }
  h.renderer.moveNodeToCenter = () => api.onBusViewDataChange({ x: 50 }, h.input.mindMap)
  api.onRequestAiToolNodeFocus({ ...request, documentId: 'local-1' }, { resolve: value => { receipt = value } })
  assert.equal(receipt.ok, true)
  assert.equal(localReads, 1)
  assert.deepEqual(saved, [{ x: 30 }], 'local navigation does not persist a workspace either')
  api.onRequestAiToolNodeFocus({ ...request, documentId: 'old-local' }, { resolve: value => { receipt = value } })
  assert.equal(receipt.ok, false)
})

test('actual chat callback rechecks current receipts, document, owner and lifecycle at click time', () => {
  const output = { created: [{ nodeUid: 'child' }] }
  const event = { key: 'tool:1', eventType: 'tool_completed', payload: { callId: 't', toolName: 'add_nodes', toolOutput: JSON.stringify(output) } }
  const turn = { job: cloud, events: [event] }
  const calls = []
  let owner = '1'
  const scope = {
    currentAiOwnerUserId: () => owner, restoreGeneration: 1, job: { value: cloud }, editorContext: { value: context.editorContext }, sourceContext: { value: null },
    componentAlive: true, visible: { value: true }, actionBusy: { value: false }, restoringJob: { value: false },
    conversationTurns: { value: [turn] }, store: { mindMap: {} }, resolveAgentToolDocumentScope, agentToolNodeTargets, projectRuntimeEvents,
    bus: { emit(name, payload, request) { calls.push([name, payload]); request.resolve({ ok: true, message: 'located' }) } },
  }
  const api = declarations('../../components/MindMap/MindmapAiDialog.vue', ['toolNodeNavigation'], scope)
  const navigation = api.toolNodeNavigation(turn)
  assert.equal(navigation.reason, '')
  assert.equal(navigation.locate(entry('add_nodes', output), 'child').ok, true)
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'requestAiToolNodeFocus')
  assert.equal(calls[0][1].editor, scope.store.mindMap)
  assert.equal(navigation.locate(entry('add_nodes', output), 'guessed').ok, false)
  turn.events = []
  assert.equal(navigation.locate(entry('add_nodes', output), 'child').ok, false)
  turn.events = [event]
  scope.editorContext.value = { mindmapId: 131, documentId: 'cloud:131' }
  assert.equal(navigation.locate(entry('add_nodes', output), 'child').ok, false)
  scope.editorContext.value = context.editorContext
  owner = '2'
  assert.equal(navigation.locate(entry('add_nodes', output), 'child').ok, false)
  owner = '1'
  scope.restoreGeneration++
  assert.equal(navigation.locate(entry('add_nodes', output), 'child').ok, false)
  assert.equal(calls.length, 1)
})

test('node navigation reaches recursive real Vue rows and controls are outside summary', () => {
  for (const name of ['MindmapAgentTrace', 'MindmapAgentTraceRows', 'MindmapAgentToolRow']) {
    const filename = `../../components/MindMap/${name}.vue`
    const source = readFileSync(new URL(filename, import.meta.url), 'utf8')
    const descriptor = parse(source).descriptor
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename, id: 'node-links' }).errors, [])
    if (name !== 'MindmapAgentToolRow') assert.match(descriptor.template.content, /:node-navigation="nodeNavigation"/)
    else {
      assert.match(source, /aria-live="polite"/)
      assert.ok(source.indexOf('class="toolNodes"') > source.indexOf('</template>'))
      assert.match(source, /nodeTargets\.value\.includes\(nodeUid\)/)
    }
  }
  const editor = readFileSync(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8')
  assert.match(editor, /bus\.on\('requestAiToolNodeFocus', onRequestAiToolNodeFocus\)/)
  assert.match(editor, /bus\.off\('requestAiToolNodeFocus', onRequestAiToolNodeFocus\)/)
})
