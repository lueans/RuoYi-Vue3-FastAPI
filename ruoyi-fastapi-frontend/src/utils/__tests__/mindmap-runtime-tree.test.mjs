import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  renderRuntimeTreeSync,
  visitRuntimeSubtree
} from '../../libs/simple-mind-map/src/utils/runtimeTree.js'

const createNode = (uid, children = [], expand = true) => ({
  uid,
  children,
  getData(key) {
    return key === 'expand' ? expand : undefined
  }
})

test('synchronous runtime rendering is stable, collapse-aware and cycle-safe', () => {
  const shared = createNode('shared')
  const hidden = createNode('hidden')
  const collapsed = createNode('collapsed', [hidden], false)
  const a = createNode('a', [shared])
  const b = createNode('b', [shared])
  const root = createNode('root', [a, b, collapsed])
  root.children.push(root)

  const events = []
  renderRuntimeTreeSync(
    root,
    node => events.push(`render:${node.uid}`),
    node => events.push(`finish:${node.uid}`),
    () => events.push('complete')
  )

  assert.deepEqual(events, [
    'render:root',
    'render:a',
    'render:shared',
    'render:b',
    'render:collapsed',
    'complete',
    'finish:shared',
    'finish:a',
    'finish:b',
    'finish:collapsed',
    'finish:root'
  ])
})

test('runtime teardown preserves preorder and prunes nodes rejected by the visitor', () => {
  const a1 = createNode('a-1')
  const a = createNode('a', [a1])
  const hidden = createNode('hidden')
  const absent = createNode('absent', [hidden])
  const root = createNode('root', [a, absent, a])
  root.children.push(root)

  const visited = []
  visitRuntimeSubtree(root, node => {
    visited.push(node.uid)
    return node.uid !== 'absent'
  })

  assert.deepEqual(visited, ['root', 'a', 'a-1', 'absent'])
})

test('runtime render and teardown complete a 20,000-level tree without recursion', () => {
  const root = createNode('0')
  let current = root
  for (let index = 1; index < 20_000; index += 1) {
    const child = createNode(String(index))
    current.children.push(child)
    current = child
  }

  let rendered = 0
  let finished = 0
  let completedBeforeFinish = false
  renderRuntimeTreeSync(
    root,
    () => {
      rendered += 1
    },
    () => {
      finished += 1
    },
    () => {
      completedBeforeFinish = finished === 0
    }
  )

  let removed = 0
  visitRuntimeSubtree(root, () => {
    removed += 1
  })

  assert.equal(rendered, 20_000)
  assert.equal(finished, 20_000)
  assert.equal(removed, 20_000)
  assert.equal(completedBeforeFinish, true)
})

test('MindMapNode and RichText use the shared iterative traversal paths', async () => {
  const [nodeSource, richTextSource] = await Promise.all([
    readFile(
      new URL(
        '../../libs/simple-mind-map/src/core/render/node/MindMapNode.js',
        import.meta.url
      ),
      'utf8'
    ),
    readFile(
      new URL(
        '../../libs/simple-mind-map/src/plugins/RichText.js',
        import.meta.url
      ),
      'utf8'
    )
  ])

  assert.match(nodeSource, /renderRuntimeTreeSync\(/)
  assert.match(nodeSource, /visitRuntimeSubtree\(/)
  assert.doesNotMatch(richTextSource, /const walk = root =>/)
  assert.match(richTextSource, /walk\(\s*data,\s*null,/)
})
