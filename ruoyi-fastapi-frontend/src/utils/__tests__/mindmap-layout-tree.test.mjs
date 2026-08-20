import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  calculateNodeAreaHeight,
  calculateNodeAreaWidth,
  calculateNodeBoundaries,
  updateDescendantNodes,
  walkLayoutAncestorChain
} from '../../libs/simple-mind-map/src/layouts/layoutTree.js'

const createLayoutNode = (overrides = {}) => ({
  left: 0,
  top: 0,
  width: 10,
  height: 10,
  expandBtnSize: 2,
  layerIndex: 0,
  _generalizationNodeWidth: 0,
  _generalizationNodeHeight: 0,
  children: [],
  checkHasGeneralization() {
    return this._generalizationNodeWidth > 0 || this._generalizationNodeHeight > 0
  },
  getData(key) {
    return key === 'expand' ? true : undefined
  },
  hasCustomPosition() {
    return false
  },
  ...overrides
})

test('subtree updates preserve order, stop below custom positions and terminate cycles', () => {
  const blockedChild = createLayoutNode({ left: 3 })
  const blocked = createLayoutNode({
    left: 2,
    children: [blockedChild],
    hasCustomPosition() {
      return true
    }
  })
  const normal = createLayoutNode({ left: 1 })
  const root = createLayoutNode({ children: [normal, blocked] })
  normal.children.push(root)

  const order = []
  updateDescendantNodes(root.children, node => {
    order.push(node)
    node.left += 5
  }, node => !node.hasCustomPosition())

  assert.deepEqual(order, [normal, root, blocked])
  assert.equal(normal.left, 6)
  assert.equal(root.left, 5)
  assert.equal(blocked.left, 7)
  assert.equal(blockedChild.left, 3)
})

test('node area width preserves path and generalization calculations', () => {
  const leaf = createLayoutNode({ width: 6 })
  const child = createLayoutNode({
    width: 8,
    _generalizationNodeWidth: 3,
    children: [leaf]
  })
  const root = createLayoutNode({
    width: 10,
    _generalizationNodeWidth: 2,
    children: [child]
  })

  assert.equal(calculateNodeAreaWidth(root, false), 15)
  assert.equal(calculateNodeAreaWidth(root, true), 20)
})

test('node boundaries preserve postorder generalization expansion', () => {
  const grandchild = createLayoutNode({ left: 30, top: 30, width: 5, height: 5 })
  const child = createLayoutNode({
    left: 20,
    top: 10,
    width: 10,
    height: 10,
    _generalizationNodeWidth: 4,
    _generalizationNodeHeight: 6,
    children: [grandchild]
  })
  const root = createLayoutNode({ children: [child] })

  assert.deepEqual(calculateNodeBoundaries(root, 'h', 1), {
    left: 0,
    right: 40,
    top: 0,
    bottom: 35
  })
  assert.deepEqual(calculateNodeBoundaries(root, 'v', 1), {
    left: 0,
    right: 35,
    top: 0,
    bottom: 42
  })
})

test('layout metrics handle a 20,000-level tree without recursion', () => {
  const root = createLayoutNode()
  let current = root
  for (let index = 1; index < 20_000; index += 1) {
    const child = createLayoutNode({ layerIndex: index })
    current.children.push(child)
    current = child
  }

  assert.equal(calculateNodeAreaWidth(root), 100_005)
  assert.equal(
    calculateNodeAreaHeight(root, node => node.children.length, () => 1),
    259_998
  )
  assert.deepEqual(calculateNodeBoundaries(root, 'h', 1), {
    left: 0,
    right: 10,
    top: 0,
    bottom: 10
  })
})

test('layout ancestor propagation is ordered, stoppable and cycle safe', () => {
  const root = { uid: 'root', parent: null }
  const parent = { uid: 'parent', parent: root }
  const child = { uid: 'child', parent }
  const order = []

  walkLayoutAncestorChain(child, node => {
    order.push(node.uid)
  })
  assert.deepEqual(order, ['child', 'parent'])

  order.length = 0
  root.parent = child
  walkLayoutAncestorChain(child, node => {
    order.push(node.uid)
  }, () => true)
  assert.deepEqual(order, ['child', 'parent', 'root'])

  order.length = 0
  walkLayoutAncestorChain(child, node => {
    order.push(node.uid)
    return node.uid === 'parent' ? false : undefined
  }, () => true)
  assert.deepEqual(order, ['child', 'parent'])
})

test('layout ancestor propagation handles a 20,000-level parent chain', () => {
  const root = { parent: null }
  let current = root
  for (let index = 1; index < 20_000; index += 1) {
    current = { parent: current }
  }

  let count = 0
  walkLayoutAncestorChain(current, () => {
    count += 1
  }, () => true)
  assert.equal(count, 20_000)
})

test('all layouts use the shared iterative ancestor propagation path', async () => {
  const layoutNames = [
    'LogicalStructure',
    'CatalogOrganization',
    'MindMap',
    'OrganizationStructure',
    'Timeline',
    'Fishbone',
    'VerticalTimeline'
  ]
  const sources = await Promise.all(layoutNames.map(name => readFile(
    new URL(
      `../../libs/simple-mind-map/src/layouts/${name}.js`,
      import.meta.url
    ),
    'utf8'
  )))

  sources.forEach(source => {
    assert.match(source, /walkLayoutAncestorChain/)
    assert.doesNotMatch(
      source,
      /this\.(?:updateBrothers|updateBrothersLeft|updateBrothersTop)\(\s*(?:node|current)\.parent/
    )
  })
  assert.equal(
    sources.reduce(
      (total, source) => total + (source.match(/walkLayoutAncestorChain\(/g) || []).length,
      0
    ),
    9
  )
})
