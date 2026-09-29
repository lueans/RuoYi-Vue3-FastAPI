import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { createRenderer, nextTick, ref } from 'vue'
import { useMindmapAgentDevices } from '../use-mindmap-agent-devices.js'
import { isMindmapExecutionBlocked } from '../mindmap-execution-state.js'
import { agentExecutionLocation, deviceExecutionIssue, deviceExecutionLabel, deviceExecutionCommand, deviceBudgetNotice, isDeviceAgent, isDeviceCatalogFresh, CODEX_DEVICE_BUDGET_NOTICE, KIMI_DEVICE_BUDGET_NOTICE } from '../mindmap-agent-devices.js'

const deviceId = '54bc6619-12a1-4cfb-a90d-735f816fd17a'
const online = { deviceId, name: '测试 MacBook', status: 'online', executionAvailable: true, executionAgents: ['claude'] }
const catalog = (overrides = {}) => ({ loaded: true, enabled: true, updatedAt: 10000, devices: [{ ...online }], ...overrides })

test('cached device badges are unverified after errors or stale refresh timestamps', () => {
  assert.equal(isDeviceCatalogFresh(catalog(), 11000), true)
  for (const state of [{ error: 'offline' }, { loaded: false }, { updatedAt: 0 }, { updatedAt: NaN }, { updatedAt: '10000' }]) {
    assert.equal(isDeviceCatalogFresh(catalog(state), 11000), false)
  }
  assert.equal(isDeviceCatalogFresh(catalog(), 26000), false)
})

test('only an explicitly selected, fresh, available Claude execution channel enables sending', () => {
  assert.equal(deviceExecutionIssue(deviceId, catalog(), { now: 11000 }), '')
  for (const state of [
    { loaded: false }, { enabled: false }, { error: 'network' }, { updatedAt: 0 }, { updatedAt: 1 },
    { devices: [] }, { devices: [{ ...online, status: 'offline' }] },
    { devices: [{ ...online, status: 'revoked' }] },
    { devices: [{ ...online, executionAgents: ['codex'] }] },
    { devices: [{ ...online, executionAvailable: false }] },
    { devices: [{ ...online, executionBusy: true }] },
  ]) assert.notEqual(deviceExecutionIssue(deviceId, catalog(state), { now: 20000 }), '', JSON.stringify(state))
  assert.notEqual(deviceExecutionIssue('', catalog(), { now: 11000 }), '')
  assert.match(deviceExecutionIssue('', catalog({ loaded: false, error: 'network' })), /读取失败/)
  const busy = catalog({ devices: [{ ...online, executionAvailable: false, executionBusy: true }] })
  assert.equal(deviceExecutionIssue(deviceId, busy, { now: 11000, allowBusy: true }), '')
  assert.notEqual(deviceExecutionIssue(deviceId, { ...busy, error: 'offline' }, { now: 11000, allowBusy: true }), '')
})

test('execution labels never imply CLI login is authenticated, and old turns keep their device', () => {
  assert.equal(deviceExecutionLabel(online), '执行通道已连接')
  assert.equal(deviceExecutionLabel({ status: 'online' }), '仅发现模式')
  assert.equal(agentExecutionLocation({ agentKey: 'claude' }, [online]), '平台运行主机')
  assert.equal(agentExecutionLocation({ agentKey: 'device_claude', deviceId }, [online]), online.name)
  assert.match(agentExecutionLocation({ agentKey: 'device_claude', deviceId: 'old-device' }, [online]), /old-devi/)
})

const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content
const ast = babelParse(script, { sourceType: 'module' }).program
const declaration = name => ast.body.find(node => node.type === 'FunctionDeclaration' && node.id.name === name)
const run = (name, values) => { const bindings = { isDeviceAgent, isMindmapExecutionBlocked, ...values }; return new Function(...Object.keys(bindings), `${script.slice(declaration(name).start, declaration(name).end)}; return ${name}`)(...Object.values(bindings)) }

for (const method of ['retryJob', 'continueJob']) {
  test(`${method} blocks unconfirmed execution before preparing a canvas or creating a task`, async () => {
    const notices = []
    const bindings = { job: ref({ id: 'old-run', status: 'ready', executionState: 'running', executionEpoch: 3 }),
      ElMessage: { info: text => notices.push(text) } }
    // No downstream bindings are supplied: reaching any side effect fails.
    assert.equal(await run(method, bindings)(), false)
    assert.match(notices[0], /尚未确认退出/)
  })
}
test('the dialog permits a busy computer only for the currently bound running turn', () => {
  const statement = ast.body.flatMap(item => item.declarations || []).find(item => item.id.name === 'selectedDeviceIssue')
  const bindings = {
    form: { agentKey: 'device_claude', deviceId },
    deviceCatalog: catalog({ now: 11000, devices: [{ ...online, executionAvailable: false, executionBusy: true }] }),
    running: ref(true), job: ref({ agentKey: 'device_claude', deviceId }), deviceExecutionIssue,
    computed: getter => getter(), isDeviceAgent,
  }
  const evaluate = () => new Function(...Object.keys(bindings), `return ${script.slice(statement.init.start, statement.init.end)}`)(...Object.values(bindings))
  assert.equal(evaluate(), '')
  bindings.deviceCatalog.devices[0].executionAgents = ['claude', 'codex']
  bindings.form.agentKey = 'device_codex'
  assert.match(evaluate(), /其他任务/)
  bindings.job.value.agentKey = 'device_codex'
  assert.equal(evaluate(), '')
  bindings.job.value.deviceId = 'other-device'
  assert.match(evaluate(), /其他任务/)
  bindings.job.value.deviceId = deviceId
  bindings.running.value = false
  assert.match(evaluate(), /其他任务/)
})
function findPayload(node) {
  if (node?.type === 'VariableDeclarator' && node.id.name === 'requestPayload') return node.init
  for (const value of Object.values(node || {})) {
    if (!value || typeof value !== 'object') continue
    for (const child of Array.isArray(value) ? value : [value]) {
      const result = findPayload(child)
      if (result) return result
    }
  }
}

for (const method of ['submitJob', 'retryJob', 'continueJob', 'queueRunningMessage']) {
  test(`${method} carries only the explicitly selected device in its actual request payload`, () => {
    const payload = findPayload(declaration(method))
    const bindings = {
      form: { agentKey: 'device_claude', deviceId, prompt: '测试' }, prompt: '测试', isDeviceAgent,
      runningMessageRoute: ref('next'), effectiveFormIntent: ref('expand'),
      continuationPrompt: ref('测试'), submittedPrompt: '测试', jobConfiguration: ref({}), job: ref({}),
      continuationBase: 'artifact', parentJob: {}, expectedParentStatus: null,
      currentSnapshotSource: undefined, requestedIntent: 'expand', source: { type: 'none' },
      effectiveRequestLayout: () => 'logicalStructure', discussionMode: ref(false), directExecution: false, sourceContext: ref(null),
    }
    const evaluate = () => new Function(...Object.keys(bindings), `return (${script.slice(payload.start, payload.end)})`)(...Object.values(bindings))
    assert.equal(evaluate().deviceId, deviceId)
    bindings.form.agentKey = 'device_codex'
    assert.equal(evaluate().deviceId, deviceId)
    bindings.form.agentKey = 'device_kimi'
    assert.equal(evaluate().deviceId, deviceId)
    bindings.form.agentKey = 'claude'
    assert.equal(evaluate().deviceId, undefined)
  })
  test(`${method} refuses stale device state and pending agent switches before task creation`, async () => {
    const warnings = []
    const bindings = { form: { agentKey: 'device_claude' }, selectedDeviceIssue: ref('设备离线'),
      agentSwitchPending: ref(false), ElMessage: { warning: value => { warnings.push(value) } },
      job: ref({ id: 'job' }), continuationPrompt: ref('继续'), continuing: ref(false) }
    await run(method, bindings)()
    assert.deepEqual(warnings, ['设备离线'])
    bindings.agentSwitchPending.value = true
    assert.equal(await run(method, bindings)(), false)
  })
}

test('stored request configuration does not pick up a later form device during recovery', () => {
  const capture = run('captureJobConfiguration', {
    form: { agentKey: 'device_claude', deviceId: 'later-device' },
    GENERATION_MODE_VALUES: new Set(), discussionMode: ref(false),
  })
  assert.equal(capture({ agentKey: 'device_claude', deviceId }).deviceId, deviceId)
  assert.equal(capture({ agentKey: 'claude', deviceId }).deviceId, '')
  assert.equal(capture({ agentKey: 'device_claude', deviceId: '' }).deviceId, '')
  assert.equal(capture({ agentKey: 'device_codex', deviceId }).deviceId, deviceId)
})

test('Codex readiness is independent of PATH discovery and cannot borrow a Claude connection', () => {
  const options = { now: 11000, agentKey: 'device_codex' }
  assert.match(deviceExecutionIssue(deviceId, catalog(), options), /--execute codex --accept-estimated-budget/)
  assert.equal(deviceExecutionIssue(deviceId, catalog({ devices: [{ ...online, executionAgents: ['claude', 'codex'], runtimes: [] }] }), options), '')
  assert.equal(deviceExecutionLabel(online, 'device_codex'), '未开启 Codex')
  assert.equal(agentExecutionLocation({ agentKey: 'device_codex', deviceId }, [online]), online.name)
  assert.match(CODEX_DEVICE_BUDGET_NOTICE, /不是硬费用上限/)
})

test('Kimi discovery cannot grant execution, borrow another Agent, or hide unmetered budget policy', () => {
  const options = { now: 11000, agentKey: 'device_kimi' }
  const scanned = { ...online, runtimes: [{ agentKey: 'kimi', version: '2.1.1', status: 'detected' }] }
  assert.match(deviceExecutionIssue(deviceId, catalog({ devices: [scanned] }), options), /--execute kimi --accept-unmetered-budget/)
  assert.equal(deviceExecutionLabel(scanned, 'device_kimi'), '未开启 Kimi')
  const ready = { ...scanned, executionAgents: ['kimi'] }
  assert.equal(deviceExecutionIssue(deviceId, catalog({ devices: [ready] }), options), '')
  assert.match(deviceExecutionIssue(deviceId, catalog({ devices: [ready] }), { ...options, agentKey: 'device_codex' }), /--execute codex/)
  assert.match(deviceExecutionIssue(deviceId, catalog({ devices: [{ ...ready, status: 'offline' }] }), options), /离线/)
  assert.equal(agentExecutionLocation({ agentKey: 'device_kimi', deviceId }, [ready]), online.name)
  assert.equal(deviceBudgetNotice('device_kimi'), KIMI_DEVICE_BUDGET_NOTICE)
  assert.match(KIMI_DEVICE_BUDGET_NOTICE, /不执行金额预算上限/)
  assert.match(deviceExecutionCommand('device_kimi'), /--accept-unmetered-budget$/)
  assert.equal(deviceBudgetNotice('device_claude'), '')
})

function catalogHarness(list) {
  const active = ref(true), owner = ref('first')
  let api
  const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode() {}, nextSibling() {} })
  const app = renderer.createApp({ setup() {
    api = useMindmapAgentDevices(() => active.value, () => owner.value, list)
    return () => null
  } })
  app.mount({})
  return { active, owner, api, close: () => app.unmount() }
}
const flush = async () => { await nextTick(); await Promise.resolve(); await nextTick() }

test('handoff refresh waits out an old poll and performs a new availability read', async () => {
  const pending = []
  const h = catalogHarness(() => new Promise(resolve => pending.push(resolve)))
  try {
    let settled = false
    const fresh = h.api.refresh({ afterPending: true }).then(value => { settled = true; return value })
    await flush()
    assert.equal(settled, false)
    assert.equal(pending.length, 1)
    pending[0]({ data: { enabled: true, devices: [{ ...online, executionBusy: true, executionAvailable: false }] } })
    await flush()
    assert.equal(pending.length, 2, 'an already-issued poll is not a post-exit availability check')
    assert.equal(settled, false)
    pending[1]({ data: { enabled: true, devices: [online] } })
    assert.equal(await fresh, true)
    assert.equal(deviceExecutionIssue(deviceId, h.api.state), '')
  } finally { h.close() }
})

for (const transition of ['owner', 'closed']) {
  test(`queued availability refresh loses authority when ${transition} changes`, async () => {
    const pending = []
    const h = catalogHarness(() => new Promise(resolve => pending.push(resolve)))
    try {
      const fresh = h.api.refresh({ afterPending: true })
      if (transition === 'owner') h.owner.value = 'second'
      else h.active.value = false
      await flush()
      const expectedRequests = transition === 'owner' ? 2 : 1
      pending[0]({ data: { enabled: true, devices: [online] } })
      assert.equal(await fresh, false)
      assert.equal(pending.length, expectedRequests)
      assert.equal(h.api.state.devices.length, 0)
      if (transition === 'owner') {
        pending[1]({ data: { enabled: true, devices: [{ ...online, deviceId: 'second-device' }] } })
        await flush()
        assert.equal(h.api.state.devices[0].deviceId, 'second-device')
      }
    } finally { h.close() }
  })
}

test('device polling drops a late previous-account response and clears identity on dialog closure', async () => {
  const pending = []
  const h = catalogHarness(() => new Promise(resolve => pending.push(resolve)))
  try {
    h.owner.value = 'second'
    await flush()
    pending[1]({ data: { enabled: true, devices: [{ ...online, deviceId: 'second-device' }] } })
    await flush()
    pending[0]({ data: { enabled: true, devices: [online] } })
    await flush()
    assert.equal(h.api.state.devices[0].deviceId, 'second-device')
    h.active.value = false
    await flush()
    assert.equal(h.api.state.devices.length, 0)
    assert.equal(h.api.state.updatedAt, 0)
    assert.equal(await h.api.refresh(), false)
  } finally { h.close() }
})

test('a failed refresh cannot leave a previously available device usable; recovery is explicit', async () => {
  let fail = false
  const h = catalogHarness(async () => {
    if (fail) throw new Error('network')
    return { data: { enabled: true, devices: [online] } }
  })
  try {
    await flush()
    assert.equal(deviceExecutionIssue(deviceId, h.api.state), '')
    fail = true
    await h.api.refresh()
    assert.match(deviceExecutionIssue(deviceId, h.api.state), /读取失败/)
    fail = false
    await h.api.refresh()
    assert.equal(deviceExecutionIssue(deviceId, h.api.state), '')
  } finally { h.close() }
})
