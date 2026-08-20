import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  MAX_MINDMAP_NODE_COUNT,
  MAX_MINDMAP_STABLE_UID_LENGTH,
  MAX_MINDMAP_TREE_DEPTH,
  assertMindmapImportDocument,
} from '../mindmap-import-validation.js'

const createNode = (uid, children) => ({
  data: uid === undefined ? {} : { uid },
  ...(children === undefined ? {} : { children }),
})

const createChain = length => {
  const root = createNode('1')
  let current = root
  for (let depth = 2; depth <= length; depth += 1) {
    const child = createNode(String(depth))
    current.children = [child]
    current = child
  }
  return root
}

test('import validation accepts bare and full documents and reports stable metrics', () => {
  const root = createNode('root', [createNode(2), createNode(undefined)])
  assert.deepEqual(assertMindmapImportDocument(root), {
    root,
    nodeCount: 3,
    treeDepth: 2,
  })
  assert.deepEqual(assertMindmapImportDocument({ root, layout: 'mindMap' }), {
    root,
    nodeCount: 3,
    treeDepth: 2,
  })
})

test('import validation rejects malformed root, data, children and child nodes', () => {
  assert.throws(() => assertMindmapImportDocument(null), /不是有效的脑图文档/)
  assert.throws(() => assertMindmapImportDocument({ children: [] }), /有效的脑图根节点/)
  assert.throws(
    () => assertMindmapImportDocument({ root: [], data: {} }),
    /有效的脑图根节点/
  )
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', {})),
    /children 必须是数组/
  )
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', [null])),
    /子节点必须是对象/
  )
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', [{ data: 'bad' }])),
    /data 必须是对象/
  )
})

test('import validation enforces the 20,000-node persistence boundary', () => {
  const root = createNode('root', Array.from(
    { length: MAX_MINDMAP_NODE_COUNT - 1 },
    (_, index) => createNode(String(index + 1))
  ))
  assert.equal(assertMindmapImportDocument(root).nodeCount, MAX_MINDMAP_NODE_COUNT)
  root.children.push(createNode('overflow'))
  assert.throws(
    () => assertMindmapImportDocument(root),
    /节点数量不能超过 20000/
  )
})

test('import validation enforces the 256-level persistence boundary iteratively', () => {
  assert.equal(
    assertMindmapImportDocument(createChain(MAX_MINDMAP_TREE_DEPTH)).treeDepth,
    MAX_MINDMAP_TREE_DEPTH
  )
  assert.throws(
    () => assertMindmapImportDocument(createChain(MAX_MINDMAP_TREE_DEPTH + 1)),
    /脑图层级不能超过 256/
  )
})

test('import validation rejects cycles, shared objects and unstable identifiers', () => {
  const cycle = createNode('cycle', [])
  cycle.children.push(cycle)
  assert.throws(() => assertMindmapImportDocument(cycle), /循环或重复引用/)

  const shared = createNode('shared')
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', [shared, shared])),
    /循环或重复引用/
  )

  const sharedData = {}
  assert.throws(
    () => assertMindmapImportDocument({
      data: sharedData,
      children: [{ data: sharedData }],
    }),
    /重复数据引用/
  )
  assert.throws(
    () => assertMindmapImportDocument(createNode('root', [createNode('root')])),
    /UID 重复: root/
  )
  assert.throws(() => assertMindmapImportDocument(createNode(' padded ')), /首尾空白/)
  assert.throws(
    () => assertMindmapImportDocument(createNode('x'.repeat(MAX_MINDMAP_STABLE_UID_LENGTH + 1))),
    /UID 不能超过 64 个字符/
  )
  assert.throws(() => assertMindmapImportDocument(createNode({})), /字符串或数字/)
  assert.throws(() => assertMindmapImportDocument(createNode(Infinity)), /有限数字/)
})

test('import parsing and editor replacement both use the shared validation boundary', async () => {
  const [importSource, editSource] = await Promise.all([
    readFile(new URL('../../components/MindMap/Import.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../components/MindMap/Edit.vue', import.meta.url), 'utf8'),
  ])
  assert.match(importSource, /import \{ assertMindmapImportDocument \}/)
  assert.equal((importSource.match(/assertMindmapImportDocument\(data\)/g) || []).length, 1)
  assert.doesNotMatch(importSource, /function isMindmapDocument/)
  assert.match(editSource, /async function onSetData\(data, request = \{\}\)/)
  assert.match(editSource, /assertMindmapImportDocument\(data\)/)
})
