import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { createAsyncRenderSession } from '../../libs/simple-mind-map/src/utils/asyncRenderSession.js'
import { debounce, throttle } from '../../libs/simple-mind-map/src/utils/timing.js'

const createScheduler = () => {
  let nextId = 1
  const tasks = new Map()
  return {
    tasks,
    setTimer(task) {
      const id = nextId
      nextId += 1
      tasks.set(id, task)
      return id
    },
    clearTimer(id) {
      tasks.delete(id)
    },
    run(id) {
      const task = tasks.get(id)
      tasks.delete(id)
      task?.()
    }
  }
}

test('异步渲染会话跟踪任务并在执行后释放句柄', () => {
  const scheduler = createScheduler()
  const session = createAsyncRenderSession(scheduler)
  const calls = []

  assert.equal(session.schedule(() => calls.push('first')), true)
  assert.equal(session.schedule(() => calls.push('second')), true)
  assert.equal(session.pendingCount(), 2)

  scheduler.run(1)
  scheduler.run(2)
  assert.deepEqual(calls, ['first', 'second'])
  assert.equal(session.pendingCount(), 0)
  assert.equal(session.isActive(), true)
})

test('取消异步渲染会话会清除全部任务且保持幂等', () => {
  const scheduler = createScheduler()
  const session = createAsyncRenderSession(scheduler)
  let calls = 0

  session.schedule(() => {
    calls += 1
  })
  session.schedule(() => {
    calls += 1
  })
  session.cancel()
  session.cancel()

  assert.equal(session.isActive(), false)
  assert.equal(session.pendingCount(), 0)
  assert.equal(scheduler.tasks.size, 0)
  assert.equal(session.schedule(() => {
    calls += 1
  }), false)
  assert.equal(calls, 0)
})

test('异步渲染会话只认领运行时节点的首次可达位置', () => {
  const session = createAsyncRenderSession()
  const root = {}
  const child = {}

  assert.equal(session.claim(root), true)
  assert.equal(session.claim(child), true)
  assert.equal(session.claim(root), false)
  assert.equal(session.claim(child), false)
  session.cancel()
  assert.equal(session.claim({}), false)
})

test('节流和防抖任务可在实例销毁时取消', async () => {
  let throttleCalls = 0
  let debounceCalls = 0
  const throttled = throttle(() => {
    throttleCalls += 1
  }, 5)
  const debounced = debounce(() => {
    debounceCalls += 1
  }, 5)

  throttled()
  debounced()
  throttled.cancel()
  debounced.cancel()
  await new Promise(resolve => setTimeout(resolve, 15))

  assert.equal(throttleCalls, 0)
  assert.equal(debounceCalls, 0)
  throttled()
  debounced()
  await new Promise(resolve => setTimeout(resolve, 15))
  assert.equal(throttleCalls, 1)
  assert.equal(debounceCalls, 1)
})

test('性能模式节点渲染和 Render 生命周期共用可取消会话', async () => {
  const [nodeSource, renderSource] = await Promise.all([
    readFile(
      new URL(
        '../../libs/simple-mind-map/src/core/render/node/MindMapNode.js',
        import.meta.url
      ),
      'utf8'
    ),
    readFile(
      new URL(
        '../../libs/simple-mind-map/src/core/render/Render.js',
        import.meta.url
      ),
      'utf8'
    )
  ])

  assert.match(nodeSource, /session\.schedule\(renderChild\)/)
  assert.match(nodeSource, /renderSession = null/)
  assert.match(nodeSource, /const children = \[\.\.\.this\.children\]/)
  assert.doesNotMatch(nodeSource, /setTimeout\(renderChild,\s*0\)/)
  assert.match(renderSource, /startPerformanceRender\(\)/)
  assert.match(renderSource, /cancelPerformanceRender\(emitEnd = true\)/)
  assert.match(renderSource, /this\.mindMap\.on\('beforeDestroy', this\.onBeforeDestroy\)/)
  assert.match(renderSource, /this\.onViewDataChange\?\.cancel\(\)/)
})
