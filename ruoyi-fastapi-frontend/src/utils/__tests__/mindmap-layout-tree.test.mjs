import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  balanceTreeChildrenVertically,
  calculateNodeAreaHeight,
  calculateNodeAreaWidth,
  calculateNodeBoundaries,
  calculateUniformSiblingCenterOffsets,
  updateDescendantNodes,
  walkLayoutAncestorChain
} from '../../libs/simple-mind-map/src/layouts/layoutTree.js'
import defaultTheme from '../../libs/simple-mind-map/src/theme/default.js'

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

test('global curve defaults keep bidirectional mind maps on a shared root center', () => {
  assert.equal(defaultTheme.rootLineKeepSameInCurve, true)
  assert.equal(defaultTheme.rootLineStartPositionKeepSameInCurve, false)
})

test('logical structures always use the ordinary cubic edge anchor', async () => {
  const [layoutSource, configSource] = await Promise.all([
    readFile(new URL(
      '../../libs/simple-mind-map/src/layouts/LogicalStructure.js',
      import.meta.url
    ), 'utf8'),
    readFile(new URL(
      '../../components/MindMap/config/index.js',
      import.meta.url
    ), 'utf8')
  ])
  const supportedLayouts = configSource.match(
    /supportRootLineKeepSameInCurveLayouts\s*=\s*\[([\s\S]*?)\]/
  )?.[1] || ''

  assert.doesNotMatch(layoutSource, /rootLineStartPositionKeepSameInCurve/)
  assert.doesNotMatch(layoutSource, /rootLineKeepSameInCurve/)
  assert.match(layoutSource, /x1 = left \+ width \+ expandBtnSize/)
  assert.match(layoutSource, /path = this\.cubicBezierPath\(x1, y1, x2, y2\)/)
  assert.doesNotMatch(supportedLayouts, /logicalStructure/)
  assert.match(supportedLayouts, /mindMap/)
  assert.match(supportedLayouts, /organizationStructure/)
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

test('uniform sibling centers use the minimum safe equal interval', () => {
  const offsets = calculateUniformSiblingCenterOffsets([
    { topOffset: -20, bottomOffset: 20 },
    { topOffset: -230, bottomOffset: 230 }
  ], 20)

  assert.deepEqual(offsets, [-135, 135])
  assert.equal(offsets[1] - offsets[0], 270)
})

test('balanced vertical layout keeps unequal subtrees clear and branch centers symmetric', () => {
  const single = createLayoutNode({ top: 130, width: 100, height: 40 })
  const multiple = createLayoutNode({
    top: 400,
    width: 100,
    height: 40,
    children: Array.from({ length: 8 }, (_, index) => createLayoutNode({
      top: 190 + index * 60,
      width: 100,
      height: 40
    }))
  })
  const root = createLayoutNode({
    top: 370,
    width: 100,
    height: 40,
    children: [single, multiple]
  })

  const result = balanceTreeChildrenVertically(root, {
    getGap: () => 20
  })
  const rootCenter = root.top + root.height / 2
  const singleCenter = single.top + single.height / 2
  const multipleCenter = multiple.top + multiple.height / 2
  const grandchildCenters = multiple.children.map(
    node => node.top + node.height / 2
  )

  assert.equal(result.balancedParentCount, 2)
  assert.equal(rootCenter - singleCenter, 135)
  assert.equal(multipleCenter - rootCenter, 135)
  assert.deepEqual(
    grandchildCenters.slice(1).map((center, index) => (
      center - grandchildCenters[index]
    )),
    Array(7).fill(60)
  )
  assert.equal(multiple.children[0].top - (single.top + single.height), 20)
})

test('balanced vertical layout preserves the whole tree when a custom position exists', () => {
  const upper = createLayoutNode({ top: -40 })
  const lower = createLayoutNode({
    top: 40,
    children: Array.from({ length: 4 }, (_, index) => createLayoutNode({
      top: 20 + index * 20
    }))
  })
  const fixed = createLayoutNode({
    top: 20,
    children: [upper, lower],
    hasCustomPosition() {
      return true
    }
  })
  const normalUpper = createLayoutNode({ top: 100 })
  const normalLower = createLayoutNode({
    top: 140,
    children: Array.from({ length: 6 }, (_, index) => createLayoutNode({
      top: 100 + index * 20
    }))
  })
  const normal = createLayoutNode({
    top: 80,
    children: [normalUpper, normalLower]
  })
  const root = createLayoutNode({ top: 40, children: [fixed, normal] })

  const result = balanceTreeChildrenVertically(root, { getGap: () => 20 })

  assert.equal(result.balancedParentCount, 0)
  assert.equal(fixed.top, 20)
  assert.equal(normal.top, 80)
  assert.equal(upper.top, -40)
  assert.equal(lower.top, 40)
  assert.deepEqual(lower.children.map(node => node.top), [20, 40, 60, 80])
  assert.equal(normalUpper.top, 100)
  assert.equal(normalLower.top, 140)
  assert.deepEqual(
    normalLower.children.map(node => node.top),
    [100, 120, 140, 160, 180, 200]
  )
})

test('balanced vertical layout handles a 20,000-level tree without recursion', () => {
  const root = createLayoutNode({ top: 0 })
  let current = root
  for (let index = 1; index < 20_000; index += 1) {
    const child = createLayoutNode({ top: index })
    current.children.push(child)
    current = child
  }

  const result = balanceTreeChildrenVertically(root, { getGap: () => 1 })

  assert.equal(result.balancedParentCount, 19_999)
  assert.equal(current.top, 0)
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
