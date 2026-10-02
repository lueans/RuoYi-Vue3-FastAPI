import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { computed, reactive, ref } from 'vue'
import { installComposerAttachmentHarness } from './mindmap-composer-attachment-harness.mjs'
import { fingerprintMindmapAiRequest, resolveMindmapAiRequestAttempt, mergeMindmapAiJobSnapshot, mergeMindmapAiJobEventSnapshot } from '../mindmap-ai-stream.js'
import { buildMindmapAiConversationTurns, resolveMindmapAiSessionTitle } from '../mindmap-ai-conversation.js'

const script = parse(readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')).descriptor.scriptSetup.content
const nodes = babelParse(script, { sourceType: 'module' }).program.body
function compile(names, scope) {
  installComposerAttachmentHarness(scope)
  const declarations = nodes.filter(node => names.includes(node.id?.name))
  assert.equal(declarations.length, names.length)
  return new Function('scope', `with (scope) { ${declarations.map(node => script.slice(node.start, node.end)).join('\n')}; return { ${names.join(', ')} }; }`)(scope)
}
const file = (id = 'original', text = 'PRIVATE_ATTACHMENT_TEXT') => ({ id, name: `${id}.txt`, size: 64, mediaType: 'text/plain', text, status: 'ready' })
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('capture freezes attachments by value and refuses pending, errored or invalid content', () => {
  const s = installComposerAttachmentHarness({ composerAttachments: ref([file()]) })
  const captured = s.captureComposerAttachments()
  s.composerAttachments.value[0].text = 'NEWER_CONTENT'
  s.composerAttachments.value.push(file('later'))
  assert.equal(captured[0].text, 'PRIVATE_ATTACHMENT_TEXT')
  assert.equal(captured.length, 1)
  assert.ok(!Object.hasOwn(captured[0], 'status'))
  for (const status of ['reading', 'error']) {
    s.composerAttachments.value = [{ ...file(), status }]
    assert.throws(() => s.captureComposerAttachments(), /等待附件读取完成|移除读取失败/)
  }
  s.composerAttachments.value = [file('empty', '')]
  assert.throws(() => s.captureComposerAttachments(), /未读取到可用文字/)
})

test('empty attachment capture preserves legacy request fingerprints and a removed reading pill cannot enable sending', () => {
  const s = installComposerAttachmentHarness({})
  assert.equal(s.captureComposerAttachments(), undefined)
  assert.equal(JSON.stringify({ prompt: 'legacy', attachments: s.captureComposerAttachments() }), '{"prompt":"legacy"}')
  s.attachmentReading.value = true
  assert.throws(() => s.captureComposerAttachments(), /等待附件读取完成/)
})

test('accepted attachment consumption removes only the captured IDs, leaving later uploads intact', () => {
  const s = installComposerAttachmentHarness({ composerAttachments: ref([file(), file('later')]) })
  s.consumeComposerAttachments([file()])
  assert.deepEqual(s.composerAttachments.value.map(item => item.id), ['later'])
  s.consumeComposerAttachments(undefined)
  assert.deepEqual(s.composerAttachments.value.map(item => item.id), ['later'])
})

for (const type of ['create', 'followup', 'retry', 'queue']) {
  test(`${type} durable metadata excludes attachment bodies but retains exact in-memory replay and key`, async () => {
    let persisted = {}, serializations = [], count = 0
    const s = {
      currentAiOwnerUserId: () => 'owner', composerDraftPersistence: { capture: () => ({ id: 'draft', text: '公开提示词' }) },
      fingerprintMindmapAiRequest, resolveMindmapAiRequestAttempt,
      hashAttemptFingerprint: async value => createHash('sha256').update(value).digest('hex'),
      readPersistedAttempts: () => structuredClone(persisted),
      writePersistedAttempts: value => { serializations.push(JSON.stringify(value)); persisted = structuredClone(value); return true },
      cloneRuntimeValue: structuredClone,
    }
    const api = compile(['resolveDurableAttempt', 'clearDurableAttempt'], s)
    s.composerAttachments.value = [{ ...file(), draftRevision: 'original-draft-revision' }]
    const payload = { prompt: '公开提示词', attachments: s.captureComposerAttachments(), agentKey: 'claude' }
    const wrapped = type === 'create' ? payload : { parentJobId: 'parent', requestPayload: payload }
    const options = { createKey: () => `key-${++count}`, metadata: { requestPayload: payload } }
    const attempt = await api.resolveDurableAttempt(type, null, wrapped, options)
    assert.ok(serializations.every(value => !value.includes('PRIVATE_ATTACHMENT_TEXT')))
    assert.equal(persisted[type].attachmentsOmitted, true)
    assert.deepEqual(persisted[type].attachmentIds, ['original'])
    assert.ok(!Object.hasOwn(persisted[type].requestPayload.attachments[0], 'text'))
    assert.deepEqual(persisted[type].requestPayload.attachments[0].parsing, { status: 'parsed', characterCount: 23 })
    assert.equal(persisted[type].requestPayload.attachments[0].draftRevision, 'original-draft-revision')
    assert.doesNotMatch(JSON.stringify(payload), /draftRevision|original-draft-revision/)
    assert.equal(s.replayableRequestPayload(persisted[type]).attachments[0].text, 'PRIVATE_ATTACHMENT_TEXT')
    payload.attachments[0].text = 'subsequent mutation'
    assert.equal(s.replayableRequestPayload(persisted[type]).attachments[0].text, 'PRIVATE_ATTACHMENT_TEXT')
    s.composerAttachments.value = [{ ...file(), draftRevision: 'reselected-draft-revision' }]
    const retryPayload = { ...payload, attachments: s.captureComposerAttachments() }
    const reused = await api.resolveDurableAttempt(type, null, type === 'create' ? retryPayload : { parentJobId: 'parent', requestPayload: retryPayload }, { ...options, metadata: { requestPayload: retryPayload } })
    assert.equal(reused.key, attempt.key)
    assert.equal(persisted[type].requestPayload.attachments[0].draftRevision, 'original-draft-revision', 'a repeated idempotent send retains its original local attachment receipt')
    s.consumeComposerAttachments(persisted[type].requestPayload.attachments)
    assert.equal(s.composerAttachments.value[0].draftRevision, 'reselected-draft-revision', 'reconciliation cannot consume a newer identical upload')
    api.clearDurableAttempt(type, 'another-key')
    assert.equal(s.privateAttachmentRequests.size, 1)
    api.clearDurableAttempt(type, attempt.key)
    assert.equal(s.privateAttachmentRequests.size, 0)
    assert.deepEqual(persisted, {})
  })
}

for (const method of ['replayFollowupAttempt', 'replayRetryAttempt']) {
  test(`${method} never sends metadata-only attachments after a page reload`, async () => {
    const requests = []
    const notFound = Object.assign(new Error('not found'), { status: 404 })
    const s = {
      reconcileMindmapAiJob: async key => { requests.push(['get', key]); throw notFound },
      isHttpNotFound: error => error.status === 404,
      continueMindmapAiJob: async () => { requests.push(['post']); assert.fail('must not send missing attachment text') },
      retryMindmapAiJob: async () => { requests.push(['post']); assert.fail('must not send missing attachment text') },
      assertFollowupAttemptResult: value => value, assertRetryAttemptResult: value => value,
    }
    const api = compile([method], s)
    const attempt = { key: 'original-key', parentJobId: 'parent', retryOfJobId: 'parent', attachmentsOmitted: true,
      requestPayload: { prompt: '要求', attachments: [{ id: 'original', name: 'original.txt', size: 64 }] } }
    await assert.rejects(api[method](attempt, 'session'))
    assert.deepEqual(requests, [['get', 'original-key']])
    assert.equal(attempt.key, 'original-key')
  })

  test(`${method} can recover the server-accepted task without re-uploading private text`, async () => {
    const s = {
      reconcileMindmapAiJob: async () => ({ data: { id: 'accepted' } }),
      isHttpNotFound: () => false,
      continueMindmapAiJob: assert.fail, retryMindmapAiJob: assert.fail,
      assertFollowupAttemptResult: value => value, assertRetryAttemptResult: value => value,
    }
    const api = compile([method], s)
    const result = await api[method]({ key: 'key', parentJobId: 'parent', retryOfJobId: 'parent', attachmentsOmitted: true, requestPayload: { prompt: '要求' } }, 'session')
    assert.equal(result.id, 'accepted')
  })
}

function readerHarness(read) {
  let counter = 0
  const s = { composerEditable: ref(true), createMindmapAiIdempotencyKey: () => `reading-${++counter}`, readMindmapAiAttachment: read }
  const api = compile(['onAttachmentFilesChange', 'removeComposerAttachment'], s)
  return { s, ...api }
}

test('removing and reselecting the same hashed file creates a new local revision that an earlier send cannot consume', async () => {
  const h = readerHarness(async () => file('same-hash'))
  const event = () => ({ target: { files: [{ name: 'same-hash.txt', size: 64 }] } })
  await h.onAttachmentFilesChange(event())
  const original = h.s.captureComposerAttachments()
  assert.equal(original[0].draftRevision, 'reading-1')
  assert.equal(Object.getOwnPropertyDescriptor(original[0], 'draftRevision').enumerable, false)
  assert.ok(!Object.keys(original[0]).includes('draftRevision'))
  assert.doesNotMatch(JSON.stringify(original), /draftRevision|reading-1/)
  h.removeComposerAttachment('same-hash')
  await h.onAttachmentFilesChange(event())
  const reselected = h.s.captureComposerAttachments()
  assert.equal(reselected[0].id, original[0].id)
  assert.equal(reselected[0].draftRevision, 'reading-2')
  assert.equal(fingerprintMindmapAiRequest({ attachments: original }), fingerprintMindmapAiRequest({ attachments: reselected }), 'local revisions never change the server idempotency identity')
  h.s.consumeComposerAttachments(original)
  assert.equal(h.s.composerAttachments.value[0].draftRevision, 'reading-2')
  h.s.consumeComposerAttachments(reselected)
  assert.deepEqual(h.s.composerAttachments.value, [])
})

test('metadata-only recovery with no original revision never removes a newly selected identical file', () => {
  const s = installComposerAttachmentHarness({ composerAttachments: ref([{ ...file(), draftRevision: 'fresh-upload' }]) })
  s.consumeComposerAttachments([{ id: 'original', name: 'original.txt' }])
  assert.equal(s.composerAttachments.value[0].draftRevision, 'fresh-upload')
})

test('removing a reading file prevents its late parser result from reappearing', async () => {
  const gate = deferred(), h = readerHarness(() => gate.promise)
  const event = { target: { files: [{ name: 'original.txt', size: 64 }], value: 'chosen' } }
  const reading = h.onAttachmentFilesChange(event)
  assert.equal(event.target.value, '')
  assert.equal(h.s.composerAttachments.value[0].status, 'reading')
  h.removeComposerAttachment('reading-1')
  gate.resolve(file())
  await reading
  assert.deepEqual(h.s.composerAttachments.value, [])
})

test('switching conversation invalidates in-flight file reads and remaining batch files', async () => {
  const gate = deferred(), read = []
  const h = readerHarness(input => { read.push(input.name); return gate.promise })
  const reading = h.onAttachmentFilesChange({ target: { files: [{ name: 'one.txt', size: 64 }, { name: 'two.txt', size: 64 }] } })
  h.s.clearComposerAttachments()
  gate.resolve(file())
  await reading
  assert.deepEqual(h.s.composerAttachments.value, [])
  assert.deepEqual(read, ['one.txt'])
  assert.equal(h.s.attachmentNotice.value, '')
})

test('duplicate uploads are not repeated and parser errors remain removable with visible feedback', async () => {
  const h = readerHarness(async input => {
    if (input.name === 'broken.txt') throw new Error('附件解析失败')
    return file()
  })
  h.s.composerAttachments.value = [file()]
  await h.onAttachmentFilesChange({ target: { files: [{ name: 'original.txt', size: 64 }] } })
  assert.equal(h.s.composerAttachments.value.length, 1)
  assert.match(h.s.attachmentNotice.value, /不重复添加/)
  await h.onAttachmentFilesChange({ target: { files: [{ name: 'broken.txt', size: 64 }] } })
  assert.equal(h.s.composerAttachments.value[1].status, 'error')
  assert.match(h.s.attachmentNotice.value, /附件解析失败/)
  assert.throws(() => h.s.captureComposerAttachments())
  h.removeComposerAttachment('reading-2')
  assert.equal(h.s.captureComposerAttachments().length, 1)
})

test('selection above five attachments is rejected before any parser starts', async () => {
  const h = readerHarness(assert.fail)
  h.s.composerAttachments.value = [file()]
  await h.onAttachmentFilesChange({ target: { files: Array.from({ length: 5 }, (_, index) => ({ name: `${index}.txt`, size: 64 })) } })
  assert.equal(h.s.composerAttachments.value.length, 1)
  assert.match(h.s.attachmentNotice.value, /最多添加 5 个/)
})

test('removing the current reading pill cannot open a second concurrent attachment batch', async () => {
  const gate = deferred(), names = []
  const h = readerHarness(input => { names.push(input.name); return names.length === 1 ? gate.promise : Promise.resolve(file(input.name)) })
  const reading = h.onAttachmentFilesChange({ target: { files: [{ name: 'first.txt', size: 64 }, { name: 'second.txt', size: 64 }] } })
  h.removeComposerAttachment('reading-1')
  assert.equal(h.s.composerAttachments.value.length, 0)
  assert.equal(h.s.attachmentReading.value, true)
  await h.onAttachmentFilesChange({ target: { files: [{ name: 'other-batch.txt', size: 64 }] } })
  gate.resolve(file('first'))
  await reading
  assert.deepEqual(names, ['first.txt', 'second.txt'])
  assert.equal(h.s.attachmentReading.value, false)
  assert.equal(h.s.composerAttachments.value.length, 1)
})

test('reselection reconstructs the exact original attachment order and does not silently drop missing files', () => {
  const s = installComposerAttachmentHarness({ composerAttachments: ref([file('second'), file('first'), file('newer')]) })
  const attempt = { key: 'key', attachmentsOmitted: true, attachmentIds: ['first', 'second'], requestPayload: { prompt: 'original prompt' } }
  const replay = s.replayableRequestPayload(attempt)
  assert.equal(replay.prompt, 'original prompt')
  assert.deepEqual(replay.attachments.map(item => item.id), ['first', 'second'])
  assert.deepEqual(replay.attachments.map(item => item.text), ['PRIVATE_ATTACHMENT_TEXT', 'PRIVATE_ATTACHMENT_TEXT'])
  assert.ok(replay.attachments.every(item => !Object.hasOwn(item, 'status')))
  s.composerAttachments.value = [file('first')]
  assert.equal(s.replayableRequestPayload(attempt), null)
  s.composerAttachments.value.push({ ...file('second'), status: 'reading' })
  assert.equal(s.replayableRequestPayload(attempt), null)
})

test('historical user turns store attachment metadata without including the private file body', () => {
  const s = { sessionTurns: ref([]), cloneRuntimeValue: structuredClone }
  const { upsertSessionTurn } = compile(['upsertSessionTurn'], s)
  upsertSessionTurn({ id: 'job', turnIndex: 1 }, '要求', [file()])
  assert.doesNotMatch(JSON.stringify(s.sessionTurns.value), /PRIVATE_ATTACHMENT_TEXT/)
  assert.equal(s.sessionTurns.value[0].userMessage.attachments[0].name, 'original.txt')
  assert.deepEqual(s.sessionTurns.value[0].userMessage.attachments[0].parsing, { status: 'parsed', characterCount: 23 })
  upsertSessionTurn({ id: 'job', turnIndex: 1, status: 'completed' }, '')
  assert.equal(s.sessionTurns.value[0].userMessage.attachments[0].name, 'original.txt', 'later job status hydration retains file metadata')
  assert.deepEqual(s.sessionTurns.value[0].userMessage.attachments[0].parsing, { status: 'parsed', characterCount: 23 })
})

test('submitted user context and attachment metadata are immutable snapshots across later drafts, status refreshes and turns', () => {
  const s = { sessionTurns: ref([]), cloneRuntimeValue: structuredClone }
  const { upsertSessionTurn } = compile(['upsertSessionTurn'], s)
  const attachment = file()
  const configuration = { sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'alpha', label: '最初的节点' }] }
  const originalContext = structuredClone(configuration)
  upsertSessionTurn({ id: 'job1', turnIndex: 1, createdTime: '2026-09-30T16:20:05' }, '最初的要求', [attachment], configuration)
  configuration.contextNodes[0].label = '后来改名'
  configuration.contextNodes.push({ uid: 'beta', label: '后来选中' })
  configuration.scopeType = 'selectedNodes'
  attachment.name = '后来改名.txt'
  attachment.text = '后来修改的私密内容'
  upsertSessionTurn({ id: 'job2', turnIndex: 2 }, '下一轮要求', [attachment], configuration)
  upsertSessionTurn({ id: 'job1', turnIndex: 1, status: 'completed_direct' }, '', undefined, configuration)
  const first = s.sessionTurns.value[0]
  assert.deepEqual(first.userMessage.context, originalContext)
  assert.equal(first.userMessage.attachments[0].name, 'original.txt')
  assert.deepEqual(first.userMessage.attachments[0].parsing, { status: 'parsed', characterCount: 23 }, 'later attachment edits cannot rewrite the earlier parsing receipt')
  assert.equal(first.userMessage.createdTime, '2026-09-30T16:20:05')
  assert.equal(first.userMessage.content, '最初的要求')
  assert.equal(first.job.status, 'completed_direct')
  assert.equal(s.sessionTurns.value[1].userMessage.context.contextNodes.length, 2)
  assert.doesNotMatch(JSON.stringify(s.sessionTurns.value), /PRIVATE_ATTACHMENT_TEXT|后来修改的私密内容/)
})

test('an explicitly unknown historical context is never inferred from the current composer selection', () => {
  const s = { sessionTurns: ref([{ job: { id: 'old', turnIndex: 1 }, userMessage: { content: '历史要求', context: null } }]), cloneRuntimeValue: structuredClone }
  const { upsertSessionTurn } = compile(['upsertSessionTurn'], s)
  upsertSessionTurn({ id: 'old', turnIndex: 1, status: 'completed_direct' }, '', undefined,
    { sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'new', label: '现在选择的节点' }] })
  assert.equal(s.sessionTurns.value[0].userMessage.context, null)
})

test('production timeline restoration preserves historical context metadata independently of the current draft', async () => {
  const historicalContext = { sourceMode: 'current', scopeType: 'selectedNodes', contextNodes: [{ uid: 'a', label: '模块甲' }, { uid: 'b', label: '模块乙' }] }
  const serverTurns = [
    { job: { id: 'old', sessionId: 'session', turnIndex: 1, status: 'completed_direct' }, userMessage: { content: '原范围', createdTime: '2026-09-30T16:20:05', context: historicalContext, attachments: [{ id: 'file', name: '需求.pdf', size: 256, mediaType: 'application/pdf' }] }, events: [] },
    { job: { id: 'current', sessionId: 'session', turnIndex: 2, status: 'running' }, userMessage: { content: '整个脑图', context: { sourceMode: 'current', scopeType: 'document', contextNodes: [] } }, events: [] },
    { job: { id: 'legacy', sessionId: 'session', turnIndex: 0, status: 'completed_direct' }, userMessage: { content: '未知历史范围', context: null }, events: [] },
  ]
  const appended = []
  const s = {
    job: ref({ id: 'current', sessionId: 'session', turnIndex: 2, status: 'running' }), sessionTurns: ref([]),
    restoreGeneration: 1, timelineLoadGeneration: 0, timelineController: null,
    timelineLoading: ref(false), timelineError: ref(''), handoffTimelineReceipt: ref(null), currentSessionTitle: ref(''),
    selectedTurnJobId: ref('current'), restoringJob: ref(false), currentAiOwnerUserId: () => 'owner',
    getMindmapAiSessionTimeline: async () => ({ data: { title: '范围验收', turns: serverTurns } }),
    cloneRuntimeValue: value => JSON.parse(JSON.stringify(value)), resolveMindmapAiSessionTitle, mergeMindmapAiJobSnapshot, mergeMindmapAiJobEventSnapshot,
    appendClientPrompt: (...args) => appended.push(args), appendAgentEvent() {}, persistActiveJob() {}, syncCurrentJobCursor() {},
    isTerminalStatus: () => false, finalizeTerminalJob: assert.fail, isAbortError: () => false,
    formatMindmapAiError: error => error.message,
    jobConfiguration: ref({ sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'later', label: '当前草稿' }] }),
  }
  const api = compile(['restoreSessionTimeline', 'upsertSessionTurn'], s)
  const restored = await api.restoreSessionTimeline('session')
  assert.ok(Array.isArray(restored), s.timelineError.value)
  assert.equal(s.timelineLoading.value, false)
  historicalContext.contextNodes[0].label = '服务端响应对象后来被改变'
  s.jobConfiguration.value.contextNodes[0].label = '下一次选中的节点'
  const conversation = buildMindmapAiConversationTurns({ sessionTurns: restored, currentJob: s.job.value })
  assert.deepEqual(conversation.map(turn => turn.job.id), ['legacy', 'old', 'current'])
  assert.equal(conversation[0].userMessage.context, null)
  assert.deepEqual(conversation[1].userMessage.context.contextNodes, [{ uid: 'a', label: '模块甲' }, { uid: 'b', label: '模块乙' }])
  assert.equal(conversation[1].userMessage.attachments[0].name, '需求.pdf')
  assert.equal(conversation[2].userMessage.context.scopeType, 'document')
  assert.deepEqual(appended.find(args => args[0] === 'old'), ['old', '原范围', 1, '2026-09-30T16:20:05'])
})

for (const accepted of [true, false]) {
  test(`uncertain queued request ${accepted ? 'restores metadata and consumes accepted files' : 'preserves unsent files on recovery failure'}`, async () => {
    const original = file()
    const { text, status, ...metadata } = original
    const originalConfiguration = { sourceMode: 'current', scopeType: 'branch', contextNodes: [{ uid: 'original-node', label: '排队时的节点' }] }
    let attempts = { queue: { key: 'queue-key', sessionId: 'session', requestPayload: { prompt: '要求', attachments: [metadata] }, configuration: structuredClone(originalConfiguration) } }
    const s = {
      componentAlive: true, job: ref({ id: 'parent', sessionId: 'session' }), sessionTurns: ref([]), queueAttempt: { key: 'queue-key' },
      composerAttachments: ref([original, file('later')]), cloneRuntimeValue: structuredClone,
      readPersistedAttempts: () => structuredClone(attempts), writePersistedAttempts: value => { attempts = value; return true },
      replayFollowupAttempt: async () => { if (!accepted) throw new Error('offline'); return { id: 'child', turnIndex: 2 } },
      appendClientPrompt() {}, consumeSubmittedComposerDraft() {}, restoreDurableAttemptNotice() {}, livePreviewError: ref(''),
      jobConfiguration: ref({ sourceMode: 'current', scopeType: 'document', contextNodes: [] }),
    }
    const api = compile(['reconcileQueuedCanvasRequest', 'upsertSessionTurn', 'clearDurableAttempt'], s)
    if (!accepted) {
      await assert.rejects(api.reconcileQueuedCanvasRequest('parent'), /offline/)
      assert.deepEqual(s.composerAttachments.value.map(item => item.id), ['original', 'later'])
      assert.equal(attempts.queue.key, 'queue-key')
      assert.equal(s.sessionTurns.value.length, 0)
    } else {
      assert.equal((await api.reconcileQueuedCanvasRequest('parent')).id, 'child')
      assert.deepEqual(s.composerAttachments.value.map(item => item.id), ['later'])
      assert.equal(s.sessionTurns.value[0].userMessage.attachments[0].id, 'original')
      assert.deepEqual(s.sessionTurns.value[0].userMessage.attachments[0].parsing, { status: 'unknown' }, 'legacy queue metadata does not prove parsing succeeded')
      assert.deepEqual(s.sessionTurns.value[0].userMessage.context, originalConfiguration, 'queue recovery uses its original submitted configuration, not the later draft')
      assert.doesNotMatch(JSON.stringify(s.sessionTurns.value), /PRIVATE_ATTACHMENT_TEXT/)
      assert.deepEqual(attempts, {})
    }
  })
}


test('template source revision survives frozen capture and exact private retry replay', () => {
  const attachment = {
    id: 'template-map-130-7', name: '项目模版', size: 10,
    mediaType: 'application/x-mindmap-template', text: '# 项目',
    purpose: 'template', templateSource: { mindmapId: 130, contentRevision: 7 }, status: 'ready',
  }
  const s = installComposerAttachmentHarness({ composerAttachments: ref([attachment]) })
  const captured = s.captureComposerAttachments()
  attachment.templateSource.contentRevision = 8
  assert.deepEqual(captured[0].templateSource, { mindmapId: 130, contentRevision: 7 })
  const stored = { key: 'template-attempt', attachmentsOmitted: true,
    requestPayload: { prompt: '沿用模版', attachments: [{ id: attachment.id }] } }
  s.privateAttachmentRequests.set(stored.key, { ...stored.requestPayload, attachments: captured })
  const replay = s.replayableRequestPayload(stored)
  assert.deepEqual(replay.attachments[0].templateSource, { mindmapId: 130, contentRevision: 7 })
  replay.attachments[0].templateSource.contentRevision = 9
  assert.equal(captured[0].templateSource.contentRevision, 7)
})

test('composer warns about deep templates without changing the budget or leaking UI depth into requests', () => {
  const attachment = { id: 'template-depth', name: '七层模版', size: 20,
    mediaType: 'application/x-mindmap-template', text: '- 示例节点', purpose: 'template',
    templateSource: { mindmapId: 136, contentRevision: 0 }, templateDepth: 7, status: 'ready' }
  const s = installComposerAttachmentHarness({ computed, form: reactive({ maxDepth: 6 }),
    composerAttachments: ref([attachment]), composerEditable: ref(true) })
  const names = ['composerTemplate', 'composerTemplateDepthHint']
  const declarations = nodes.filter(node => node.type === 'VariableDeclaration'
    && node.declarations.some(item => names.includes(item.id?.name)))
  assert.equal(declarations.length, names.length)
  const ui = new Function('scope', `with(scope) { ${declarations.map(node => script.slice(node.start, node.end)).join('\n')}; return { ${names.join(', ')} }; }`)(s)
  assert.equal(ui.composerTemplateDepthHint.value, '模版最深7层，当前上限6层；可在任务设置提高层级，以使用深层关系和标签。')
  assert.equal(s.form.maxDepth, 6)
  const captured = s.captureComposerAttachments()
  assert.equal(captured.length, 1, 'depth guidance does not block submission')
  assert.equal(Object.hasOwn(captured[0], 'templateDepth'), false)
  const replay = s.replayableRequestPayload({ attachmentsOmitted: true,
    attachmentIds: [attachment.id], requestPayload: { prompt: '生成内容' } })
  assert.equal(Object.hasOwn(replay.attachments[0], 'templateDepth'), false)
  s.form.maxDepth = 7
  assert.equal(ui.composerTemplateDepthHint.value, '')
  s.form.maxDepth = 6
  delete s.composerAttachments.value[0].templateDepth
  assert.equal(ui.composerTemplateDepthHint.value, '', 'legacy metadata does not invent depth')
  s.composerAttachments.value[0].templateDepth = 7
  const api = compile(['removeComposerAttachment'], s)
  api.removeComposerAttachment(attachment.id)
  assert.equal(ui.composerTemplateDepthHint.value, '')
  assert.equal(s.form.maxDepth, 6, 'removal also preserves the selected budget')
})

test('template layout guidance follows frozen running inputs, then the actual retry or follow-up attachments', () => {
  const attachment = { id: 'template-turn', name: '模版', size: 20,
    mediaType: 'application/x-mindmap-template', text: '- 示例节点', purpose: 'template',
    templateSource: { mindmapId: 136, contentRevision: 21 }, status: 'ready' }
  const s = installComposerAttachmentHarness({ computed, job: ref(null), sessionTurns: ref([]),
    followupAvailable: ref(false), composerAttachments: ref([attachment]) })
  const names = ['composerTemplate', 'terminalStatuses', 'retryableStatuses', 'running', 'retryAvailable',
    'currentJobTemplate', 'templateLayoutLocked', 'composerTemplateReuseHint']
  const declarations = nodes.filter(node => node.type === 'VariableDeclaration'
    && node.declarations.some(item => names.includes(item.id?.name)))
  assert.equal(declarations.length, names.length)
  const ui = new Function('scope', `with(scope) { ${declarations.map(node => script.slice(node.start, node.end)).join('\n')}; return { ${names.join(', ')} }; }`)(s)
  assert.equal(ui.templateLayoutLocked.value, true)
  assert.equal(ui.composerTemplateReuseHint.value, '')
  const submitted = s.captureComposerAttachments()
  s.job.value = { id: 'first', status: 'running' }
  s.sessionTurns.value = [{ job: { id: 'first' }, userMessage: { attachments: submitted } }]
  s.consumeComposerAttachments(submitted)
  assert.equal(ui.templateLayoutLocked.value, true, 'in-flight task still uses its frozen template')
  assert.equal(ui.composerTemplateReuseHint.value, '')

  s.job.value.status = 'failed'
  assert.equal(ui.templateLayoutLocked.value, false, 'history must not promise a template on the next request')
  assert.match(ui.composerTemplateReuseHint.value, /本轮.*重新添加模版/)
  assert.equal(s.captureComposerAttachments(), undefined, 'guidance agrees with the actual retry payload')
  s.composerAttachments.value = [{ ...attachment, templateSource: { mindmapId: 140, contentRevision: 3 } }]
  assert.equal(ui.templateLayoutLocked.value, true)
  assert.equal(ui.composerTemplateReuseHint.value, '')
  assert.equal(s.captureComposerAttachments()[0].templateSource.mindmapId, 140)

  s.composerAttachments.value = []
  s.job.value.status = 'completed_file'
  s.followupAvailable.value = true
  assert.equal(ui.templateLayoutLocked.value, false)
  assert.match(ui.composerTemplateReuseHint.value, /重新添加模版/)
  s.job.value = { id: 'next-without-template', status: 'running' }
  s.followupAvailable.value = false
  assert.equal(ui.templateLayoutLocked.value, false, 'another turn cannot borrow an earlier template receipt')
  assert.equal(ui.composerTemplateReuseHint.value, '')
})
