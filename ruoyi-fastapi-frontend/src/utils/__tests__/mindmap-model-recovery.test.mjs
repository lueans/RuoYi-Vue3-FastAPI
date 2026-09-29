import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { computed, effectScope, nextTick, reactive, ref, toRefs, watch } from 'vue'
import { enabledRecoveryModels, modelRepairLocation, normalizeModelRecoveryId } from '../mindmap-model-recovery.js'
import { useMindmapModelRecovery } from '../use-mindmap-model-recovery.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((a, b) => { resolve = a; reject = b })
  return { promise, resolve, reject }
}

test('repair links accept only exact positive safe integer IDs', () => {
  for (const value of [1, '2', Number.MAX_SAFE_INTEGER]) assert.equal(normalizeModelRecoveryId(value), Number(value))
  for (const value of [undefined, null, true, false, [], ['2'], {}, 0, -1, 1.5, NaN, Infinity,
    '', ' 2', '2 ', '+2', '02', '2e1', '2/../1', '9007199254740992', 'https://example.com']) {
    assert.equal(normalizeModelRecoveryId(value), null, String(value))
  }
})

test('repair navigation requires the actual route and all edit permissions, and carries no task data', () => {
  const permissions = ['ai:model:list', 'ai:model:query', 'ai:model:edit']
  const options = { permissions, routeAvailable: true, modelId: 2, prompt: 'private prompt', apiKey: 'secret' }
  assert.deepEqual(modelRepairLocation(options), { path: '/ai/model', query: { from: 'mindmap-agent', modelId: '2' } })
  assert.deepEqual(modelRepairLocation({ ...options, permissions: ['*:*:*'] }), modelRepairLocation(options))
  assert.equal(modelRepairLocation({ ...options, routeAvailable: false }), null)
  for (const excluded of permissions) assert.equal(modelRepairLocation({ ...options, permissions: permissions.filter(p => p !== excluded) }), null)
  for (const value of [null, '*:*:*', [], {}]) assert.equal(modelRepairLocation({ ...options, permissions: value }), null)
  assert.deepEqual(modelRepairLocation({ ...options, modelId: null }), { path: '/ai/model', query: { from: 'mindmap-agent' } })
})

test('metadata refresh excludes disabled/invalid models and rejects malformed catalogues', () => {
  assert.deepEqual(enabledRecoveryModels({ data: [{ modelId: 1, status: '0' }, { modelId: 2, status: '1' },
    { modelId: '3', status: 0 }, null, { modelId: '../4', status: '0' }] }).map(m => m.modelId), [1, '3'])
  for (const response of [null, {}, { data: {} }]) assert.throws(() => enabledRecoveryModels(response))
  assert.deepEqual(enabledRecoveryModels({ data: [] }), [])
})

function refreshHarness(t, load = async () => ({ data: [{ modelId: 2, provider: 'OpenAI' }] })) {
  const scope = effectScope()
  const owner = ref('7'), epoch = ref(1), agent = ref('native_mindmap'), allowed = ref(true)
  const models = ref([{ modelId: 2, provider: 'Anthropic' }])
  const requests = []
  let loader = load
  const api = scope.run(() => useMindmapModelRecovery({ models,
    ownerId: () => owner.value, epoch: () => epoch.value, agentKey: () => agent.value,
    canRefresh: () => allowed.value,
    loadModels: options => { requests.push(options); return loader(options) },
  }))
  t.after(() => scope.stop())
  return { ...api, models, owner, epoch, agent, allowed, requests, scope, setLoad: value => { loader = value } }
}

test('refresh is explicit, updates metadata only, and never claims connectivity was verified', async t => {
  const h = refreshHarness(t)
  assert.equal(h.requests.length, 0)
  assert.equal(await h.refresh(), true)
  assert.equal(h.requests.length, 1)
  assert.equal(h.requests[0].silentError, true)
  assert.equal(h.models.value[0].provider, 'OpenAI')
  assert.match(h.notice.value, /实际连接和认证将在运行时校验.*不会自动发送任务/)
  assert.equal(h.loading.value, false)
})

test('duplicate refresh clicks make one request', async t => {
  const gate = deferred(), h = refreshHarness(t, () => gate.promise)
  const running = h.refresh()
  assert.equal(h.loading.value, true)
  assert.equal(await h.refresh(), false)
  assert.equal(h.requests.length, 1)
  gate.resolve({ data: [{ modelId: 2 }] })
  assert.equal(await running, true)
})

test('unauthenticated or locked editors do not read the model catalogue', async t => {
  const h = refreshHarness(t)
  h.owner.value = ''
  assert.equal(await h.refresh(), false)
  h.owner.value = '7'
  h.allowed.value = false
  assert.equal(await h.refresh(), false)
  assert.equal(h.requests.length, 0)
})

for (const reason of ['owner', 'epoch', 'agent', 'locked', 'disposed', 'invalidate']) {
  test(`late model metadata cannot overwrite the editor after ${reason}`, async t => {
    const gate = deferred(), h = refreshHarness(t, () => gate.promise)
    const before = h.models.value
    const pending = h.refresh()
    if (reason === 'owner') h.owner.value = '8'
    if (reason === 'epoch') h.epoch.value++
    if (reason === 'agent') h.agent.value = 'claude'
    if (reason === 'locked') h.allowed.value = false
    if (reason === 'disposed') h.scope.stop()
    if (reason === 'invalidate') h.invalidate()
    assert.equal(h.requests[0].signal.aborted, true)
    assert.equal(h.loading.value, false)
    gate.resolve({ data: [{ modelId: 8 }] }) // simulate a transport that ignores abort
    assert.equal(await pending, false)
    assert.equal(h.models.value, before)
    assert.equal(h.notice.value, '')
    assert.equal(h.error.value, '')
  })
}

test('a superseded refresh cannot clear the newer request loading flag or its results', async t => {
  const old = deferred(), latest = deferred(), h = refreshHarness(t, () => old.promise)
  const first = h.refresh()
  h.invalidate()
  h.setLoad(() => latest.promise)
  const second = h.refresh()
  old.resolve({ data: [{ modelId: 1 }] })
  await first
  assert.equal(h.loading.value, true)
  latest.resolve({ data: [{ modelId: 2, provider: 'OpenAI' }] })
  assert.equal(await second, true)
  assert.equal(h.models.value[0].provider, 'OpenAI')
})

test('failed or malformed refresh retains the old catalogue and offers a safe retry', async t => {
  const h = refreshHarness(t, async () => { throw Error('private provider URL') })
  const before = h.models.value
  assert.equal(await h.refresh(), false)
  assert.equal(h.models.value, before)
  assert.match(h.error.value, /保留上次清单/)
  assert.doesNotMatch(h.error.value, /private/)
  h.setLoad(async () => ({ data: {} }))
  assert.equal(await h.refresh(), false)
  assert.equal(h.models.value, before)
  h.setLoad(async () => ({ data: [] }))
  assert.equal(await h.refresh(), true)
  assert.deepEqual(h.models.value, [])
  assert.equal(h.error.value, '')
})

const modelSource = readFileSync(new URL('../../views/ai/model/index.vue', import.meta.url), 'utf8')
const modelScript = parse(modelSource).descriptor.scriptSetup.content
const modelBody = babelParse(modelScript, { sourceType: 'module' }).program.body
  .filter(node => node.type !== 'ImportDeclaration').map(node => modelScript.slice(node.start, node.end)).join('\n')
const modelExports = ['getList', 'clearModelFilter', 'queryParams', 'modelList', 'total', 'loading', 'listError',
  'repairModelId', 'invalidModelFilter', 'hasModelFilter', 'fromMindmap', 'form', 'open', 'ids', 'single', 'multiple', 'handleSelectionChange', 'resetQuery']

function pageHarness(t, { modelId = '2', load, from = 'mindmap-agent', path = '/ai/model' } = {}) {
  const effects = [], requests = [], navigation = [], lifecycle = []
  const route = reactive({ path, query: { ...(modelId !== undefined ? { modelId } : {}), from } })
  const user = reactive({ id: '7' })
  const scope = effectScope()
  let loader = load || (async query => ({ rows: query.modelId ? [{ modelId: query.modelId }] : [{ modelId: 1 }, { modelId: 2 }], total: query.modelId ? 1 : 2 }))
  const env = { computed, reactive, ref, toRefs, watch, normalizeModelRecoveryId,
    getCurrentInstance: () => ({ proxy: { useDict: () => ({}), resetForm: name => effects.push(['reset', name]) } }),
    onBeforeUnmount: cb => lifecycle.push(cb), useUserStore: () => user, useRoute: () => route,
    useRouter: () => ({ replace: async location => { navigation.push(location); route.query = location.query } }),
    listModel: (query, options) => { requests.push({ query, ...options }); return loader(query, options) },
    getModel: () => assert.fail('Navigation must not automatically open a credential editor'),
    addModel: () => assert.fail('Navigation is read-only'), updateModel: () => assert.fail('Navigation is read-only'),
    delModel: () => assert.fail('Navigation is read-only'),
  }
  const api = scope.run(() => new Function('scope', `with (scope) { ${modelBody}; return { ${modelExports.join(', ')} }; }`)(env))
  const dispose = () => { lifecycle.forEach(cb => cb()); scope.stop() }
  t.after(dispose)
  return { ...api, route, user, requests, navigation, effects, dispose, setLoad: fn => { loader = fn } }
}

test('the actual model management page consumes a deep link without opening or editing a model', async t => {
  const h = pageHarness(t)
  await nextTick()
  assert.equal(h.requests.length, 1)
  assert.equal(h.requests[0].query.modelId, 2)
  assert.equal(h.modelList.value.length, 1)
  assert.equal(h.modelList.value[0].modelId, 2)
  assert.equal(h.open.value, false)
  assert.deepEqual(h.form.value, {})
  assert.match(modelSource, /正在定位模型/)
  assert.match(modelSource, /不会自动切换模型或发送任务/)
})

test('normal management without a repair ID continues listing all models', async t => {
  const h = pageHarness(t)
  await nextTick()
  h.route.query = {}
  await nextTick()
  await nextTick()
  assert.equal(h.requests.at(-1).query.modelId, undefined)
  assert.equal(h.modelList.value.length, 2)
  assert.equal(h.fromMindmap.value, false)
})

test('existing customized menu paths continue working and clear filters within the same page', async t => {
  const h = pageHarness(t, { path: '/settings/ai-models' })
  await nextTick()
  assert.equal(h.requests.length, 1)
  assert.equal(h.modelList.value[0].modelId, 2)
  await h.clearModelFilter()
  await nextTick()
  assert.equal(h.navigation[0].path, '/settings/ai-models')
  assert.equal(h.modelList.value.length, 2)
})

for (const modelId of ['0', '-1', '', null, ['2', '1'], '../2', '9007199254740992']) {
  test(`invalid repair ID ${JSON.stringify(modelId)} cannot silently query a broader model list`, async t => {
    const h = pageHarness(t, { modelId })
    await nextTick()
    assert.equal(h.invalidModelFilter.value, true)
    assert.equal(h.requests.length, 0)
    assert.equal(h.loading.value, false)
    assert.deepEqual(h.modelList.value, [])
    await h.clearModelFilter()
    await nextTick()
    assert.equal(h.requests.length, 1, 'Only the explicit clear action may list all models')
    assert.equal(h.requests[0].query.modelId, undefined)
    assert.deepEqual(h.navigation[0], { path: '/ai/model', query: { from: 'mindmap-agent' } })
  })
}

test('switching repair targets discards stale rows, filters and selections, and ignores late responses', async t => {
  const old = deferred(), next = deferred()
  const h = pageHarness(t, { load: () => old.promise })
  h.queryParams.value.modelCode = 'unrelated'
  h.queryParams.value.pageNum = 9
  h.handleSelectionChange([{ modelId: 2 }])
  h.setLoad(() => next.promise)
  h.route.query.modelId = '1'
  await nextTick()
  assert.equal(h.requests[0].signal.aborted, true)
  assert.equal(h.requests.at(-1).query.modelId, 1)
  assert.equal(h.requests.at(-1).query.pageNum, 1)
  assert.equal(h.requests.at(-1).query.modelCode, undefined)
  assert.deepEqual(h.ids.value, [])
  assert.equal(h.single.value, true)
  old.resolve({ rows: [{ modelId: 2 }], total: 1 })
  await nextTick()
  assert.deepEqual(h.modelList.value, [])
  assert.equal(h.loading.value, true)
  next.resolve({ rows: [{ modelId: 1 }], total: 1 })
  await nextTick()
  assert.equal(h.modelList.value[0].modelId, 1)
})

for (const reason of ['owner', 'route', 'unmount']) {
  test(`model list responses stay fenced after ${reason} changes`, async t => {
    const gate = deferred(), h = pageHarness(t, { load: () => gate.promise })
    h.setLoad(async () => ({ rows: [], total: 0 }))
    if (reason === 'owner') h.user.id = '8'
    if (reason === 'route') h.route.path = '/index'
    if (reason === 'unmount') h.dispose()
    await nextTick()
    gate.resolve({ rows: [{ modelId: 2 }], total: 1 })
    await nextTick()
    assert.equal(h.requests[0].signal.aborted, true)
    assert.deepEqual(h.modelList.value, [])
    assert.equal(h.loading.value, false)
  })
}

test('failed model list reads end loading and can be retried with the same target', async t => {
  const h = pageHarness(t, { load: async () => { throw Error('secret diagnostics') } })
  await nextTick()
  assert.equal(h.loading.value, false)
  assert.match(h.listError.value, /加载失败/)
  assert.doesNotMatch(h.listError.value, /secret/)
  h.setLoad(async () => ({ rows: [{ modelId: 2 }], total: 1 }))
  assert.equal(await h.getList(), true)
  assert.equal(h.listError.value, '')
  assert.equal(h.requests.at(-1).query.modelId, 2)
})

test('malformed list replies cannot leave successful-looking rows', async t => {
  const h = pageHarness(t, { load: async () => ({ rows: null, total: '1' }) })
  await nextTick()
  assert.equal(h.loading.value, false)
  assert.match(h.listError.value, /加载失败/)
  assert.deepEqual(h.modelList.value, [])
})

test('a legitimate empty scoped result is not a network failure or permission disclosure', async t => {
  const h = pageHarness(t, { load: async () => ({ rows: [], total: 0 }) })
  await nextTick()
  assert.equal(h.listError.value, '')
  assert.equal(h.repairModelId.value, 2)
  assert.match(modelSource, /未找到该模型或没有查看权限/)
})

test('search reset preserves the explicit model scope until the user clears it', async t => {
  const h = pageHarness(t)
  await nextTick()
  h.resetQuery()
  await nextTick()
  assert.equal(h.requests.at(-1).query.modelId, 2)
  await h.clearModelFilter()
  await nextTick()
  assert.equal(h.requests.at(-1).query.modelId, undefined)
  assert.equal(h.open.value, false)
})
