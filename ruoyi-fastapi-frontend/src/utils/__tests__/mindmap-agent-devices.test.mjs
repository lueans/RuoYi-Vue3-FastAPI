import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, babelParse } from '@vue/compiler-sfc'
import { agentDeviceStatus, agentInstallationStatus, createAgentRequestScope, pairingSecondsRemaining } from '../mindmap-agent-devices.js'

test('account/dialog scope discards old responses without invalidating the new request', () => {
  const scope = createAgentRequestScope()
  const old = scope.capture()
  scope.invalidate()
  const current = scope.capture()
  assert.equal(old(), false)
  assert.equal(current(), true)
  scope.invalidate()
  assert.equal(current(), false)
})

test('installation detection does not claim authenticated execution readiness', () => {
  assert.equal(agentDeviceStatus('online'), '在线')
  assert.equal(agentDeviceStatus('offline'), '已配对 · 离线')
  assert.match(agentInstallationStatus({ status: 'detected' }), /登录状态未检查/)
  assert.equal(agentInstallationStatus({ status: 'invented' }), '尚未检查')
  assert.equal(pairingSecondsRemaining(2000, 1001), 1)
  assert.equal(pairingSecondsRemaining(2000, 2001), 0)
  assert.equal(pairingSecondsRemaining(undefined), 0)
})

function harness() {
  const source = readFileSync(new URL('../../components/MindMap/MindmapAgentDevices.vue', import.meta.url), 'utf8')
  const script = parse(source).descriptor.scriptSetup.content
  const ast = babelParse(script, { sourceType: 'module' }).program
  const functions = ast.body.filter(node => node.type === 'FunctionDeclaration').map(node => script.slice(node.start, node.end)).join('\n')
  const ref = value => ({ value })
  const scope = {
    props: { active: true, ownerId: 7 }, scope: createAgentRequestScope(),
    loading: ref(false), loaded: ref(false), enabled: ref(true), devices: ref([]),
    busy: ref(''), error: ref(''), pairing: ref(null), deviceName: ref('我的电脑'), clockNow: ref(0), updatedAt: ref(0),
    pollTimer: null, setTimeout: () => 1, clearTimeout: () => {},
    api: { list: async () => ({ data: { enabled: true, devices: [] } }), pair: async () => ({ data: { deviceId: 'dev1', pairingCode: 'demo-code', expiresIn: 300 } }), scan: async () => {}, revoke: async () => {} },
    ElMessageBox: { confirm: async () => {} },
  }
  const functionsByName = new Function('scope', `with (scope) { ${functions}; return { loadDevices, pairDevice, scanDevice, revokeDevice }; }`)(scope)
  return { scope, ...functionsByName }
}

test('a late pairing result after an account switch cannot display a previous account code', async () => {
  const h = harness()
  let resolve
  h.scope.api.pair = () => new Promise(done => { resolve = done })
  const pending = h.pairDevice()
  h.scope.scope.invalidate()
  h.scope.props.ownerId = 8
  h.scope.busy.value = 'new-owner-action'
  resolve({ data: { deviceId: 'private-device', pairingCode: 'private-old-code', expiresIn: 300 } })
  await pending
  assert.equal(h.scope.pairing.value, null)
  assert.equal(h.scope.busy.value, 'new-owner-action')
})

test('a late device list after closure cannot replace newer account state', async () => {
  const h = harness()
  let resolve
  h.scope.api.list = () => new Promise(done => { resolve = done })
  const pending = h.loadDevices()
  h.scope.scope.invalidate()
  h.scope.devices.value = [{ deviceId: 'new-owner-device' }]
  resolve({ data: { enabled: true, devices: [{ deviceId: 'old-owner-device' }] } })
  await pending
  assert.deepEqual(h.scope.devices.value, [{ deviceId: 'new-owner-device' }])
})

test('revocation confirmation cannot act after account/dialog scope changed', async () => {
  const h = harness()
  let resolve
  let revocations = 0
  h.scope.ElMessageBox.confirm = () => new Promise(done => { resolve = done })
  h.scope.api.revoke = async () => { revocations++ }
  const pending = h.revokeDevice({ deviceId: 'dev1', name: '我的电脑' })
  h.scope.scope.invalidate()
  resolve()
  await pending
  assert.equal(revocations, 0)
})

test('pairing records only the short-lived code and does not retain arbitrary response fields', async () => {
  const h = harness()
  let now = 10000
  h.scope.Date = { now: () => now }
  h.scope.api.pair = async () => ({ data: { deviceId: 'dev1', pairingCode: 'demo-code', expiresIn: 99999, privateCredential: 'must-not-store' } })
  h.scope.api.list = async () => { now += 25; return { data: { enabled: true, devices: [] } } }
  await h.pairDevice()
  assert.equal(h.scope.pairing.value.pairingCode, 'demo-code')
  assert.equal(h.scope.pairing.value.expiresAt, 310000)
  assert.equal(h.scope.clockNow.value, 10025, 'refresh latency does not extend the original five-minute expiry')
  assert.equal('privateCredential' in h.scope.pairing.value, false)
})
