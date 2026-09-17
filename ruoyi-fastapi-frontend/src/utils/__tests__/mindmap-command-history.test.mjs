import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { applyNodeDataBatch } from '../../libs/simple-mind-map/src/utils/nodeDataBatch.js'

const commandUrl = new URL(
  '../../libs/simple-mind-map/src/core/command/Command.js',
  import.meta.url,
)
const timingUrl = new URL(
  '../../libs/simple-mind-map/src/utils/timing.js',
  import.meta.url,
)

async function loadCommand() {
  const source = await readFile(commandUrl, 'utf8')
  const executableSource = source
    .replace(
      /import \{[\s\S]*?\} from '\.\.\/\.\.\/utils'\n/,
      `import { throttle } from ${JSON.stringify(timingUrl.href)}
const copyRenderTree = (_target, root) => structuredClone(root)
const isSameObject = (left, right) => JSON.stringify(left) === JSON.stringify(right)
const transformTreeDataToObject = (root) => {
  const result = {}
  const pending = root ? [root] : []
  while (pending.length > 0) {
    const node = pending.pop()
    const uid = node?.data?.uid
    if (uid) result[uid] = structuredClone(node)
    for (const child of (Array.isArray(node?.children) ? node.children : [])) pending.push(child)
  }
  return result
}
const materializeObjectSubtree = (nodes, uid) => structuredClone(nodes[uid])
const stringifyJsonValueIterative = value => JSON.stringify(value)
`,
    )
    .replace(
      "import { ERROR_TYPES } from '../../constants/constant'",
      "const ERROR_TYPES = { DATA_CHANGE_DETAIL_EVENT_ERROR: 'data-change-detail-error' }",
    )
    .replace(
      "import pkg from '../../../package.json'",
      "const pkg = { version: 'test' }",
    )
    .replace(
      "import { trimHistoryEntries } from '../../utils/historyBuffer'",
      'const trimHistoryEntries = entries => entries',
    )
  const moduleUrl = `data:text/javascript;base64,${Buffer.from(executableSource).toString('base64')}`
  return (await import(moduleUrl)).default
}

function createMindMap(addHistoryTime = 20) {
  const emitted = []
  const mindMap = {
    opt: {
      readonly: false,
      addHistoryTime,
      maxHistoryCount: 100,
      maxHistoryMemoryBytes: Infinity,
      errorHandler(_type, error) { throw error },
    },
    keyCommand: { addShortcut() {} },
    renderer: {
      renderTree: {
        data: { uid: 'root', text: 'before' },
        children: [],
      },
    },
    event: {
      listenerCount(eventName) {
        return eventName === 'data_change_detail' ? 1 : 0
      },
    },
    emit(eventName, ...args) {
      emitted.push({ eventName, args })
    },
  }
  return { emitted, mindMap }
}

const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))

test('flushPendingHistory synchronously commits the real throttled history task once', async () => {
  const Command = await loadCommand()
  const { emitted, mindMap } = createMindMap()
  const command = new Command({ mindMap })
  assert.equal(command.resetHistoryBaseline(), true)
  emitted.length = 0

  mindMap.renderer.renderTree.data.text = 'DOM-only final text'
  command.addHistory()
  assert.equal(emitted.some(item => item.eventName === 'data_change'), false)

  assert.equal(command.flushPendingHistory(), true)
  assert.equal(emitted.filter(item => item.eventName === 'data_change').length, 1)
  const [detail] = emitted.find(item => item.eventName === 'data_change_detail').args
  assert.equal(detail[0].oldData.data.text, 'before')
  assert.equal(detail[0].data.data.text, 'DOM-only final text')

  await wait(60)
  assert.equal(emitted.filter(item => item.eventName === 'data_change').length, 1)
  assert.equal(command.flushPendingHistory(), false)
})

test('resetHistoryBaseline cancels the timer and keeps a silent baseline for the next edit', async () => {
  const Command = await loadCommand()
  const { emitted, mindMap } = createMindMap()
  const command = new Command({ mindMap })
  assert.equal(command.resetHistoryBaseline(), true)

  mindMap.renderer.renderTree.data.text = 'authoritative text'
  command.addHistory()
  emitted.length = 0
  assert.equal(command.resetHistoryBaseline(), true)
  assert.equal(command.history.length, 1)
  assert.equal(JSON.parse(command.history[0]).data.text, 'authoritative text')
  assert.equal(emitted.some(item => item.eventName === 'data_change'), false)
  assert.equal(emitted.some(item => item.eventName === 'data_change_detail'), false)

  await wait(60)
  assert.equal(emitted.some(item => item.eventName === 'data_change'), false)

  mindMap.renderer.renderTree.data.text = 'next local edit'
  command.addHistory()
  assert.equal(command.flushPendingHistory(), true)
  const [detail] = emitted.find(item => item.eventName === 'data_change_detail').args
  assert.equal(detail[0].oldData.data.text, 'authoritative text')
  assert.equal(detail[0].data.data.text, 'next local edit')

  mindMap.renderer.renderTree = null
  emitted.length = 0
  assert.equal(command.resetHistoryBaseline(), false)
  assert.deepEqual(command.history, [])
  assert.equal(command.activeHistoryIndex, 0)
  assert.equal(emitted.some(item => item.eventName === 'data_change'), false)
  assert.equal(emitted.some(item => item.eventName === 'data_change_detail'), false)
})

test('clearHistory also cancels an older throttled snapshot', async () => {
  const Command = await loadCommand()
  const { emitted, mindMap } = createMindMap()
  const command = new Command({ mindMap })
  command.resetHistoryBaseline()
  emitted.length = 0

  mindMap.renderer.renderTree.data.text = 'must not return after clear'
  command.addHistory()
  command.clearHistory()
  await wait(60)

  assert.deepEqual(command.history, [])
  assert.equal(emitted.some(item => item.eventName === 'data_change'), false)
  assert.equal(emitted.some(item => item.eventName === 'data_change_detail'), false)
})

test('setData-style history initialization emits no tree detail for an imported root', async () => {
  const Command = await loadCommand()
  const { emitted, mindMap } = createMindMap()
  const command = new Command({ mindMap })
  command.resetHistoryBaseline()
  emitted.length = 0

  // MindMap.setData clears history, queues the new baseline, and only then
  // swaps renderer.renderTree. This intentionally emits data_change but has no
  // previous entry from which data_change_detail could describe the new tree.
  command.clearHistory()
  command.addHistory()
  mindMap.renderer.renderTree = {
    data: { uid: 'imported-root', text: 'imported' },
    children: [{ data: { uid: 'imported-child', text: 'child' }, children: [] }],
  }
  assert.equal(command.flushPendingHistory(), true)

  assert.equal(emitted.filter(item => item.eventName === 'data_change').length, 1)
  assert.equal(emitted.some(item => item.eventName === 'data_change_detail'), false)
  assert.equal(JSON.parse(command.history[0]).data.uid, 'imported-root')
})

test('AI 整图替换作为一条历史记录接回原撤销链', async () => {
  const Command = await loadCommand()
  const { mindMap } = createMindMap()
  const command = new Command({ mindMap })
  command.resetHistoryBaseline()
  const state = command.captureHistoryState()

  command.clearHistory()
  mindMap.renderer.renderTree = {
    data: { uid: 'ai-root', text: 'AI result' },
    children: [],
  }
  command.resetHistoryBaseline()
  assert.equal(command.appendCurrentToHistoryState(state), true)

  assert.equal(command.history.length, 2)
  assert.equal(JSON.parse(command.history[0]).data.text, 'before')
  assert.equal(JSON.parse(command.history[1]).data.text, 'AI result')
  assert.equal(command.back().data.text, 'before')
})

test('AI 仅修改布局或文档元数据时仍强制建立唯一撤销单元', async () => {
  const Command = await loadCommand()
  const { mindMap } = createMindMap()
  const command = new Command({ mindMap })
  command.resetHistoryBaseline()
  const state = command.captureHistoryState()

  // Renderer tree is intentionally identical: full-document metadata lives
  // outside Command history, but the editor keeps its complete baseline next
  // to this forced marker.
  command.clearHistory()
  command.resetHistoryBaseline()
  assert.equal(command.appendCurrentToHistoryState(state, { force: true }), true)
  assert.equal(command.history.length, 2)
  assert.equal(command.activeHistoryIndex, 1)
  assert.equal(command.back().data.text, 'before')
  assert.equal(command.activeHistoryIndex, 0)
})

test('command execution guard blocks BACK before renderer history mutates', async () => {
  const Command = await loadCommand()
  const { mindMap } = createMindMap()
  const command = new Command({ mindMap })
  command.resetHistoryBaseline()
  mindMap.renderer.renderTree.data.text = 'AI result'
  command.addHistory()
  command.flushPendingHistory()
  const historyIndex = command.activeHistoryIndex
  let rendererBackCalls = 0
  command.add('BACK', () => { rendererBackCalls += 1 })
  assert.equal(command.addExecutionGuard(name => name !== 'BACK'), true)

  assert.equal(command.exec('BACK'), false)
  assert.equal(rendererBackCalls, 0)
  assert.equal(command.activeHistoryIndex, historyIndex)
  assert.equal(JSON.parse(command.history[historyIndex]).data.text, 'AI result')
})

test('sparse node batch is committed as exactly one undo unit', async () => {
  const Command = await loadCommand()
  const { emitted, mindMap } = createMindMap()
  const command = new Command({ mindMap })
  command.resetHistoryBaseline()
  emitted.length = 0
  const rootNode = { nodeData: { data: mindMap.renderer.renderTree.data } }
  command.add('SET_NODE_DATA_BATCH', updates => applyNodeDataBatch(updates))

  command.exec('SET_NODE_DATA_BATCH', [{
    node: rootNode,
    patch: { customPriority: 'P1' },
  }])
  assert.equal(command.flushPendingHistory(), true)
  assert.equal(command.history.length, 2)
  assert.equal(emitted.filter(item => item.eventName === 'data_change').length, 1)
  assert.equal(command.back().data.customPriority, undefined)
})
