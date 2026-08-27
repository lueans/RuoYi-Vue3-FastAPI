import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  createMindmapCreationAttemptTracker,
  extractCreatedMindmapId,
  resolveCreatedMindmapNavigation,
} from '../mindmap-creation.js'

function memoryStorage() {
  const values = new Map()
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  }
}

test('不确定失败和同标签页刷新会复用同一个创建幂等键', () => {
  const storage = memoryStorage()
  let generated = 0
  const options = {
    storage,
    storageKey: 'creation-test',
    createKey: () => `request-key-${++generated}-123456`,
    now: () => 1000,
  }
  const firstTracker = createMindmapCreationAttemptTracker(options)
  const first = firstTracker.begin('{"name":"规划"}')
  firstTracker.invalidate()
  const retried = firstTracker.begin('{"name":"规划"}')
  const afterRefresh = createMindmapCreationAttemptTracker(options)
    .begin('{"name":"规划"}')

  assert.equal(retried.idempotencyKey, first.idempotencyKey)
  assert.equal(afterRefresh.idempotencyKey, first.idempotencyKey)
  assert.equal(generated, 1)
})

test('创建意图变化生成新键且成功确认只清理对应尝试', () => {
  const storage = memoryStorage()
  let generated = 0
  const tracker = createMindmapCreationAttemptTracker({
    storage,
    storageKey: 'creation-test',
    createKey: () => `request-key-${++generated}-123456`,
    now: () => 1000,
  })
  const abandoned = tracker.begin('template:1')
  const current = tracker.begin('template:2')

  assert.notEqual(current.idempotencyKey, abandoned.idempotencyKey)
  assert.equal(tracker.complete(abandoned), false)
  assert.equal(tracker.complete(current), true)
  assert.equal(storage.getItem('creation-test'), null)
})

test('过期的未决创建尝试不会被继续复用', () => {
  const storage = memoryStorage()
  storage.setItem('creation-test', JSON.stringify({
    version: 1,
    intent: 'template:1',
    idempotencyKey: 'expired-request-key',
    createdAt: 1000,
  }))
  const tracker = createMindmapCreationAttemptTracker({
    storage,
    storageKey: 'creation-test',
    createKey: () => 'fresh-request-key-123456',
    now: () => 5000,
    maxAgeMs: 100,
  })

  assert.equal(tracker.begin('template:1').idempotencyKey, 'fresh-request-key-123456')
})

test('创建结果取得有效 ID 后只导航一次并返回明确成功态', async () => {
  const openedIds = []
  const result = await resolveCreatedMindmapNavigation({
    response: { data: { id: 88 } },
    navigate: async id => { openedIds.push(id) },
  })

  assert.deepEqual(openedIds, [88])
  assert.deepEqual(result, {
    created: true,
    opened: true,
    mindmapId: 88,
    reason: null,
    error: null,
  })
})

test('创建已提交但缺少 ID 时不会尝试导航或伪报创建失败', async () => {
  let navigated = false
  const result = await resolveCreatedMindmapNavigation({
    response: { data: {} },
    navigate: async () => { navigated = true },
  })

  assert.equal(navigated, false)
  assert.equal(result.created, true)
  assert.equal(result.opened, false)
  assert.equal(result.reason, 'missing-id')
  assert.match(result.error.message, /已创建.*未返回有效文件 ID/)
})

test('创建后的导航失败保留文件 ID并与创建失败分离', async () => {
  const navigationError = new Error('router unavailable')
  const result = await resolveCreatedMindmapNavigation({
    response: { data: { id: '102' } },
    navigate: async () => { throw navigationError },
  })

  assert.equal(result.created, true)
  assert.equal(result.opened, false)
  assert.equal(result.mindmapId, 102)
  assert.equal(result.reason, 'navigation-failed')
  assert.equal(result.error, navigationError)
  assert.equal(extractCreatedMindmapId({ data: { id: 102 } }), 102)
})

test('创建请求返回前页面失效时保留已创建资源但不强制导航', async () => {
  let navigated = false
  const result = await resolveCreatedMindmapNavigation({
    response: { data: { id: 120 } },
    isCurrent: () => false,
    navigate: async () => { navigated = true },
  })

  assert.equal(navigated, false)
  assert.equal(result.created, true)
  assert.equal(result.opened, false)
  assert.equal(result.reason, 'session-stale')
})

test('路由守卫以已解决的导航失败对象返回时仍不能伪报已打开', async () => {
  const navigationFailure = new Error('navigation aborted')
  const result = await resolveCreatedMindmapNavigation({
    response: { data: { id: 121 } },
    navigate: async () => navigationFailure,
  })

  assert.equal(result.created, true)
  assert.equal(result.opened, false)
  assert.equal(result.mindmapId, 121)
  assert.equal(result.reason, 'navigation-failed')
  assert.equal(result.error, navigationFailure)
})

test('列表新建流程把服务端创建与后续导航分成独立结果阶段', async () => {
  const source = await readFile(
    new URL('../../views/mindmap/index.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /response = await addMindmap\(mindmapData, creationRequestId\.idempotencyKey\)/)
  assert.match(source, /creationRequests\.complete\(creationRequestId\)/)
  assert.match(source, /resolveCreatedMindmapNavigation\(\{/)
  assert.match(source, /navigate: mindmapId => router\.push\(\{[\s\S]*returnList: getListReturnState\(\)/)
  assert.match(source, /creationRequests\.isCurrent\(creationRequestId\)/)
  assert.match(source, /navigation\.reason === 'session-stale'/)
  assert.match(source, /脑图已创建，但未能自动打开/)
})

test('新建、复制与导入 API 把服务端幂等键作为显式协议发送', async () => {
  const mindmapApi = await readFile(
    new URL('../../api/mindmap/mindmap.js', import.meta.url),
    'utf8',
  )

  assert.match(mindmapApi, /'Idempotency-Key': idempotencyKey/)
  assert.match(mindmapApi, /repeatSubmit: false/)
  assert.match(mindmapApi, /export function copyMindmap\(mindmapId, idempotencyKey\)/)
  assert.match(mindmapApi, /export function importMindmap\(data, idempotencyKey\)/)
})

test('列表复制复用创建尝试跟踪器并在确认成功后清理', async () => {
  const source = await readFile(
    new URL('../../views/mindmap/index.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /creationRequests\.begin\(`copy:\$\{row\.id\}`\)/)
  assert.match(source, /copyMindmap\(row\.id, creationRequest\.idempotencyKey\)/)
  assert.match(source, /creationRequests\.complete\(creationRequest\)/)
})
