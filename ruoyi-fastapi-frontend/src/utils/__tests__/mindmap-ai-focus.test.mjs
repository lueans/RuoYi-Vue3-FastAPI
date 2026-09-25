import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8')
const focusFunctions = source.slice(source.indexOf('function focusNodeByUid('), source.indexOf('function onVersionEditingTransition('))

function harness() {
  const calls = []
  const timers = new Map()
  let nextTimer = 0
  const node = { nodeData: { data: { uid: 'child', expand: false } } }
  const map = {
    renderer: {
      findNodeByUid: uid => uid === 'child' ? node : null,
      moveNodeToCenter: target => calls.push(['center', target]),
    },
    execCommand: (...args) => calls.push(args),
  }
  const scope = {
    mindMap: { value: map }, aiDraftPreviewState: { jobId: 'job1', mindMap: map },
    aiFocusRequestId: 0, aiFocusLastKey: '', aiFocusRetryTimer: null,
    terminalState: '',
    window: {
      clearTimeout: id => timers.delete(id),
      setTimeout: callback => { timers.set(++nextTimer, callback); return nextTimer },
    },
  }
  const api = new Function('scope', `with(scope) { ${focusFunctions}; return { focusNodeByUid, onAiNodeFocus } }`)(scope)
  return { scope, map, node, calls, ...api, drain() {
    const pending = [...timers.values()]
    timers.clear()
    pending.forEach(callback => callback())
  } }
}

test('AI 聚焦只移动视口，不通过导航命令修改云端折叠数据', () => {
  const h = harness()
  h.onAiNodeFocus({ jobId: 'job1', focusKey: 'job1:1:child', nodeUids: ['child'] })
  assert.deepEqual(h.calls, [['center', h.node]])
  assert.equal(h.node.nodeData.data.expand, false)
  h.onAiNodeFocus({ jobId: 'job1', focusKey: 'job1:1:child', nodeUids: ['child'] })
  assert.equal(h.calls.length, 1, 'characters of the same node must not repeatedly pan')
})

test('普通导航仍可使用 GO_TARGET_NODE，旧任务事件不能移动当前画布', () => {
  const h = harness()
  h.onAiNodeFocus({ jobId: 'old', nodeUids: ['child'] })
  assert.equal(h.calls.length, 0)
  assert.equal(h.focusNodeByUid('child'), true)
  assert.deepEqual(h.calls, [['GO_TARGET_NODE', 'child']])
})

test('等待布局期间会话交接或画布替换会使旧聚焦失效', () => {
  for (const replaceMap of [false, true]) {
    const h = harness()
    h.map.renderer.isRendering = true
    h.onAiNodeFocus({ jobId: 'job1', nodeUids: ['child'] })
    h.map.renderer.isRendering = false
    if (replaceMap) h.scope.mindMap.value = { ...h.map }
    else h.scope.aiDraftPreviewState = { jobId: 'job2', mindMap: h.map }
    h.drain()
    assert.equal(h.calls.length, 0)
  }
})
