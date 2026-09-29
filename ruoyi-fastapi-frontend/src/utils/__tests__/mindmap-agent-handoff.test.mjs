import test from 'node:test'
import assert from 'node:assert/strict'
import { projectAgentHandoff } from '../mindmap-agent-handoff.js'

const job = { id: 'j1', sessionId: 's1', agentKey: 'claude', executionEpoch: 2, status: 'running' }
const base = { job, ownerId: '7', target: { agentKey: 'device_codex', deviceId: 'd1' },
  agents: [{ agentKey: 'claude', displayName: 'Claude' }, { agentKey: 'device_codex', displayName: 'Codex' }],
  devices: [{ deviceId: 'd1', name: '我的 Mac' }],
  timelineReceipt: { ownerId: '7', sessionId: 's1' },
}
const todo = (sequence, todos, overrides = {}) => ({ jobId: 'j1', sequence, eventType: 'todo_updated', payload: { todos, executionEpoch: 2 }, ...overrides })
const queued = (id, overrides = {}) => ({ job: { ...job, id, status: 'waiting_turn', ...overrides }, userMessage: { content: '补充边界情况' } })

test('handoff uses bound execution identity and distinguishes locations without offline claims', () => {
  const view = projectAgentHandoff(base)
  assert.equal(view.current.name, 'Claude')
  assert.equal(view.current.location, '平台运行主机')
  assert.equal(view.next.location, '我的 Mac')
  assert.match(view.dataNotice, /模型服务/)
  assert.match(view.scope, /未确认/)
  assert.equal(view.queue.known, true)
  assert.equal(view.queue.items.length, 0)
})

test('missing Todo, explicit empty, latest replan and other job/epoch are distinct', () => {
  assert.equal(projectAgentHandoff(base).todo.known, false)
  const events = [todo(1, [{ content: '旧任务', status: 'pending' }]), todo(4, []), todo(99, [{ content: '其他轮', status: 'pending' }], { jobId: 'j2' }), todo(100, [], { payload: { executionEpoch: 1, todos: [] } })]
  const view = projectAgentHandoff({ ...base, events })
  assert.equal(view.todo.known, true)
  assert.equal(view.todo.items.length, 0)
  const replanned = projectAgentHandoff({ ...base, events: [...events, todo(5, [{ content: '完成', status: 'completed' }, { content: '正在检查', status: 'in_progress' }, { content: '未知', status: 'surprise' }])] })
  assert.deepEqual(replanned.todo.items.map(item => item.status), ['in_progress', 'unknown'])
  assert.equal(replanned.todo.current, '正在检查')
})

test('malformed and truncated Todo snapshots never assert zero unfinished work', () => {
  for (const todos of [null, [{ content: 12 }], Array.from({ length: 45 }, () => ({ content: '检查', status: 'completed' }))]) {
    assert.equal(projectAgentHandoff({ ...base, events: [todo(1, todos)] }).todo.complete, false)
  }
})

test('queue includes only confirmed tasks in this session and never the composer draft', () => {
  const turns = [queued('j2'), queued('j3', { agentKey: 'kimi' }), queued('x', { sessionId: 'other' }), queued('j4', { status: 'completed_direct' })]
  const view = projectAgentHandoff({ ...base, turns, draft: '不能自动发送' })
  assert.deepEqual(view.queue.items.map(item => item.id), ['j2', 'j3'])
  assert.equal(view.queue.items[1].agent, 'kimi')
  for (const override of [{ timelineReceipt: null }, { ownerId: '8' }, { timelineLoading: true }, { timelineError: '断网' }]) {
    assert.equal(projectAgentHandoff({ ...base, ...override, turns }).queue.known, false)
  }
})

test('consent changes for task, target or queue consequences, but not streaming Todo/stat growth', () => {
  const initial = projectAgentHandoff(base).consentKey
  for (const change of [{ job: { ...job, executionEpoch: 3 } }, { target: { agentKey: 'kimi' } }, { turns: [queued('j2')] }, { devices: [{ deviceId: 'd1', name: '另一台电脑' }] }]) {
    assert.notEqual(projectAgentHandoff({ ...base, ...change }).consentKey, initial)
  }
  assert.equal(projectAgentHandoff({ ...base, events: [todo(1, [{ content: '继续', status: 'pending' }])], resultState: { title: '保存中', description: '等待回执' } }).consentKey, initial)
})

test('result projection preserves receipt semantics and text is bounded without interpreting HTML', () => {
  const resultState = { title: '保存未完成', description: '未收到回执', canvasNote: '正在同步' }
  const view = projectAgentHandoff({ ...base, resultState, events: [todo(1, [{ content: '<img onerror=alert(1)>' + '字'.repeat(2000), status: 'pending' }])] })
  assert.equal(view.result.title, resultState.title)
  assert.equal(view.result.description, resultState.description)
  assert.match(view.todo.items[0].content, /^<img/)
  assert.ok(view.todo.items[0].content.length <= 501)
  assert.match(projectAgentHandoff({ ...base, job: { ...job, intent: 'discuss' } }).result.title, /讨论/)
})
