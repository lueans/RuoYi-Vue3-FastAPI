import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { babelParse, parse } from '@vue/compiler-sfc'
import { computed, effectScope, h as createVNode, nextTick, ref } from 'vue'
import { projectAgentHandoff } from '../mindmap-agent-handoff.js'
import { projectRuntimeEvents, readAgentPreferences, saveAgentPreferences } from '../mindmap-ai-runtime.js'
import { deviceExecutionIssue, isDeviceAgent } from '../mindmap-agent-devices.js'
import { isMindmapExecutionBlocked } from '../mindmap-execution-state.js'
import { useMindmapExecutionStop } from '../use-mindmap-execution-stop.js'

const event = (sequence, eventType, payload) => ({ key: `j:${sequence}`, sequence, eventType, payload })

test('runtime projects deltas and matches concurrent tools by call identity without touching draft data', () => {
  const events = [
    event(1, 'assistant_delta', { messageId: 'm1', text: '正在' }),
    event(2, 'assistant_delta', { messageId: 'm1', text: '检查' }),
    event(3, 'tool_started', { callId: 'a', toolName: 'add_nodes', toolInput: '{"nodes":[]}' }),
    event(4, 'tool_started', { callId: 'b', toolName: 'add_nodes' }),
    event(5, 'tool_completed', { callId: 'a', toolName: 'add_nodes', toolOutput: '{"ok":true}', durationMs: 25 }),
    event(6, 'draft_changed', { operations: [{ type: 'add' }] }),
  ]
  const before = JSON.stringify(events)
  const view = projectRuntimeEvents(events, { running: false, cancelled: true })
  assert.equal(view.entries[0].text, '正在检查')
  assert.equal(view.entries[1].status, 'completed')
  assert.equal(view.entries[2].status, 'cancelled')
  assert.equal(view.entries.length, 3)
  assert.equal(JSON.stringify(events), before)
})

test('todo snapshots remain replayable and latest plan replaces, not appends', () => {
  const view = projectRuntimeEvents([
    event(1, 'todo_updated', { todos: [{ content: '检查', status: 'in_progress' }] }),
    event(2, 'todo_updated', { todos: [{ content: '检查', status: 'completed' }] }),
  ])
  assert.equal(view.todos[0].status, 'completed')
  assert.equal(view.entries[0].todos[0].status, 'in_progress')
})

test('ACP partial metadata refreshes one tool in its original step and retains status-only terminal details', () => {
  const events = [
    event(1, 'todo_updated', { todos: [{ content: '检查', status: 'in_progress' }] }),
    event(2, 'tool_started', { callId: 'acp:tool-1', toolName: 'CLI tool', toolInput: '{"limit":10}' }),
    event(3, 'todo_updated', { todos: [{ content: '整理', status: 'in_progress' }] }),
    event(4, 'tool_started', { callId: 'acp:tool-1', toolName: 'Read', toolInput: '{"limit":10,"page":2}', toolOutput: '已找到三个节点' }),
    event(5, 'tool_completed', { callId: 'acp:tool-1', toolName: 'Read', durationMs: 3100 }),
    event(6, 'tool_started', { callId: 'acp:tool-1', toolName: 'stale', toolOutput: 'late' }),
    event(7, 'draft_changed', { operations: [{ type: 'add' }] }),
  ]
  const original = JSON.stringify(events)
  for (let length = 2; length <= events.length; length++) {
    const view = projectRuntimeEvents(events.slice(0, length), { running: true })
    const calls = view.entries.filter(entry => entry.kind === 'tool')
    assert.equal(calls.length, 1)
    assert.equal(calls[0].step.content, '检查')
    assert.equal(calls[0].key, 'j:2')
    if (length >= 4) {
      assert.equal(calls[0].name, 'Read')
      assert.equal(calls[0].output, '已找到三个节点')
      assert.equal(calls[0].input, '{"limit":10,"page":2}')
    }
    if (length >= 5) {
      assert.equal(calls[0].status, 'completed')
      assert.equal(calls[0].duration, 3100)
    }
  }
  assert.equal(JSON.stringify(events), original)
})

test('ACP orphan terminal does not fabricate a Todo association or duration, and unfinished stays unconfirmed', () => {
  const view = projectRuntimeEvents([
    event(1, 'todo_updated', { todos: [{ content: '检查', status: 'in_progress' }] }),
    event(2, 'tool_completed', { callId: 'acp:tool-1', toolName: 'Read', toolOutput: 'result' }),
    event(3, 'tool_started', { callId: 'acp:tool-2', toolName: 'Search' }),
  ], { running: false })
  const [orphan, unfinished] = view.entries.filter(entry => entry.kind === 'tool')
  assert.equal(orphan.step, undefined)
  assert.equal(orphan.duration, undefined)
  assert.equal(unfinished.status, 'unknown')
})

test('preferences are scoped per account and survive invalid or unavailable browser storage', () => {
  const items = new Map()
  const storage = { getItem: key => items.get(key), setItem: (key, value) => items.set(key, value) }
  assert.equal(saveAgentPreferences(1, { defaultAgent: 'claude', hidden: ['codex'] }, storage), true)
  assert.equal(readAgentPreferences(1, storage).defaultAgent, 'claude')
  assert.equal(readAgentPreferences(2, storage).defaultAgent, 'native_mindmap')
  items.set('mindmap:agent-preferences:1', 'invalid')
  assert.deepEqual(readAgentPreferences(1, storage), { defaultAgent: 'native_mindmap', hidden: [] })
  assert.equal(saveAgentPreferences(1, {}, { setItem() { throw Error('quota') } }), false)
})

function switchHarness() {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAiDialog.vue', import.meta.url), 'utf8')
  const script = parse(source).descriptor.scriptSetup.content
  const fn = babelParse(script, { sourceType: 'module' }).program.body.find(node => node.type === 'FunctionDeclaration' && node.id.name === 'requestAgentSwitch')
  const summaryFn = babelParse(script, { sourceType: 'module' }).program.body.find(node => node.type === 'FunctionDeclaration' && node.id.name === 'agentHandoffSummary')
  const calls = [], notices = []
  const scope = {
    h: createVNode, MindmapAgentHandoffSummary: {}, projectAgentHandoff, nextTick,
    agentSwitchPhase: ref(''), agentExecutionPickerRef: ref(null), agentEvents: ref([]),
    sessionTurns: ref([]), handoffTimelineReceipt: ref(null), timelineLoading: ref(false),
    timelineError: ref(''), currentResultState: ref({ title: '预览中' }), proposal: ref(null),
    isDeviceAgent, deviceExecutionIssue,
    isMindmapExecutionBlocked,
    form: { agentKey: 'claude' }, job: { value: { id: 'j1' } }, running: { value: true },
    actionBusy: { value: false }, restoringJob: { value: false }, agentManagerVisible: { value: true },
    agents: { value: [{ agentKey: 'codex', displayName: 'Codex', status: 'enabled' }] },
    agentPreferences: { value: { hidden: [] } }, agentSupportsCurrentTask: () => true,
    agentSwitchPending: { value: false }, agentSwitchGeneration: 0, componentAlive: true,
    currentAiOwnerUserId: () => '7', deviceCatalog: {
      loaded: true, enabled: true, error: '', updatedAt: Date.now(), now: Date.now(),
      devices: ['old-device', 'new-device', 'my-device'].map(deviceId => ({
        deviceId, status: 'online', executionAvailable: true,
        executionAgents: ['claude', 'codex', 'kimi'],
      })),
    },
    agentExecutionLocation: (_, devices) => devices[0]?.name || '我的电脑', refreshDeviceCatalog: async () => true,
    ElMessageBox: { confirm: async () => { calls.push('confirm') } },
    ElMessage: { success: () => {}, info: message => notices.push(message) }, onAgentChange: () => calls.push('change'),
    cancelJob: async () => { calls.push('cancel'); scope.running.value = false; return true },
    executionStop: { waitForStopped: async () => !scope.running.value && !isMindmapExecutionBlocked(scope.job.value) },
    finalizeTerminalJob: async () => true,
  }
  const run = new Function('scope', `with(scope) { ${script.slice(summaryFn.start, summaryFn.end)}; ${script.slice(fn.start, fn.end)}; return requestAgentSwitch; }`)(scope)
  return { scope, calls, notices, run }
}

test('confirmation renders the live summary without freezing stream progress', async () => {
  const fixture = switchHarness()
  fixture.scope.ElMessageBox.confirm = async (message, title, options) => {
    assert.equal(title, '停止当前轮并切换 Agent')
    assert.equal(options.customClass, 'mindmapAgentHandoffBox')
    assert.equal(message().props.summary.result.title, '预览中')
    fixture.scope.currentResultState.value = { title: '保存中' }
    assert.equal(message().props.summary.result.title, '保存中')
  }
  assert.equal(await fixture.run('codex'), true)
})

test('a queued request added while confirming prevents cancellation', async () => {
  const fixture = switchHarness()
  fixture.scope.job.value.sessionId = 's1'
  fixture.scope.ElMessageBox.confirm = async () => {
    fixture.scope.sessionTurns.value = [{ job: { id: 'j2', sessionId: 's1', status: 'waiting_turn', agentKey: 'claude' } }]
  }
  assert.equal(await fixture.run('codex'), false)
  assert.deepEqual(fixture.calls, [])
  assert.match(fixture.notices[0], /排队请求已变化/)
})

test('an account transition hides the summary instead of showing another owner data', async () => {
  const fixture = switchHarness()
  fixture.scope.ElMessageBox.confirm = async message => {
    fixture.scope.currentAiOwnerUserId = () => '8'
    assert.equal(message().type, 'p')
    assert.match(message().children, /账号已变化/)
  }
  assert.equal(await fixture.run('codex'), false)
  assert.deepEqual(fixture.calls, [])
})

test('queue successor reports that selection did not take effect without cancelling it', async () => {
  const fixture = switchHarness()
  fixture.scope.cancelJob = async () => {
    fixture.calls.push('cancel')
    fixture.scope.job.value = { id: 'successor', status: 'running', agentKey: 'claude' }
    return true
  }
  assert.equal(await fixture.run('codex'), false)
  assert.deepEqual(fixture.calls, ['confirm', 'cancel'])
  assert.match(fixture.notices[0], /没有中断或改绑/)
})

test('cancelled confirmation retains execution and restores keyboard focus after enabling picker', async () => {
  const fixture = switchHarness()
  fixture.scope.agentManagerVisible.value = false
  fixture.scope.agentExecutionPickerRef.value = { focus() {
    assert.equal(fixture.scope.agentSwitchPending.value, false)
    fixture.calls.push('focus')
  } }
  fixture.scope.ElMessageBox.confirm = async () => { throw new Error('cancel') }
  assert.equal(await fixture.run('codex'), false)
  assert.deepEqual(fixture.calls, ['focus'])
})

for (const change of ['disabled', 'hidden', 'capability', 'removed']) {
  test(`target ${change} during confirmation must not cancel the current run`, async () => {
    const h = switchHarness()
    h.scope.ElMessageBox.confirm = async () => {
      h.calls.push('confirm')
      if (change === 'disabled') h.scope.agents.value[0].status = 'disabled'
      if (change === 'hidden') h.scope.agentPreferences.value.hidden.push('codex')
      if (change === 'capability') h.scope.agentSupportsCurrentTask = () => false
      if (change === 'removed') h.scope.agents.value = []
    }
    assert.equal(await h.run('codex'), false)
    assert.deepEqual(h.calls, ['confirm'])
    assert.equal(h.scope.running.value, true)
    assert.equal(h.scope.form.agentKey, 'claude')
    assert.equal(h.scope.agentSwitchPending.value, false)
    assert.equal(h.notices.length, 1)
  })
}

function deviceSwitchHarness() {
  const h = switchHarness()
  h.scope.agents.value.push({ agentKey: 'device_codex', displayName: '本机 Codex', status: 'enabled' })
  h.selection = { agentKey: 'device_codex', deviceId: 'new-device' }
  h.device = h.scope.deviceCatalog.devices.find(device => device.deviceId === h.selection.deviceId)
  return h
}

const deviceFailures = {
  offline: h => { h.device.status = 'offline' },
  revoked: h => { h.device.status = 'revoked' },
  busy: h => { h.device.executionBusy = true },
  channel: h => { h.device.executionAgents = ['claude'] },
  unavailable: h => { h.device.executionAvailable = false },
  removed: h => { h.scope.deviceCatalog.devices = [] },
  disabled: h => { h.scope.deviceCatalog.enabled = false },
  error: h => { h.scope.deviceCatalog.error = 'network' },
  unloaded: h => { h.scope.deviceCatalog.loaded = false },
  stale: h => {
    // A suspended tab's reactive clock can lag; use wall-clock freshness.
    h.scope.deviceCatalog.updatedAt = Date.now() - 16000
    h.scope.deviceCatalog.now = h.scope.deviceCatalog.updatedAt
  },
}
for (const [reason, invalidate] of Object.entries(deviceFailures)) {
  for (const phase of ['before-confirm', 'during-confirm', 'after-stop']) {
    test(`${reason} target device ${phase} never becomes the selected execution setting`, async () => {
      const h = deviceSwitchHarness()
      if (phase === 'before-confirm') invalidate(h)
      if (phase === 'during-confirm') h.scope.ElMessageBox.confirm = async () => { h.calls.push('confirm'); invalidate(h) }
      if (phase === 'after-stop') h.scope.finalizeTerminalJob = async () => { invalidate(h); return true }
      assert.equal(await h.run(h.selection), false)
      assert.deepEqual(h.calls, phase === 'before-confirm' ? [] : phase === 'during-confirm' ? ['confirm'] : ['confirm', 'cancel'])
      assert.equal(h.scope.form.agentKey, 'claude')
      assert.equal(h.scope.agentSwitchPending.value, false)
      assert.equal(h.notices.length, 1)
    })
  }
}

test('missing target computer must not stop a run, but idle agent selection can expose the computer picker', async () => {
  const h = deviceSwitchHarness()
  assert.equal(await h.run('device_codex'), false)
  assert.deepEqual(h.calls, [])
  assert.match(h.notices.at(-1), /管理 Agents/)
  h.scope.running.value = false
  assert.equal(await h.run('device_codex'), true)
  assert.equal(h.scope.form.agentKey, 'device_codex')
  assert.equal(h.scope.form.deviceId, '')
  assert.deepEqual(h.calls, ['change'])
})

test('same-computer handoff tolerates this run being busy, then refreshes availability after exit', async () => {
  const h = deviceSwitchHarness()
  Object.assign(h.scope.form, { agentKey: 'device_claude', deviceId: 'new-device' })
  Object.assign(h.scope.job.value, { agentKey: 'device_claude', deviceId: 'new-device', status: 'running', executionState: 'running' })
  const cancel = h.scope.cancelJob
  h.scope.cancelJob = async () => {
    const cancelled = await cancel()
    Object.assign(h.scope.job.value, { status: 'cancelled', executionState: 'stopped' })
    return cancelled
  }
  h.device.executionBusy = true
  h.device.executionAvailable = false
  const refreshes = []
  h.scope.refreshDeviceCatalog = async options => {
    refreshes.push({ running: h.scope.running.value, options })
    if (!h.scope.running.value) { h.device.executionBusy = false; h.device.executionAvailable = true }
    return true
  }
  assert.equal(await h.run(h.selection), true)
  assert.deepEqual(h.calls, ['confirm', 'cancel', 'change'])
  assert.deepEqual(refreshes.slice(0, 2), [
    { running: true, options: { afterPending: true } },
    { running: false, options: { afterPending: true } },
  ])
  assert.equal(h.scope.job.value.agentKey, 'device_claude')
})

test('a queued run has no authority to treat an occupied computer as its own', async () => {
  const h = deviceSwitchHarness()
  Object.assign(h.scope.job.value, { agentKey: 'device_claude', deviceId: 'new-device', executionState: 'not_started' })
  h.device.executionBusy = true
  assert.equal(await h.run(h.selection), false)
  assert.deepEqual(h.calls, [])
})

test('changing owner during target refresh must not stop or rebind a successor', async () => {
  const h = deviceSwitchHarness()
  h.scope.refreshDeviceCatalog = async () => { h.scope.currentAiOwnerUserId = () => '8'; return true }
  assert.equal(await h.run(h.selection), false)
  assert.deepEqual(h.calls, ['confirm'])
  assert.equal(h.scope.form.agentKey, 'claude')
})

for (const phase of ['before-stop', 'after-stop']) {
  test(`unconfirmed fresh device read ${phase} cannot use an earlier cached availability`, async () => {
    const h = deviceSwitchHarness()
    h.scope.refreshDeviceCatalog = async () => phase === 'after-stop' && h.scope.running.value
    assert.equal(await h.run(h.selection), false)
    assert.deepEqual(h.calls, phase === 'before-stop' ? ['confirm'] : ['confirm', 'cancel'])
    assert.equal(h.scope.form.agentKey, 'claude')
    assert.equal(h.scope.agentSwitchPending.value, false)
    assert.equal(h.notices.length, 1)
  })
}

test('switching waits for authoritative cancellation, then changes only the next agent', async () => {
  const h = switchHarness()
  assert.equal(await h.run('codex'), true)
  assert.deepEqual(h.calls, ['confirm', 'cancel', 'change'])
  assert.equal(h.scope.form.agentKey, 'codex')
  assert.equal(h.scope.job.value.id, 'j1')
})

test('a retained draft cannot switch agents until an independent exit receipt arrives', async () => {
  const h = switchHarness()
  h.scope.running.value = false
  h.scope.job.value = { id: 'j1', status: 'ready', artifactId: 'draft', executionEpoch: 3, executionState: 'running' }
  assert.equal(await h.run('codex'), false)
  assert.equal(h.scope.form.agentKey, 'claude')
  assert.deepEqual(h.calls, [])
  h.scope.job.value.executionState = 'stopped'
  assert.equal(await h.run('codex'), true)
  assert.equal(h.scope.form.agentKey, 'codex')
  assert.equal(h.scope.job.value.artifactId, 'draft')
  assert.deepEqual(h.calls, ['change'])
})

test('rejected cancellation and queued successor cannot switch the executing agent', async () => {
  const rejected = switchHarness()
  rejected.scope.ElMessageBox.confirm = async () => { throw 'cancel' }
  assert.equal(await rejected.run('codex'), false)
  assert.equal(rejected.scope.form.agentKey, 'claude')
  assert.deepEqual(rejected.calls, [])
  const queued = switchHarness()
  queued.scope.cancelJob = async () => { queued.scope.job.value = { id: 'j2' }; return true }
  assert.equal(await queued.run('codex'), false)
  assert.equal(queued.scope.form.agentKey, 'claude')
  assert.ok(!queued.calls.includes('change'))
})

test('an account or task transition during switch confirmation leaves the new task alone', async () => {
  const h = switchHarness()
  h.scope.ElMessageBox.confirm = async () => { h.scope.job.value = null }
  assert.equal(await h.run('codex'), false)
  assert.ok(!h.calls.includes('cancel'))
})

test('switching computers with the same agent stops the old run without rewriting its binding', async () => {
  const h = switchHarness()
  Object.assign(h.scope.form, { agentKey: 'device_claude', deviceId: 'old-device' })
  Object.assign(h.scope.job.value, { agentKey: 'device_claude', deviceId: 'old-device' })
  h.scope.agents.value.push({ agentKey: 'device_claude', displayName: '本机 Claude', status: 'enabled' })
  assert.equal(await h.run({ agentKey: 'device_claude', deviceId: 'new-device' }), true)
  assert.deepEqual(h.calls, ['confirm', 'cancel', 'change'])
  assert.equal(h.scope.form.deviceId, 'new-device')
  assert.equal(h.scope.job.value.deviceId, 'old-device')
  assert.equal(h.scope.agentSwitchPending.value, false)
})

test('switching Claude to Codex retains the explicitly chosen computer only after the old run stops', async () => {
  const h = switchHarness()
  Object.assign(h.scope.form, { agentKey: 'device_claude', deviceId: 'my-device' })
  Object.assign(h.scope.job.value, { agentKey: 'device_claude', deviceId: 'my-device' })
  h.scope.agents.value.push({ agentKey: 'device_codex', displayName: '本机 Codex', status: 'enabled' })
  assert.equal(await h.run('device_codex'), true)
  assert.deepEqual(h.calls, ['confirm', 'cancel', 'change'])
  assert.equal(h.scope.form.deviceId, 'my-device')
  assert.equal(h.scope.form.agentKey, 'device_codex')
  assert.equal(h.scope.job.value.agentKey, 'device_claude')
})

test('switching to Kimi keeps the current run binding and waits for confirmed cancellation', async () => {
  const h = switchHarness()
  Object.assign(h.scope.form, { agentKey: 'device_codex', deviceId: 'my-device' })
  Object.assign(h.scope.job.value, { agentKey: 'device_codex', deviceId: 'my-device' })
  h.scope.agents.value.push({ agentKey: 'device_kimi', displayName: '本机 Kimi', status: 'enabled' })
  assert.equal(await h.run('device_kimi'), true)
  assert.deepEqual(h.calls, ['confirm', 'cancel', 'change'])
  assert.equal(h.scope.form.deviceId, 'my-device')
  assert.equal(h.scope.form.agentKey, 'device_kimi')
  assert.equal(h.scope.job.value.agentKey, 'device_codex')
})

test('switch confirmations are exclusive and closure invalidates a pending confirmation', async () => {
  const h = switchHarness()
  let confirm
  h.scope.ElMessageBox.confirm = () => new Promise(resolve => { confirm = resolve })
  const first = h.run('codex')
  assert.equal(await h.run('codex'), false)
  h.scope.agentSwitchGeneration++
  h.scope.agentSwitchPending.value = false
  confirm()
  assert.equal(await first, false)
  assert.equal(h.scope.form.agentKey, 'claude')
  assert.deepEqual(h.calls, [])
})

test('unconfirmed cancellation or a changed account never applies the selected target', async () => {
  for (const scenario of ['running', 'cleanup-failed', 'owner']) {
    const h = switchHarness()
    h.scope.cancelJob = async () => {
      if (scenario === 'owner') h.scope.currentAiOwnerUserId = () => 'other-user'
      h.scope.running.value = scenario === 'running'
      return scenario !== 'cleanup-failed'
    }
    assert.equal(await h.run('codex'), false, scenario)
    assert.equal(h.scope.form.agentKey, 'claude', scenario)
    assert.equal(h.scope.agentSwitchPending.value, false, scenario)
  }
})

function delayedSwitchHarness(t, { status = 'cancel_requested', accepted = true, timeoutMs = 1000 } = {}) {
  const h = switchHarness()
  const effects = effectScope()
  const job = ref({ id: 'j1', status: 'running', executionEpoch: 3, executionState: 'running' })
  const owner = ref('7')
  Object.assign(h.scope, {
    job, running: computed(() => ['running', 'cancel_requested'].includes(job.value.status)),
    agentSwitchPending: ref(false), currentAiOwnerUserId: () => owner.value,
    continuationPrompt: ref('保留已有修改，再补充边界情况'),
    finalizeTerminalJob: async () => true,
    cancelJob: async () => {
      h.calls.push('cancel')
      job.value = { ...job.value, status, artifactId: 'retained', cancelRequestedTime: '2026-09-26T10:00:00' }
      return accepted
    },
  })
  const monitor = effects.run(() => useMindmapExecutionStop({
    job, ownerId: () => owner.value, loadJob: async () => ({ data: { ...job.value } }), intervalMs: 1000,
  }))
  h.scope.executionStop = { ...monitor, waitForStopped: options => monitor.waitForStopped({ ...options, timeoutMs }) }
  t.after(() => effects.stop())
  return { ...h, job, owner, effects }
}

for (const [status, accepted] of [['cancel_requested', true], ['ready', false]]) {
  test(`one confirmation survives delayed exit after ${status}, retaining the draft`, async t => {
    const h = delayedSwitchHarness(t, { status, accepted })
    let settled = false
    const result = h.run('codex').then(value => { settled = true; return value })
    await nextTick(); await nextTick(); await nextTick()
    assert.equal(settled, false, 'an accepted cancellation is not a failed switch')
    assert.equal(h.scope.agentSwitchPending.value, true)
    assert.equal(h.scope.agentSwitchPhase.value, '等待旧 Agent 退出')
    assert.equal(h.scope.form.agentKey, 'claude')
    h.scope.continuationPrompt.value += '，不要删节点'
    h.job.value = { ...h.job.value, status: 'ready', executionState: 'stopped' }
    assert.equal(await result, true)
    assert.deepEqual(h.calls, ['confirm', 'cancel', 'change'])
    assert.equal(h.scope.form.agentKey, 'codex')
    assert.equal(h.job.value.artifactId, 'retained')
    assert.equal(h.scope.continuationPrompt.value, '保留已有修改，再补充边界情况，不要删节点')
  })
}

test('confirmed exit still waits for canvas settlement before selecting the next agent', async t => {
  const h = delayedSwitchHarness(t)
  let release
  h.scope.finalizeTerminalJob = () => new Promise(resolve => { release = resolve })
  const result = h.run('codex')
  await nextTick(); await nextTick()
  h.job.value = { ...h.job.value, status: 'ready', executionState: 'stopped' }
  await nextTick(); await nextTick()
  assert.equal(h.scope.form.agentKey, 'claude')
  assert.equal(h.scope.agentSwitchPending.value, true)
  assert.equal(typeof release, 'function')
  assert.equal(h.scope.agentSwitchPhase.value, '同步脑图结果')
  release(true)
  assert.equal(await result, true)
})

for (const change of ['sync-failed', 'queued-successor', 'disabled', 'hidden', 'capability']) {
  test(`handoff revalidates canvas ownership and target after ${change}`, async t => {
    const h = delayedSwitchHarness(t)
    h.scope.finalizeTerminalJob = async () => {
      if (change === 'queued-successor') h.job.value = { ...h.job.value, id: 'j2', status: 'running' }
      if (change === 'disabled') h.scope.agents.value[0].status = 'disabled'
      if (change === 'hidden') h.scope.agentPreferences.value.hidden.push('codex')
      if (change === 'capability') h.scope.agentSupportsCurrentTask = () => false
      return change !== 'sync-failed'
    }
    const result = h.run('codex')
    await nextTick(); await nextTick()
    h.job.value = { ...h.job.value, status: 'ready', executionState: 'stopped' }
    assert.equal(await result, false)
    assert.equal(h.scope.form.agentKey, 'claude')
    assert.equal(h.scope.agentSwitchPending.value, false)
    assert.ok(!h.calls.includes('change'))
  })
}

for (const transition of ['job', 'epoch', 'owner', 'closed', 'disposed', 'unconfirmed', 'timeout']) {
  test(`pending handoff cannot apply after ${transition}`, async t => {
    const h = delayedSwitchHarness(t, { timeoutMs: transition === 'timeout' ? 20 : 1000 })
    const result = h.run('codex')
    await nextTick(); await nextTick()
    if (transition === 'job') h.job.value = { ...h.job.value, id: 'j2' }
    if (transition === 'epoch') h.job.value = { ...h.job.value, executionEpoch: 4 }
    if (transition === 'owner') h.owner.value = '8'
    if (transition === 'closed') { h.scope.agentSwitchGeneration++; h.scope.agentSwitchPending.value = false }
    if (transition === 'disposed') h.effects.stop()
    if (transition === 'unconfirmed') h.job.value = { ...h.job.value, executionState: 'unconfirmed' }
    assert.equal(await result, false)
    h.job.value = { ...h.job.value, status: 'ready', executionState: 'stopped' }
    await nextTick()
    assert.equal(h.scope.form.agentKey, 'claude', 'late exit must not revive a discarded selection')
    assert.equal(h.scope.agentSwitchPending.value, false)
    assert.ok(!h.calls.includes('change'))
  })
}
