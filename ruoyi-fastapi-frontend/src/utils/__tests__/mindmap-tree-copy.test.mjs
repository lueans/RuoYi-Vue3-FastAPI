import assert from 'node:assert/strict'
import test from 'node:test'

import { copyTreeIterative } from '../../libs/simple-mind-map/src/utils/treeCopy.js'

const cloneData = value => structuredClone(value)

test('iterative tree copy preserves order, clones data and filters runtime fields', () => {
  const source = {
    data: { uid: 'root', nested: { value: 1 } },
    layout: 'mindMap',
    _runtime: 'ignored',
    children: [
      { data: { uid: 'left' }, children: [] },
      { data: { uid: 'right' }, children: [] }
    ]
  }

  const target = { existing: true }
  const copied = copyTreeIterative({ target, root: source, cloneData })

  assert.equal(copied, target)
  assert.deepEqual(copied, {
    existing: true,
    data: { uid: 'root', nested: { value: 1 } },
    children: [
      { data: { uid: 'left' }, children: [] },
      { data: { uid: 'right' }, children: [] }
    ],
    layout: 'mindMap'
  })
  assert.notEqual(copied.data, source.data)
  assert.notEqual(copied.data.nested, source.data.nested)
})

test('iterative tree copy supports wrapped node data and data transforms', () => {
  const fallbackChild = {
    data: { uid: 'fallback', isActive: true },
    children: []
  }
  const root = {
    nodeData: {
      data: { uid: 'root', isActive: true },
      custom: 'kept',
      _cache: 'ignored',
      children: [fallbackChild]
    },
    children: []
  }

  const copied = copyTreeIterative({
    target: {},
    root,
    cloneData,
    resolveNode: node => {
      const dataSource = node.nodeData || node
      return {
        dataSource,
        children: node.children?.length ? node.children : dataSource.children
      }
    },
    transformData: data => {
      delete data.uid
      data.isActive = false
      return data
    }
  })

  assert.deepEqual(copied, {
    data: { isActive: false },
    children: [{ data: { isActive: false }, children: [] }],
    custom: 'kept'
  })
})

test('iterative tree copy terminates cycles and keeps shared objects once', () => {
  const shared = { data: { uid: 'shared' }, children: [] }
  const left = { data: { uid: 'left' }, children: [shared] }
  const right = { data: { uid: 'right' }, children: [shared] }
  const root = { data: { uid: 'root' }, children: [left, right] }
  shared.children.push(root)

  const copied = copyTreeIterative({ target: {}, root, cloneData })

  assert.equal(copied.children[0].children[0].data.uid, 'shared')
  assert.deepEqual(copied.children[0].children[0].children, [])
  assert.deepEqual(copied.children[1].children, [])
})

test('iterative tree copy handles a 20,000-level history snapshot', () => {
  const root = { data: { uid: 'node-0' }, children: [] }
  let current = root
  for (let index = 1; index < 20_000; index += 1) {
    const child = { data: { uid: `node-${index}` }, children: [] }
    current.children.push(child)
    current = child
  }

  const copied = copyTreeIterative({ target: {}, root, cloneData })
  let count = 0
  current = copied
  while (current) {
    count += 1
    current = current.children[0]
  }
  assert.equal(count, 20_000)
})
