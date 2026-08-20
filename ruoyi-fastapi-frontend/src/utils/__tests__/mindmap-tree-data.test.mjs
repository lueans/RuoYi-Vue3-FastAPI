import assert from 'node:assert/strict'
import test from 'node:test'

import {
  materializeObjectSubtree,
  transformObjectMapToTree,
  transformTreeDataToObject
} from '../../libs/simple-mind-map/src/utils/treeData.js'

const cloneData = value => structuredClone(value)

test('tree collaboration conversion preserves ordered structure and data', () => {
  const source = {
    data: { uid: 'root', text: 'Root' },
    children: [
      {
        data: { uid: 'left', text: 'Left' },
        children: [{ data: { uid: 'leaf', text: 'Leaf' }, children: [] }]
      },
      { data: { uid: 'right', text: 'Right' }, children: [] }
    ]
  }

  const flat = transformTreeDataToObject(source)
  assert.deepEqual(flat.root.children, ['left', 'right'])
  assert.deepEqual(flat.left.children, ['leaf'])
  assert.equal(flat.root.isRoot, true)
  assert.equal(flat.left.isRoot, false)
  const restored = transformObjectMapToTree(flat, cloneData)
  assert.deepEqual(restored, source)
  assert.notEqual(restored.data, flat.root.data)
  restored.data.text = 'Changed'
  assert.equal(flat.root.data.text, 'Root')
})

test('object collaboration conversion ignores missing, repeated and cyclic links', () => {
  const flat = {
    root: {
      isRoot: true,
      data: { uid: 'root' },
      children: ['left', 'missing', 'right']
    },
    left: {
      isRoot: false,
      data: { uid: 'left' },
      children: ['shared']
    },
    right: {
      isRoot: false,
      data: { uid: 'right' },
      children: ['shared']
    },
    shared: {
      isRoot: false,
      data: { uid: 'shared' },
      children: ['root']
    },
    orphan: {
      isRoot: false,
      data: { uid: 'orphan' },
      children: []
    }
  }

  const tree = transformObjectMapToTree(flat, cloneData)
  assert.deepEqual(tree, {
    data: { uid: 'root' },
    children: [
      {
        data: { uid: 'left' },
        children: [{ data: { uid: 'shared' }, children: [] }]
      },
      { data: { uid: 'right' }, children: [] }
    ]
  })
  assert.equal(transformObjectMapToTree({}, cloneData), null)
  assert.equal(
    transformObjectMapToTree({ lone: { data: {}, children: [] } }, cloneData),
    null
  )
})

test('tree collaboration conversion handles a 20,000-level chain iteratively', () => {
  const root = { data: { uid: 'node-0' }, children: [] }
  let current = root
  for (let index = 1; index < 20_000; index += 1) {
    const child = { data: { uid: `node-${index}` }, children: [] }
    current.children.push(child)
    current = child
  }

  const flat = transformTreeDataToObject(root)
  const restored = transformObjectMapToTree(flat, cloneData)
  assert.equal(Object.keys(flat).length, 20_000)

  let restoredCount = 0
  current = restored
  while (current) {
    restoredCount += 1
    current = current.children[0]
  }
  assert.equal(restoredCount, 20_000)
})

test('object collaboration conversion restores a 20,000-node wide tree', () => {
  const flat = {
    root: {
      isRoot: true,
      data: { uid: 'root' },
      children: []
    }
  }
  for (let index = 0; index < 20_000; index += 1) {
    const uid = `child-${index}`
    flat.root.children.push(uid)
    flat[uid] = { isRoot: false, data: { uid }, children: [] }
  }

  const tree = transformObjectMapToTree(flat, cloneData)
  assert.equal(tree.children.length, 20_000)
  assert.equal(tree.children[0].data.uid, 'child-0')
  assert.equal(tree.children.at(-1).data.uid, 'child-19999')
})

test('history subtree materialization is ordered, immutable and cycle safe', () => {
  const flat = {
    root: {
      isRoot: true,
      data: { uid: 'root' },
      children: ['left', 'missing', 'right']
    },
    left: {
      isRoot: false,
      data: { uid: 'left' },
      children: ['shared']
    },
    right: {
      isRoot: false,
      data: { uid: 'right' },
      children: ['shared']
    },
    shared: {
      isRoot: false,
      data: { uid: 'shared' },
      children: ['root']
    }
  }
  const originalChildren = flat.root.children.slice()

  const subtree = materializeObjectSubtree(flat, 'root')

  assert.deepEqual(subtree.children.map(node => node.data.uid), ['left', 'right'])
  assert.equal(subtree.children[0].children[0].data.uid, 'shared')
  assert.deepEqual(subtree.children[0].children[0].children, [])
  assert.deepEqual(subtree.children[1].children, [])
  assert.deepEqual(flat.root.children, originalChildren)
  assert.equal(materializeObjectSubtree(flat, 'missing'), null)
})

test('history subtree materialization handles a 20,000-level chain', () => {
  const flat = {}
  for (let index = 0; index < 20_000; index += 1) {
    const uid = `node-${index}`
    flat[uid] = {
      isRoot: index === 0,
      data: { uid },
      children: index < 19_999 ? [`node-${index + 1}`] : []
    }
  }

  const subtree = materializeObjectSubtree(flat, 'node-0')
  let count = 0
  let current = subtree
  while (current) {
    count += 1
    current = current.children[0]
  }
  assert.equal(count, 20_000)
})
