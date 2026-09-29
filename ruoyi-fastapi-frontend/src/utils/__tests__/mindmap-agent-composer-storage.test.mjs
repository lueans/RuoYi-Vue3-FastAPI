import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { ref, effectScope, nextTick } from 'vue'
import { memoryStorage } from './helpers/memory-storage.mjs'
import { createMindmapComposerDraftStorage, resolveMindmapComposerDraftScope } from '../mindmap-agent-composer-storage.js'
import { useMindmapComposerDraft } from '../use-mindmap-composer-draft.js'

const scope = (ownerId = '1', documentKey = 'cloud:130', sessionId = 'session') => ({ ownerId, documentKey, sessionId })
function repository(storage = memoryStorage()) {
  let sequence = 0
  let now = 1_800_000_000_000
  return { storage, setNow: value => { now = value }, now: () => now,
    drafts: createMindmapComposerDraftStorage({ storage: () => storage, now: () => now, createId: () => `draft-${++sequence}` }) }
}
function editor(repository, initialScope = scope()) {
  const currentScope = ref(initialScope)
  const ready = ref(true)
  const text = ref('')
  const lifetime = effectScope()
  const draft = lifetime.run(() => useMindmapComposerDraft({
    scope: () => currentScope.value, ready: () => ready.value,
    readText: () => text.value, writeText: value => { text.value = value }, repository: repository.drafts,
  }))
  return { currentScope, ready, text, draft, stop: () => lifetime.stop() }
}

test('draft scope requires an authenticated owner, an editor document, and an exact route match', () => {
  const context = { mindmapId: 130, documentId: 'runtime', document: { root: {} } }
  assert.deepEqual(resolveMindmapComposerDraftScope({ ownerId: 1, context, sessionId: 's', routeMindmapId: '130' }), scope('1', 'cloud:130', 's'))
  for (const input of [{ ownerId: '' }, { context: null }, { routeMindmapId: '131' }, { sessionId: {} },
    { job: { id: 'not-hydrated' } },
    { job: { sessionId: 'other' } },
    { job: { sessionId: 's', sourceType: 'cloud_document', sourceMindmapId: 131 } }]) {
    assert.equal(resolveMindmapComposerDraftScope({ ownerId: 1, context, sessionId: 's', ...input }), null)
  }
  assert.deepEqual(resolveMindmapComposerDraftScope({ ownerId: 1, context: { documentId: 'local', document: { root: {} } } }), scope('1', 'local:local', null))
})

test('only exact account/document/conversation drafts restore, including separate new-conversation drafts', () => {
  const { drafts } = repository()
  drafts.write(scope(), '未发送\n保持换行')
  assert.equal(drafts.read(scope()).text, '未发送\n保持换行')
  for (const other of [scope('2'), scope('1', 'cloud:131'), scope('1', 'local:130'), scope('1', 'cloud:130', 'other'), scope('1', 'cloud:130', null)]) {
    assert.equal(drafts.read(other), null)
  }
})

test('late acceptance only removes the exact draft revision, including equal text retyped later', () => {
  const { drafts } = repository()
  const first = drafts.write(scope(), '相同要求')
  const later = drafts.write(scope(), '相同要求')
  assert.notEqual(first.id, later.id)
  assert.equal(drafts.remove(scope(), first.id), false)
  assert.equal(drafts.read(scope()).id, later.id)
  assert.equal(drafts.remove(scope(), later.id), true)
  assert.equal(drafts.read(scope()), null)
})

test('each stored draft is bounded, text-only and expires independently', () => {
  const h = repository()
  assert.throws(() => h.drafts.write(scope(), 'x'.repeat(20_001)))
  for (let index = 0; index < 25; index++) h.drafts.write(scope('1', 'cloud:130', `s-${index}`), `draft ${index}`)
  assert.equal(h.drafts.read(scope('1', 'cloud:130', 's-0')).text, 'draft 0')
  assert.equal(h.drafts.read(scope('1', 'cloud:130', 's-24')).text, 'draft 24')
  const record = h.drafts.write(scope(), '文本', { token: 'never', document: { root: {} } })
  assert.deepEqual(Object.keys(record).sort(), ['id', 'savedAt', 'scope', 'text'])
  assert(![...h.storage.values.values()].some(value => value.includes('never')))
  h.setNow(h.now() + 8 * 24 * 60 * 60 * 1000)
  assert.equal(h.drafts.read(scope()), null)
})

test('malformed and mismatched storage cannot populate the composer', () => {
  const h = repository()
  h.drafts.write(scope(), 'old')
  const key = [...h.storage.values.keys()][0]
  for (const value of ['{broken', '[]', JSON.stringify({ version: 1, ownerId: '2', drafts: [] }), 'x'.repeat(2_000_001)]) {
    h.storage.values.set(key, value)
    assert.equal(h.drafts.read(scope()), null)
  }
})

test('refresh restores the exact draft and clearing text removes its persisted copy', async () => {
  const h = repository()
  const first = editor(h)
  first.draft.update('刷新后继续写')
  first.stop()
  const reopened = editor(h)
  assert.equal(reopened.text.value, '刷新后继续写')
  assert.match(reopened.draft.notice.value, /恢复.*文字/)
  reopened.draft.update('')
  reopened.stop()
  assert.equal(h.drafts.read(scope()), null)
})

test('session restoration defers binding until stable and never writes reset values into the next scope', async () => {
  const h = repository()
  h.drafts.write(scope('1', 'cloud:130', 'second'), '第二会话的草稿')
  const e = editor(h)
  e.draft.update('第一会话的草稿')
  e.ready.value = false
  e.currentScope.value = scope('1', 'cloud:130', null)
  e.text.value = '' // resetNewJob during switch/restore, not user input
  await nextTick()
  e.currentScope.value = scope('1', 'cloud:130', 'second')
  await nextTick()
  assert.equal(e.text.value, '')
  e.ready.value = true
  await nextTick()
  assert.equal(e.text.value, '第二会话的草稿')
  assert.equal(h.drafts.read(scope()).text, '第一会话的草稿')
  assert.equal(h.drafts.read(scope('1', 'cloud:130', null)), null)
  e.stop()
})

test('same-session task handoff does not overwrite an in-memory draft with stale storage', async () => {
  const h = repository()
  const e = editor(h)
  e.draft.update('下一条要求')
  e.ready.value = false
  await nextTick()
  e.currentScope.value = { ...scope() }
  e.ready.value = true
  await nextTick()
  assert.equal(e.text.value, '下一条要求')
  e.stop()
})

test('accepted receipt cannot erase a newer draft or another account, even after remount', async () => {
  const h = repository()
  const e = editor(h)
  e.draft.update('已发送的要求')
  const accepted = e.draft.capture('已发送的要求')
  e.draft.update('')
  e.draft.update('已发送的要求')
  assert.equal(e.draft.consume(accepted), false)
  assert.equal(e.text.value, '已发送的要求')
  const current = e.draft.capture('已发送的要求')
  e.stop()
  const reopened = editor(h)
  assert.equal(reopened.draft.consume(current), true)
  assert.equal(reopened.text.value, '')
  reopened.currentScope.value = scope('2')
  await nextTick()
  reopened.draft.update('另一账号的文字')
  assert.equal(reopened.draft.consume(current), false)
  assert.equal(reopened.text.value, '另一账号的文字')
  reopened.stop()
})

test('storage getters/quota/silent writes failing never disable typing or clear the visible draft', () => {
  for (const storage of [memoryStorage({ throwOnWrite: true }), memoryStorage({ ignoreWrites: true })]) {
    const e = editor(repository(storage))
    e.draft.update('保留本页输入')
    assert.equal(e.text.value, '保留本页输入')
    assert.match(e.draft.notice.value, /无法.*保存/)
    e.stop()
  }
  const drafts = createMindmapComposerDraftStorage({ storage: () => { throw new Error('disabled') } })
  const e = editor({ drafts })
  e.draft.update('隐私模式也能输入')
  assert.equal(e.text.value, '隐私模式也能输入')
  e.stop()
})

test('a failed storage read after an account switch must not leave the previous account text visible', async () => {
  const h = repository()
  const e = editor(h)
  e.draft.update('账号一的私有草稿')
  h.storage.getItem = () => { throw new Error('storage disabled') }
  e.currentScope.value = scope('2')
  await nextTick()
  assert.equal(e.text.value, '')
  assert.match(e.draft.notice.value, /无法/)
  e.stop()
})

test('failed newer writes never reuse the old draft receipt', () => {
  const h = repository()
  const e = editor(h)
  e.draft.update('相同要求')
  const first = e.draft.capture('相同要求')
  h.storage.setItem = () => { throw new Error('quota') }
  e.draft.update('相同要求')
  assert.equal(e.draft.capture('相同要求'), null)
  e.draft.consume(first)
  assert.equal(e.text.value, '相同要求')
  e.stop()
})

const dialog = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const script = parse(dialog).descriptor.scriptSetup.content
const declarations = babelParse(script, { sourceType: 'module' }).program.body
function productionFunctions(names, bindings) {
  const selected = declarations.filter(node => node.type === 'FunctionDeclaration' && names.includes(node.id.name))
  assert.equal(selected.length, names.length)
  return new Function('scope', `with (scope) { ${selected.map(node => script.slice(node.start, node.end)).join('\n')}; return { ${names.join(', ')} }; }`)(bindings)
}

for (const type of ['create', 'queue', 'followup', 'retry']) {
  test(`${type} production durable attempt keeps the original draft receipt when reconciling an identical request`, async () => {
    const h = repository()
    const e = editor(h)
    let attempts = {}
    let keys = 0
    const bindings = {
      currentAiOwnerUserId: () => '1', composerDraftPersistence: e.draft,
      fingerprintMindmapAiRequest: JSON.stringify, hashAttemptFingerprint: async value => value,
      readPersistedAttempts: () => structuredClone(attempts),
      writePersistedAttempts: value => { attempts = structuredClone(value); return true },
      resolveMindmapAiRequestAttempt: (_old, _payload, { createKey }) => ({ key: createKey() }),
      cloneRuntimeValue: structuredClone, continuationPrompt: e.text, form: { prompt: '' },
    }
    const api = productionFunctions(['resolveDurableAttempt', 'consumeSubmittedComposerDraft'], bindings)
    const request = { prompt: '同文的新要求' }
    const payload = type === 'create' ? request : { requestPayload: request }
    e.draft.update(request.prompt)
    const original = await api.resolveDurableAttempt(type, null, payload, { createKey: () => `request-${++keys}` })
    const originalReceipt = structuredClone(attempts[type].composerDraft)
    assert.equal(originalReceipt.id, h.drafts.read(scope()).id)
    assert.equal('text' in originalReceipt, false, 'receipt adds identity, not another prompt copy')
    e.draft.update('')
    e.draft.update(request.prompt)
    const newerId = h.drafts.read(scope()).id
    assert.notEqual(newerId, originalReceipt.id)
    const reused = await api.resolveDurableAttempt(type, null, payload, { createKey: () => `request-${++keys}` })
    assert.equal(reused.key, original.key)
    assert.deepEqual(attempts[type].composerDraft, originalReceipt)
    api.consumeSubmittedComposerDraft(request.prompt, type, reused.key)
    assert.equal(e.text.value, request.prompt)
    assert.equal(h.drafts.read(scope()).id, newerId)
    attempts = {}
    const accepted = await api.resolveDurableAttempt(type, null, payload, { createKey: () => `request-${++keys}` })
    api.consumeSubmittedComposerDraft(request.prompt, type, accepted.key)
    assert.equal(h.drafts.read(scope()), null)
    assert.equal(e.text.value, '')
    e.stop()
  })
}

test('receipt consumption during restoration prevents an accepted prompt from returning on later binding', async () => {
  const h = repository()
  const old = editor(h)
  old.draft.update('服务端已接受')
  const receipt = old.draft.capture('服务端已接受')
  old.stop()
  const active = ref(false)
  const value = ref('')
  const lifetime = effectScope()
  const restored = lifetime.run(() => useMindmapComposerDraft({ scope: () => scope(), ready: () => active.value,
    readText: () => value.value, writeText: text => { value.value = text }, repository: h.drafts }))
  restored.consume(receipt)
  active.value = true
  await nextTick()
  assert.equal(value.value, '')
  assert.equal(h.drafts.read(scope()), null)
  lifetime.stop()
})

test('a missing click-time draft receipt is not recaptured from newer text or consumed by equality', async () => {
  const h = repository()
  const e = editor(h)
  let attempts = {}
  const bindings = {
    currentAiOwnerUserId: () => '1',
    composerDraftPersistence: { capture: () => assert.fail('must not capture newer text'), consume: () => assert.fail('missing receipt') },
    fingerprintMindmapAiRequest: JSON.stringify, hashAttemptFingerprint: async value => value,
    readPersistedAttempts: () => structuredClone(attempts),
    writePersistedAttempts: value => { attempts = structuredClone(value); return true },
    resolveMindmapAiRequestAttempt: (_old, _payload, { createKey }) => ({ key: createKey() }),
    cloneRuntimeValue: structuredClone, continuationPrompt: e.text, form: { prompt: '' },
  }
  const api = productionFunctions(['resolveDurableAttempt', 'consumeSubmittedComposerDraft'], bindings)
  e.draft.update('与先前提交相同但尚未发送的文字')
  const attempt = await api.resolveDurableAttempt('followup', null, { requestPayload: { prompt: e.text.value } }, {
    createKey: () => 'accepted-request', draftReceipt: null,
  })
  api.consumeSubmittedComposerDraft(e.text.value, 'followup', attempt.key)
  assert.equal(e.text.value, '与先前提交相同但尚未发送的文字')
  assert.equal(h.drafts.read(scope()).text, e.text.value)
  e.stop()
})

test('composer exposes restoration/storage status and an explicit clear action without new send gates', () => {
  assert.match(dialog, /class="composerDraftNotice" role="status"/)
  assert.match(dialog, /composerDraftPersisted/)
  assert.match(dialog, /@click="composerText = ''">清除草稿/)
  const computed = declarations.find(node => node.declarations?.some(item => item.id.name === 'composerCanSend'))
  assert.doesNotMatch(script.slice(computed.start, computed.end), /composerDraft/)
})
